"""Invalid data types: values that are not of their field's type, or could not be read.

This detector owns two cell conditions (``app.validation.contracts.conditions``):

* ``failed``: text where a number, date or yes/no value was expected ("approx. 5" as a
  quantity), or a number outside the supported range -> ``confirmed_rule_violation`` (rule
  ``invalid_value``);
* ``ambiguous``: a value with several readings and no value chosen ("1.234" without separator
  evidence, "04.03.2026" without a day/month order) -> ``extraction_uncertainty`` (rule
  ``ambiguous_value``).

It also reports usable values of the wrong type in a mapped number, date or yes/no field (a
date in a quantity column) as ``confirmed_rule_violation`` (rule ``wrong_type``). Checked
cells: the mapped fields (``fields``, default every mapped field of type number, date or
boolean) on item and total rows. More than ``max_cells_per_issue`` cells of one column and
problem become one grouped finding.

With ``check_unmapped_columns``, an unmapped column whose type profile is dominated by one
type (share at least ``dominance_threshold`` over at least ``min_non_empty`` values) and that
still holds values of other types gets one low-severity ``suspected_anomaly`` (rule
``minority_type``): an unusual observation, not an error, and without any score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field

from app.models.dataset import Cell, CellRef, Column, Row, RowKind, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import SemanticField
from app.models.values import DataType, ParseStatus
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
)
from app.validation.deterministic._support import row_guard, row_label

RULE_INVALID = "invalid_value"
RULE_WRONG_TYPE = "wrong_type"
RULE_AMBIGUOUS = "ambiguous_value"
RULE_MINORITY = "minority_type"

CHECKED_KINDS = frozenset(
    {
        RowKind.ITEM,
        RowKind.SUBTOTAL,
        RowKind.GRAND_TOTAL,
        RowKind.TAX,
        RowKind.GROSS_TOTAL,
        RowKind.ADJUSTMENT,
        RowKind.CARRY_FORWARD,
        RowKind.SUMMARY_LINE,
    }
)
_TYPED_FIELDS = frozenset({DataType.NUMBER, DataType.DATE, DataType.DATETIME, DataType.BOOLEAN})
_DATE_TYPES = frozenset({DataType.DATE, DataType.DATETIME})
_NOT_DOMINANT = frozenset({DataType.TEXT, DataType.MIXED, DataType.EMPTY, DataType.UNKNOWN})
_TYPE_NAMES = {
    DataType.NUMBER: "number",
    DataType.DATE: "date",
    DataType.DATETIME: "date and time",
    DataType.BOOLEAN: "yes/no value",
    DataType.TEXT: "text",
}


class DataTypeConformanceConfig(DetectorConfig):
    fields: list[str] | None = plannable(
        None, description="Fields to check; None = every mapped number, date or yes/no field."
    )
    max_cells_per_issue: int = plannable(
        50,
        ge=1,
        le=1000,
        description="Cells of one column and problem reported one by one; more are grouped.",
    )
    check_unmapped_columns: bool = Field(
        default=True, description="Look for minority types in unmapped columns."
    )
    dominance_threshold: float = Field(
        default=0.95, gt=0.5, le=1, description="Share of the dominant type in a column."
    )
    min_non_empty: int = Field(
        default=10, ge=2, description="Values a column needs before minorities are reported."
    )
    severity_invalid_value: Severity = Field(
        default=Severity.MEDIUM, description="Severity of values not readable as their type."
    )
    severity_wrong_type: Severity = Field(
        default=Severity.MEDIUM, description="Severity of values of another type."
    )
    severity_ambiguous_value: Severity = Field(
        default=Severity.MEDIUM, description="Severity of values with several readings."
    )
    severity_minority_type: Severity = Field(
        default=Severity.LOW, description="Severity of minority types in unmapped columns."
    )

    def severity_of(self, rule: str) -> Severity:
        return {
            RULE_INVALID: self.severity_invalid_value,
            RULE_WRONG_TYPE: self.severity_wrong_type,
            RULE_AMBIGUOUS: self.severity_ambiguous_value,
            RULE_MINORITY: self.severity_minority_type,
        }[rule]


@dataclass(frozen=True, slots=True)
class _Hit:
    row: Row
    cell: Cell
    ref: CellRef


class DataTypeConformanceDetector(Detector[DataTypeConformanceConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.data_type_conformance",
        name="Invalid data types",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Reports values that could not be read as their field's type (text in a quantity, "
            "an unreadable date), values with several possible readings (decimal separator, "
            "day/month order), values of the wrong type, and unusual minority types in "
            "unmapped columns."
        ),
        supported_data_types=(
            DataType.NUMBER,
            DataType.DATE,
            DataType.DATETIME,
            DataType.BOOLEAN,
            DataType.UNKNOWN,
            DataType.TEXT,
        ),
        applicability="Every dataset; mapped fields need a number, date or yes/no type.",
        evidence_classes=(
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
            EvidenceClass.EXTRACTION_UNCERTAINTY,
            EvidenceClass.SUSPECTED_ANOMALY,
        ),
        issue_categories=(IssueCategory.DATA_TYPE,),
        limitations=(
            "Only item and total rows are checked in mapped columns; headings and notes may "
            "hold any text.",
            "Minority types in unmapped columns are observations, not errors; no score is "
            "attached to them.",
        ),
        cost="low",
    )
    config_model = DataTypeConformanceConfig

    def applicability(
        self, context: ValidationContext, config: DataTypeConformanceConfig
    ) -> Applicability:
        return Applicability.yes("Every dataset can be checked for unreadable values.")

    def validate(
        self, context: ValidationContext, config: DataTypeConformanceConfig
    ) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            for field_def in _fields(context, config, table):
                self._check_field(context, config, table, field_def, result)
            if config.check_unmapped_columns:
                for column in table.columns:
                    if column.mapping is None:
                        self._check_minority(context, config, table, column, result)
        return result

    # ------------------------------------------------------------------ mapped fields
    def _check_field(
        self,
        context: ValidationContext,
        config: DataTypeConformanceConfig,
        table: Table,
        field_def: SemanticField,
        result: DetectorResult,
    ) -> None:
        column = table.column_for_field(field_def.field_id)
        if column is None:
            return
        groups: dict[str, list[_Hit]] = {RULE_INVALID: [], RULE_WRONG_TYPE: [], RULE_AMBIGUOUS: []}
        for row in context.rows(table, CHECKED_KINDS):
            with row_guard(result, table, row):
                cell = context.cell_at(row, column.column_id)
                if cell is None:
                    continue
                result.count(Coverage.CELLS_CHECKED)
                rule = _problem(cell, field_def.data_type)
                if rule is not None:
                    ref = context.issues.cell_ref(table, row, column.column_id)
                    groups[rule].append(_Hit(row, cell, ref))
        label = column_label(context, table, column)
        for rule, hits in groups.items():
            if not hits:
                continue
            result.count(f"cells_{rule}", len(hits))
            if len(hits) <= config.max_cells_per_issue:
                for hit in hits:
                    context.checkpoint()
                    result.add(
                        self._cell_issue(context, config, table, field_def, label, rule, hit)
                    )
            else:
                result.add(
                    self._group_issue(context, config, table, column, field_def, label, rule, hits)
                )

    def _cell_issue(
        self,
        context: ValidationContext,
        config: DataTypeConformanceConfig,
        table: Table,
        field_def: SemanticField,
        label: str,
        rule: str,
        hit: _Hit,
    ) -> ValidationIssue:
        expected = _TYPE_NAMES.get(field_def.data_type, field_def.data_type.value)
        raw = raw_preview(hit.cell)
        where = row_label(table, hit.row)
        if rule == RULE_AMBIGUOUS:
            title = f"Ambiguous value '{raw}' in {label}"
            explanation = (
                f"{where}: {label} reads '{raw}', which can be understood in more than one way, "
                "so no value was chosen and checks that need it abstain."
            )
        elif rule == RULE_WRONG_TYPE:
            actual = _TYPE_NAMES.get(hit.cell.data_type, hit.cell.data_type.value)
            title = f"{label} holds a {actual} instead of a {expected}: '{raw}'"
            explanation = (
                f"{where}: {label} must be a {expected}, but the cell holds a {actual} ('{raw}')."
            )
        else:
            title = f"{label} is not a valid {expected}: '{raw}'"
            explanation = (
                f"{where}: {label} must be a {expected}, but '{raw}' could not be read as one, "
                "so checks that need it abstain."
            )
        return context.issues.create(
            self.spec,
            rule_id=rule,
            category=IssueCategory.DATA_TYPE,
            severity=config.severity_of(rule),
            evidence_class=_evidence_class(rule),
            title=clip(title, 200),
            explanation=explanation,
            table=table,
            row=hit.row,
            cells=[hit.ref],
            observed_value=raw,
            evidence=[_value_evidence(label, [hit]), _type_rule(field_def, label, expected)],
            suggested_action=_action(rule, label, expected),
            subject=field_def.field_id,
        )

    def _group_issue(
        self,
        context: ValidationContext,
        config: DataTypeConformanceConfig,
        table: Table,
        column: Column,
        field_def: SemanticField,
        label: str,
        rule: str,
        hits: list[_Hit],
    ) -> ValidationIssue:
        expected = _TYPE_NAMES.get(field_def.data_type, field_def.data_type.value)
        listed = hits[: config.max_cells_per_issue]
        where = describe_rows([(table, hit.row) for hit in hits])
        problem = {
            RULE_AMBIGUOUS: "can be read in more than one way",
            RULE_WRONG_TYPE: f"are not of type {expected}",
        }.get(rule, f"could not be read as a {expected}")
        return context.issues.create(
            self.spec,
            rule_id=rule,
            category=IssueCategory.DATA_TYPE,
            severity=config.severity_of(rule),
            evidence_class=_evidence_class(rule),
            title=clip(f"{len(hits)} values in {label} {problem}", 200),
            explanation=(
                f"{len(hits)} values of {label} in table '{table.name}' ({where}) {problem}. "
                f"They are reported as one finding; the first {len(listed)} cells are "
                "highlighted."
            ),
            table=table,
            cells=[hit.ref for hit in listed],
            evidence=[
                _value_evidence(label, listed, total=len(hits)),
                _type_rule(field_def, label, expected),
            ],
            suggested_action=_action(rule, label, expected),
            subject=f"{field_def.field_id}:{column.source_column_number}",
        )

    # ------------------------------------------------------------------ unmapped columns
    def _check_minority(
        self,
        context: ValidationContext,
        config: DataTypeConformanceConfig,
        table: Table,
        column: Column,
        result: DetectorResult,
    ) -> None:
        profile = column.type_profile
        dominant = profile.dominant_type
        if (
            dominant in _NOT_DOMINANT
            or profile.non_empty < config.min_non_empty
            or profile.dominant_share < config.dominance_threshold
        ):
            return
        hits: list[_Hit] = []
        for row in context.rows(table, None):
            cell = context.cell_at(row, column.column_id)
            if cell is None or cell.is_empty or cell.parse_status is ParseStatus.MARKER:
                continue
            if cell.data_type is not dominant:
                hits.append(_Hit(row, cell, context.issues.cell_ref(table, row, column.column_id)))
        if not hits:
            return
        result.count("columns_with_minority_types")
        label = column_label(context, table, column)
        listed = hits[: config.max_cells_per_issue]
        name = _TYPE_NAMES.get(dominant, dominant.value)
        where = describe_rows([(table, hit.row) for hit in hits])
        result.add(
            context.issues.create(
                self.spec,
                rule_id=RULE_MINORITY,
                category=IssueCategory.DATA_TYPE,
                severity=config.severity_minority_type,
                evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
                title=clip(
                    f"{len(hits)} of {profile.non_empty} values in {label} are not of type {name}",
                    200,
                ),
                explanation=(
                    f"Column {label} of table '{table.name}' is not mapped to a profile field. "
                    f"Most of its values are of type {name} ({profile.dominant_share:.0%}), but "
                    f"{len(hits)} are not ({where}). This is an unusual observation, not "
                    "necessarily an error."
                ),
                table=table,
                cells=[hit.ref for hit in listed],
                evidence=[_value_evidence(label, listed, total=len(hits))],
                suggested_action=(
                    "Check whether these values were entered in the wrong column or mean "
                    "something special; map the column if it should be checked."
                ),
                subject=f"column:{column.source_column_number}",
            )
        )


def _fields(
    context: ValidationContext, config: DataTypeConformanceConfig, table: Table
) -> list[SemanticField]:
    if config.fields is None:
        candidates = [context.profile.field(c.mapping.field_id) for c in table.columns if c.mapping]
    else:
        candidates = [context.profile.field(f) for f in config.fields]
    return [f for f in candidates if f is not None and f.data_type in _TYPED_FIELDS]


def _problem(cell: Cell, expected: DataType) -> str | None:
    condition = cell_condition(cell)
    if condition is CellCondition.FAILED:
        return RULE_INVALID
    if condition is CellCondition.AMBIGUOUS:
        return RULE_AMBIGUOUS
    if condition in (CellCondition.USABLE, CellCondition.INFERRED, CellCondition.TEXT):
        actual = cell.data_type
        if actual is expected or (actual in _DATE_TYPES and expected in _DATE_TYPES):
            return None
        return RULE_WRONG_TYPE
    return None


def _evidence_class(rule: str) -> EvidenceClass:
    if rule == RULE_AMBIGUOUS:
        return EvidenceClass.EXTRACTION_UNCERTAINTY
    return EvidenceClass.CONFIRMED_RULE_VIOLATION


def _value_evidence(label: str, hits: list[_Hit], total: int | None = None) -> EvidenceItem:
    count = total if total is not None else len(hits)
    notes = sorted({hit.cell.parse_note for hit in hits if hit.cell.parse_note})[:3]
    detail = f"{label}: " + "; ".join(f"'{raw_preview(hit.cell)}'" for hit in hits[:5])
    if notes:
        detail += ". Reading notes: " + " ".join(notes)
    return EvidenceItem(
        kind=EvidenceKind.VALUE,
        label="Values as written" if count > 1 else "Value as written",
        detail=clip(detail, 1000),
        cells=[hit.ref for hit in hits],
        data={"cells": count, "cells_highlighted": len(hits)},
    )


def _type_rule(field_def: SemanticField, label: str, expected: str) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.RULE,
        label="Field type",
        detail=f"The profile defines {label} as a {expected}.",
        data={"field": field_def.field_id, "data_type": field_def.data_type.value},
    )


def _action(rule: str, label: str, expected: str) -> str:
    if rule == RULE_AMBIGUOUS:
        return (
            f"Confirm how {label} is written (decimal separator or day/month order), for "
            "example by correcting the value in the source, then upload it again."
        )
    return f"Correct {label} in the source document so it holds a {expected}."
