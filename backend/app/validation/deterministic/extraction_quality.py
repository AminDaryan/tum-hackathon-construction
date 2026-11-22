"""Extraction uncertainty: low OCR confidence, header and mapping doubts, structure warnings.

This detector owns what the extraction itself could not establish reliably (ADR 0007). Every
finding is ``extraction_uncertainty``:

* ``low_confidence``: mapped cells whose ``extraction_confidence`` (OCR/PDF sources only; XLSX
  and CSV cells have none and never produce this finding) is below the run's
  ``ValidationLimits.low_confidence_threshold``, the same threshold the issue factory uses to
  downgrade findings: low, medium below half of it. Empty cells and cells another detector
  owns (error, unavailable, ambiguous, failed) are skipped. More than ``max_issues_per_column``
  cells of one column and confidence band form one grouped finding.
* ``no_mapped_columns``: no column of a table matches a profile field (a cover sheet, a notes
  page, or a header that was not recognized): one finding, and the table's other structure
  findings are omitted.
* ``header_uncertain``: the header row was inferred from the layout, taken from the first row,
  or not found (``HeaderMethod`` STRUCTURAL, FIRST_ROW, NONE): medium.
* ``required_field_unmapped``: a required profile field has no column, so the checks that need
  it could not run (``deterministic.required_values`` abstains on it): medium.
* ``fuzzy_mapping``: a column mapped by approximate header spelling (a string-similarity
  ratio, not a probability that the mapping is right): low.
* ``extraction_warning``: each other normalization warning that needs review (for example
  ``column_mapping_ambiguous``, ``decimal_separator_conflict``, ``unclassified_amount_row``):
  medium. Warnings about cells other detectors report one by one
  (``number_format_ambiguous``: data_type_conformance; ``formula_without_cached_result``:
  formula_errors) and the two this detector computes itself (``header_uncertain``,
  ``required_field_unmapped``) are not repeated.

Profiles without fields (generic) have nothing to map: only confidence and extraction
warnings are reported for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field

from app.models.dataset import (
    Cell,
    CellRef,
    Column,
    ExtractionWarning,
    HeaderMethod,
    MappingMethod,
    Row,
    RowKind,
    Table,
)
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._reference_support import (
    clip,
    column_label,
    describe_rows,
    raw_preview,
    short_digest,
)
from app.validation.deterministic._support import FieldId, row_guard, row_label

RULE_LOW_CONFIDENCE = "low_confidence"
RULE_NO_MAPPED_COLUMNS = "no_mapped_columns"
RULE_HEADER = "header_uncertain"
RULE_UNMAPPED = "required_field_unmapped"
RULE_FUZZY = "fuzzy_mapping"
RULE_WARNING = "extraction_warning"
# Confidence bands of low_confidence groups. Their names, the former fixed severities, stay in
# the group subjects so fingerprints do not depend on the configured severities.
_BELOW_HALF = "medium"  # below half the threshold
_BELOW = "low"  # below the threshold

# Warnings this detector does not repeat: cells reported one by one by their owner, and the
# conditions this detector computes from the tables itself.
NOT_REPEATED: frozenset[str] = frozenset(
    {
        "number_format_ambiguous",
        "formula_without_cached_result",
        "header_uncertain",
        "required_field_unmapped",
    }
)
_UNCERTAIN_HEADERS = {
    HeaderMethod.STRUCTURAL: "was inferred from the layout (a text row above typed data)",
    HeaderMethod.FIRST_ROW: "was taken from the first non-empty row",
    HeaderMethod.NONE: "was not found, so the columns are named by position",
}
_OWNED_ELSEWHERE = frozenset(
    {
        CellCondition.EMPTY,
        CellCondition.ERROR,
        CellCondition.UNAVAILABLE,
        CellCondition.AMBIGUOUS,
        CellCondition.FAILED,
    }
)
_CELLS_HIGHLIGHTED = 50


class ExtractionQualityConfig(DetectorConfig):
    fields: list[FieldId] | None = plannable(
        None,
        description="Fields whose cells are checked for low confidence; None = every mapped field.",
    )
    max_issues_per_column: int = plannable(
        200,
        ge=1,
        le=10_000,
        description="Low-confidence cells of one column and confidence band beyond which they "
        "form one finding.",
    )
    report_header_uncertainty: bool = Field(
        default=True, description="Report headers found by layout, first row or not at all."
    )
    report_fuzzy_mappings: bool = Field(
        default=True, description="Report columns mapped by approximate header spelling."
    )
    report_unmapped_fields: bool = Field(
        default=True, description="Report required profile fields without a column."
    )
    report_extraction_warnings: bool = Field(
        default=True, description="Report the other normalization warnings that need review."
    )
    severity_low_confidence: Severity = Field(
        default=Severity.LOW, description="Severity of values scored below the threshold."
    )
    severity_very_low_confidence: Severity = Field(
        default=Severity.MEDIUM, description="Severity of values scored below half the threshold."
    )
    severity_no_mapped_columns: Severity = Field(
        default=Severity.MEDIUM, description="Severity of tables without a mapped column."
    )
    severity_header_uncertain: Severity = Field(
        default=Severity.MEDIUM, description="Severity of headers found by layout or not at all."
    )
    severity_required_field_unmapped: Severity = Field(
        default=Severity.MEDIUM, description="Severity of required fields without a column."
    )
    severity_fuzzy_mapping: Severity = Field(
        default=Severity.LOW, description="Severity of columns mapped by approximate spelling."
    )
    severity_extraction_warning: Severity = Field(
        default=Severity.MEDIUM, description="Severity of other normalization warnings."
    )


@dataclass(frozen=True, slots=True)
class _Hit:
    row: Row
    cell: Cell
    ref: CellRef
    confidence: float


class ExtractionQualityDetector(Detector[ExtractionQualityConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.extraction_quality",
        name="Extraction uncertainty",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Reports what the extraction could not establish reliably: values read with low "
            "OCR confidence, unrecognized headers, uncertain or missing column mappings and "
            "other structure warnings."
        ),
        applicability="Every dataset.",
        evidence_classes=(EvidenceClass.EXTRACTION_UNCERTAINTY,),
        issue_categories=(IssueCategory.EXTRACTION,),
        limitations=(
            "Confidence is reported only where the extraction engine scores values (OCR/PDF); "
            "spreadsheet and CSV values are read verbatim.",
            "A header similarity is a similarity of spelling, not a probability that the "
            "mapping is right.",
        ),
        cost="low",
    )
    config_model = ExtractionQualityConfig

    def applicability(
        self, context: ValidationContext, config: ExtractionQualityConfig
    ) -> Applicability:
        return Applicability.yes("Extraction quality is checked for every dataset.")

    def validate(
        self, context: ValidationContext, config: ExtractionQualityConfig
    ) -> DetectorResult:
        result = DetectorResult()
        threshold = context.issues.low_confidence_threshold
        for table in context.tables():
            result.count("tables_checked")
            self._confidence(context, config, table, threshold, result)
            if context.profile.fields:
                self._structure(context, config, table, result)
        if config.report_extraction_warnings:
            self._warnings(context, config, result)
        return result

    # ------------------------------------------------------------------ confidence
    def _confidence(
        self,
        context: ValidationContext,
        config: ExtractionQualityConfig,
        table: Table,
        threshold: float,
        result: DetectorResult,
    ) -> None:
        for column in _checked_columns(table, config):
            groups: dict[str, list[_Hit]] = {_BELOW_HALF: [], _BELOW: []}
            for row in context.rows(table, kinds=None):
                if row.classification.kind is RowKind.BLANK:
                    continue
                with row_guard(result, table, row):
                    cell = context.cell_at(row, column.column_id)
                    if cell is None or cell.extraction_confidence is None:
                        continue
                    if cell_condition(cell) in _OWNED_ELSEWHERE:
                        continue
                    result.count(Coverage.CELLS_CHECKED)
                    confidence = cell.extraction_confidence
                    if confidence >= threshold:
                        continue
                    band = _BELOW_HALF if confidence < threshold / 2 else _BELOW
                    ref = context.issues.cell_ref(table, row, column.column_id)
                    groups[band].append(_Hit(row, cell, ref, confidence))
            label = column_label(context, table, column)
            for band, hits in groups.items():
                if not hits:
                    continue
                severity = (
                    config.severity_very_low_confidence
                    if band == _BELOW_HALF
                    else config.severity_low_confidence
                )
                result.count("cells_low_confidence", len(hits))
                if len(hits) <= config.max_issues_per_column:
                    for hit in hits:
                        context.checkpoint()
                        result.add(
                            self._cell_issue(
                                context, table, column, label, severity, hit, threshold
                            )
                        )
                else:
                    result.add(
                        self._group_issue(
                            context, table, column, label, band, severity, hits, threshold
                        )
                    )

    def _cell_issue(
        self,
        context: ValidationContext,
        table: Table,
        column: Column,
        label: str,
        severity: Severity,
        hit: _Hit,
        threshold: float,
    ) -> ValidationIssue:
        raw = raw_preview(hit.cell)
        return context.issues.create(
            self.spec,
            rule_id=RULE_LOW_CONFIDENCE,
            category=IssueCategory.EXTRACTION,
            severity=severity,
            evidence_class=EvidenceClass.EXTRACTION_UNCERTAINTY,
            title=clip(f"{label} read with low confidence: '{raw}'", 200),
            explanation=(
                f"{row_label(table, hit.row)}: the extraction engine scores this value "
                f"{hit.confidence:.2f}, below the threshold of {threshold:.2f}, so it is not "
                "treated as verified and findings that use it are downgraded."
            ),
            table=table,
            row=hit.row,
            cells=[hit.ref],
            observed_value=raw,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Value as extracted",
                    detail=f"{label} = '{raw}' (confidence {hit.confidence:.2f})",
                    cells=[hit.ref],
                    data={"confidence": hit.confidence, "threshold": threshold},
                )
            ],
            suggested_action=(
                "Compare the value with the original document and correct it if it was misread."
            ),
            subject=f"confidence:{_column_key(column)}",
        )

    def _group_issue(
        self,
        context: ValidationContext,
        table: Table,
        column: Column,
        label: str,
        band: str,
        severity: Severity,
        hits: list[_Hit],
        threshold: float,
    ) -> ValidationIssue:
        listed = hits[:_CELLS_HIGHLIGHTED]
        lowest = min(hit.confidence for hit in hits)
        below = "below half the threshold" if band == _BELOW_HALF else "below the threshold"
        return context.issues.create(
            self.spec,
            rule_id=RULE_LOW_CONFIDENCE,
            category=IssueCategory.EXTRACTION,
            severity=severity,
            evidence_class=EvidenceClass.EXTRACTION_UNCERTAINTY,
            title=clip(f"{len(hits)} values in {label} were read with low confidence", 200),
            explanation=clip(
                f"{len(hits)} values of {label} in table '{table.name}' "
                f"({describe_rows([(table, hit.row) for hit in hits])}) were scored {below} "
                f"of {threshold:.2f} by the extraction engine (lowest {lowest:.2f}). They are "
                f"reported as one finding; the first {len(listed)} cells are highlighted.",
                2000,
            ),
            table=table,
            cells=[hit.ref for hit in listed],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Values as extracted",
                    detail=clip(
                        f"{label}: "
                        + "; ".join(
                            f"'{raw_preview(hit.cell)}' ({hit.confidence:.2f})" for hit in hits[:5]
                        ),
                        1000,
                    ),
                    cells=[hit.ref for hit in listed],
                    data={
                        "cells": len(hits),
                        "lowest_confidence": lowest,
                        "threshold": threshold,
                    },
                )
            ],
            suggested_action=(
                f"Compare {label} with the original document, for example by checking the "
                "highlighted cells first."
            ),
            subject=f"confidence:{_column_key(column)}:{band}",
        )

    # ------------------------------------------------------------------ structure
    def _structure(
        self,
        context: ValidationContext,
        config: ExtractionQualityConfig,
        table: Table,
        result: DetectorResult,
    ) -> None:
        if not any(column.mapping is not None for column in table.columns):
            result.add(self._no_mapped_columns(context, config, table))
            return
        if config.report_header_uncertainty and table.header.method in _UNCERTAIN_HEADERS:
            result.add(self._header_issue(context, config, table))
        if config.report_unmapped_fields:
            for field in context.profile.fields:
                if field.required and table.column_for_field(field.field_id) is None:
                    result.add(
                        self._unmapped_issue(context, config, table, field.field_id, field.label)
                    )
        if config.report_fuzzy_mappings:
            for column in table.columns:
                if (
                    column.mapping is not None
                    and column.mapping.method is MappingMethod.HEADER_FUZZY
                ):
                    result.add(self._fuzzy_issue(context, config, table, column))

    def _table_issue(
        self,
        context: ValidationContext,
        table: Table | None,
        *,
        rule_id: str,
        severity: Severity,
        title: str,
        explanation: str,
        evidence: EvidenceItem,
        suggested_action: str,
        subject: str,
    ) -> ValidationIssue:
        return context.issues.create(
            self.spec,
            rule_id=rule_id,
            category=IssueCategory.EXTRACTION,
            severity=severity,
            evidence_class=EvidenceClass.EXTRACTION_UNCERTAINTY,
            title=clip(title, 200),
            explanation=clip(explanation, 2000),
            table=table,
            evidence=[evidence],
            suggested_action=suggested_action,
            subject=subject,
        )

    def _no_mapped_columns(
        self, context: ValidationContext, config: ExtractionQualityConfig, table: Table
    ) -> ValidationIssue:
        headers = [
            clip(" ".join(column.original_header.split()), 40)
            for column in table.columns
            if column.original_header and column.original_header.strip()
        ]
        shown = ", ".join(f"'{header}'" for header in headers[:10]) or "none"
        return self._table_issue(
            context,
            table,
            rule_id=RULE_NO_MAPPED_COLUMNS,
            severity=config.severity_no_mapped_columns,
            title=f"No column of table '{table.name}' matches the profile",
            explanation=(
                f"None of the {len(table.columns)} columns of table '{table.name}' was matched "
                f"to a field of the '{context.profile.name}' profile, so no check that needs a "
                "field ran on this table."
            ),
            evidence=EvidenceItem(
                kind=EvidenceKind.NOTE,
                label="Column headers",
                detail=clip(f"Headers: {shown}.", 1000),
                data={"columns": len(table.columns), "header_method": table.header.method.value},
            ),
            suggested_action=(
                "If the table holds data, map its columns to the profile's fields; if it does "
                "not (for example a cover sheet), no action is needed."
            ),
            subject=RULE_NO_MAPPED_COLUMNS,
        )

    def _header_issue(
        self, context: ValidationContext, config: ExtractionQualityConfig, table: Table
    ) -> ValidationIssue:
        header = table.header
        rows = ", ".join(str(number) for number in header.header_row_numbers) or "none"
        return self._table_issue(
            context,
            table,
            rule_id=RULE_HEADER,
            severity=config.severity_header_uncertain,
            title=f"Header row of table '{table.name}' was not recognized",
            explanation=(
                f"The header row of table '{table.name}' {_UNCERTAIN_HEADERS[header.method]}, "
                "not recognized from the profile's column names, so the column mapping (which "
                "column holds the quantity, the unit price, ...) may be wrong."
            ),
            evidence=EvidenceItem(
                kind=EvidenceKind.NOTE,
                label="Header detection",
                detail=clip(f"Method: {header.method.value}; header rows: {rows}.", 1000),
                data={
                    "method": header.method.value,
                    "header_rows": rows,
                    "matched_fields": len(header.matched_fields),
                },
            ),
            suggested_action="Review the column mapping of this table and correct it if needed.",
            subject=RULE_HEADER,
        )

    def _unmapped_issue(
        self,
        context: ValidationContext,
        config: ExtractionQualityConfig,
        table: Table,
        field_id: str,
        label: str,
    ) -> ValidationIssue:
        return self._table_issue(
            context,
            table,
            rule_id=RULE_UNMAPPED,
            severity=config.severity_required_field_unmapped,
            title=f"Required column '{label}' not found in table '{table.name}'",
            explanation=(
                f"The profile requires {label}, but no column of table '{table.name}' was "
                "matched to it, so the checks that need it (for example missing values and "
                "line totals) could not run."
            ),
            evidence=EvidenceItem(
                kind=EvidenceKind.RULE,
                label="Required field",
                detail=f"The '{context.profile.name}' profile marks {label} as required.",
                data={"field": field_id},
            ),
            suggested_action=(
                f"Map the column that holds {label}, or confirm that the table has none."
            ),
            subject=f"unmapped:{field_id}",
        )

    def _fuzzy_issue(
        self,
        context: ValidationContext,
        config: ExtractionQualityConfig,
        table: Table,
        column: Column,
    ) -> ValidationIssue:
        mapping = column.mapping
        assert mapping is not None
        label = column_label(context, table, column)
        header = clip(" ".join((column.original_header or "").split()), 60)
        similarity = f"{mapping.similarity:.2f}" if mapping.similarity is not None else "unknown"
        synonym = mapping.matched_synonym or "a synonym"
        return self._table_issue(
            context,
            table,
            rule_id=RULE_FUZZY,
            severity=config.severity_fuzzy_mapping,
            title=f"Column '{header}' was matched to {label} by approximate spelling",
            explanation=(
                f"The header '{header}' of table '{table.name}' resembles '{synonym}', a name "
                f"for {label}, with a string similarity of {similarity} (a similarity of "
                "spelling, not a probability that the mapping is right)."
            ),
            evidence=EvidenceItem(
                kind=EvidenceKind.NOTE,
                label="Column mapping",
                detail=f"'{header}' -> {label} (similarity {similarity}).",
                data={
                    "header": header,
                    "field": mapping.field_id,
                    "matched_synonym": mapping.matched_synonym,
                    "similarity": mapping.similarity,
                },
            ),
            suggested_action=f"Confirm that column '{header}' holds {label}, or remap it.",
            subject=f"fuzzy:{mapping.field_id}:{column.source_column_number}",
        )

    # ------------------------------------------------------------------ warnings
    def _warnings(
        self, context: ValidationContext, config: ExtractionQualityConfig, result: DetectorResult
    ) -> None:
        seen: set[tuple[str, str | None, str]] = set()
        for warning in context.dataset.extraction.warnings:
            if not warning.needs_review or warning.code in NOT_REPEATED:
                continue
            key = (warning.code, warning.table_id, warning.message)
            if key in seen:
                continue
            seen.add(key)
            result.count("extraction_warnings_reported")
            result.add(self._warning_issue(context, config, warning))

    def _warning_issue(
        self,
        context: ValidationContext,
        config: ExtractionQualityConfig,
        warning: ExtractionWarning,
    ) -> ValidationIssue:
        table = _table(context, warning.table_id)
        where = f" Location: {warning.source.describe()}." if warning.source is not None else ""
        message = " ".join(warning.message.split())
        return self._table_issue(
            context,
            table,
            rule_id=RULE_WARNING,
            severity=config.severity_extraction_warning,
            title=message,
            explanation=(
                f"{message}{where} The extraction flagged this as something that can affect "
                "values or structure, so related findings should be read with it in mind."
            ),
            evidence=EvidenceItem(
                kind=EvidenceKind.NOTE,
                label="Extraction warning",
                detail=clip(f"{warning.code}: {message}", 1000),
                data={"code": warning.code, "count": warning.count},
            ),
            suggested_action=(
                "Review the affected part of the table and correct the mapping or the "
                "values if needed."
            ),
            subject=f"warning:{warning.code}:{short_digest(message + where)}",
        )


def _checked_columns(table: Table, config: ExtractionQualityConfig) -> list[Column]:
    wanted = set(config.fields) if config.fields is not None else None
    return [
        column
        for column in table.columns
        if column.mapping is not None and (wanted is None or column.mapping.field_id in wanted)
    ]


def _table(context: ValidationContext, table_id: str | None) -> Table | None:
    if table_id is None:
        return None
    return next((table for table in context.tables() if table.table_id == table_id), None)


def _column_key(column: Column) -> str:
    return column.mapping.field_id if column.mapping else f"column:{column.source_column_number}"
