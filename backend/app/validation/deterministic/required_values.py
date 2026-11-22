"""Missing required values: empty cells where the profile requires a value.

This detector owns the cell condition ``empty`` where the profile requires a value
(``app.validation.contracts.conditions``). For every table, every required field (profile
fields with ``required: true``, or the configured ``fields``) and every row of the field's
``required_row_kinds`` (item rows by default), an EMPTY cell is a ``confirmed_rule_violation``
(rule ``required_value``). Cells that hold a value marker ("Incl.", "psch"), an error, an
ambiguous or failed reading, or an unavailable formula result are not missing: their owners
report them.

Exemptions come from the profile (``detector_defaults``): a row is exempt for the listed fields
when every condition of the exemption holds: its unit resolves to one of ``unit_dimensions``
(a lump sum needs no quantity or unit price), and/or the item is not counted in totals
(``not_counted``: ``counts_toward_totals`` is not True, so a "nur EP" or optional item may
leave its total blank), and/or the row's ``text_field`` matches ``text_pattern`` (an item type
"Freie Menge" leaves the quantity open), and/or the row's ``marker_field`` holds one of
``markers`` (a unit price written as a "not offered" token leaves the total blank), and/or
every field in ``zero_fields`` holds the number 0 (a position with quantity 0, such as an
uncommissioned change-order item, needs no unit).
``only_populated_columns``: a required column that is
empty in every checked row of a table (an unpriced tender bill) is not reported row by row; the
run notes it once instead. More than ``max_row_issues_per_field`` missing cells of one field in
one table become one grouped finding. Required fields that are not mapped at all are a mapping
problem, reported by ``deterministic.extraction_quality``; this detector notes them and
abstains.
"""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core import patterns
from app.models.dataset import CellRef, Row, RowKind, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import FIELD_ID_PATTERN, RULE_ID_PATTERN, FieldRole, SemanticField
from app.models.values import DataType, ValueMarker
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
from app.validation.deterministic._reference_support import checked_pattern, clip, describe_rows
from app.validation.deterministic._support import field_label, row_guard, row_label

RULE_REQUIRED = "required_value"
CELLS_MISSING = "cells_missing"
CELLS_EXEMPT = "cells_exempt"
COLUMNS_EMPTY = "columns_skipped_empty"
_HIGH_ROLES = frozenset({FieldRole.QUANTITY, FieldRole.MONETARY})


class Exemption(BaseModel):
    """Rows exempt from the requirement for ``fields`` (every given condition must hold)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    fields: list[str] = Field(min_length=1)
    unit_dimensions: list[str] = Field(default_factory=list)
    not_counted: bool = False
    text_field: str | None = None  # with text_pattern: the row's text in this field matches
    text_pattern: str | None = None
    marker_field: str | None = None  # with markers: the row's cell in this field holds one
    markers: list[ValueMarker] = Field(default_factory=list)
    zero_fields: list[str] = Field(default_factory=list)  # the row's number here is 0

    @field_validator("fields")
    @classmethod
    def _field_ids(cls, value: list[str]) -> list[str]:
        for field_id in value:
            if not _valid_field_id(field_id):
                raise ValueError(f"invalid field id {field_id!r}")
        return value

    @field_validator("zero_fields")
    @classmethod
    def _zero_field_ids(cls, value: list[str]) -> list[str]:
        for field_id in value:
            if not _valid_field_id(field_id):
                raise ValueError(f"invalid field id {field_id!r}")
        return value

    @field_validator("text_field", "marker_field")
    @classmethod
    def _text_field_id(cls, value: str | None) -> str | None:
        if value is not None and not _valid_field_id(value):
            raise ValueError(f"invalid field id {value!r}")
        return value

    @field_validator("text_pattern")
    @classmethod
    def _valid_pattern(cls, value: str | None) -> str | None:
        return None if value is None else checked_pattern(value, groups=None)

    @model_validator(mode="after")
    def _has_condition(self) -> Exemption:
        if (self.text_field is None) != (self.text_pattern is None):
            raise ValueError("text_field and text_pattern go together")
        if (self.marker_field is None) != (not self.markers):
            raise ValueError("marker_field and markers go together")
        if not (
            self.unit_dimensions
            or self.not_counted
            or self.text_pattern
            or self.markers
            or self.zero_fields
        ):
            raise ValueError(
                "an exemption needs unit_dimensions, not_counted, text_pattern, markers or "
                "zero_fields"
            )
        return self


class RequiredValuesConfig(DetectorConfig):
    fields: list[str] | None = plannable(
        None,
        description="Fields to check; None = every profile field marked required.",
    )
    severity_by_field: dict[str, Severity] = plannable(
        default_factory=dict,
        description="Severity per field; default high for quantities and amounts, else medium.",
    )
    max_row_issues_per_field: int = plannable(
        50,
        ge=1,
        le=1000,
        description="Missing cells of one field and table reported one by one; more are grouped.",
    )
    only_populated_columns: bool = Field(
        default=True,
        description="Skip a required column that is empty in every checked row of a table "
        "(an unpriced bill), with one note instead of one finding per row.",
    )
    exemptions: list[Exemption] = Field(
        default_factory=list, description="Rows exempt from the requirement (profile rules)."
    )

    @field_validator("fields")
    @classmethod
    def _field_ids(cls, value: list[str] | None) -> list[str] | None:
        for field_id in value or ():
            if not _valid_field_id(field_id):
                raise ValueError(f"invalid field id {field_id!r}")
        return value


class RequiredValuesDetector(Detector[RequiredValuesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.required_values",
        name="Missing required values",
        version="1.3.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Reports empty cells in fields the profile requires (for example the quantity, "
            "unit, unit price and total of an item), with profile exemptions for lump sums, "
            "for items that are not counted in totals and for marked item types."
        ),
        supported_data_types=(DataType.EMPTY,),
        applicability=(
            "Datasets whose profile marks fields as required (or a plan that names fields); "
            "each field is checked in the tables that map it."
        ),
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.MISSING_VALUE,),
        limitations=(
            "Only cells that are truly empty are reported; value markers such as 'Incl.' or "
            "'psch' count as values.",
            "A required column that is empty in every checked row (an unpriced bill) is noted "
            "once, not reported row by row (only_populated_columns).",
            "Required fields without a mapped column are reported by the extraction quality "
            "check, not here.",
        ),
        cost="low",
    )
    config_model = RequiredValuesConfig

    def applicability(
        self, context: ValidationContext, config: RequiredValuesConfig
    ) -> Applicability:
        fields = _fields(context, config)
        if not fields:
            return Applicability.no("The profile marks no field as required.")
        mapped = [
            t.name for t in context.tables() if any(t.column_for_field(f.field_id) for f in fields)
        ]
        if not mapped:
            labels = ", ".join(f.label for f in fields)
            return Applicability.no(f"No required field is mapped in any table ({labels}).")
        return Applicability.yes(f"Required fields are mapped in: {', '.join(mapped)}.")

    def validate(self, context: ValidationContext, config: RequiredValuesConfig) -> DetectorResult:
        result = DetectorResult()
        fields = _fields(context, config)
        for table in context.tables():
            unmapped = [f.label for f in fields if table.column_for_field(f.field_id) is None]
            if unmapped:
                result.notes.append(
                    f"Table '{table.name}': {', '.join(unmapped)} not mapped; not checked."
                )
            for field_def in fields:
                if table.column_for_field(field_def.field_id) is not None:
                    self._check_field(context, config, table, field_def, result)
        return result

    def _check_field(
        self,
        context: ValidationContext,
        config: RequiredValuesConfig,
        table: Table,
        field_def: SemanticField,
        result: DetectorResult,
    ) -> None:
        field_id = field_def.field_id
        missing: list[Row] = []
        populated = 0
        for row in context.rows(table, frozenset(field_def.required_row_kinds)):
            with row_guard(result, table, row):
                result.count(Coverage.CELLS_CHECKED)
                condition = cell_condition(context.cell(table, row, field_id))
                if condition is not CellCondition.EMPTY:
                    populated += 1
                elif _exempt(context, config, table, row, field_id):
                    result.count(CELLS_EXEMPT)
                else:
                    missing.append(row)
        if not missing:
            return
        label = field_label(context, field_id)
        if config.only_populated_columns and populated == 0:
            result.count(COLUMNS_EMPTY)
            result.notes.append(
                f"Table '{table.name}': {label} is empty in every checked row (for example an "
                "unpriced bill), so missing values were not reported one by one."
            )
            return
        result.count(CELLS_MISSING, len(missing))
        severity = config.severity_by_field.get(field_id) or _default_severity(field_def)
        if len(missing) <= config.max_row_issues_per_field:
            for row in missing:
                context.checkpoint()
                result.add(self._issue(context, table, row, field_def, label, severity))
        else:
            cap = config.max_row_issues_per_field
            result.add(self._group(context, table, missing, field_def, label, severity, cap))

    def _issue(
        self,
        context: ValidationContext,
        table: Table,
        row: Row,
        field_def: SemanticField,
        label: str,
        severity: Severity,
    ) -> ValidationIssue:
        ref = context.cell_ref(table, row, field_def.field_id)
        return context.issues.create(
            self.spec,
            rule_id=RULE_REQUIRED,
            category=IssueCategory.MISSING_VALUE,
            severity=severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Missing {label} in {row_label(table, row)}", 200),
            explanation=(
                f"{row_label(table, row)} is {_kind_text(row.kind)}, and the profile requires "
                f"{label} on such rows, but the cell is empty."
            ),
            table=table,
            row=row,
            cells=[ref],
            evidence=[_rule_evidence(field_def, label), _empty_evidence(label, [ref])],
            suggested_action=_action(label),
            subject=field_def.field_id,
        )

    def _group(
        self,
        context: ValidationContext,
        table: Table,
        rows: list[Row],
        field_def: SemanticField,
        label: str,
        severity: Severity,
        cap: int,
    ) -> ValidationIssue:
        refs = [context.cell_ref(table, row, field_def.field_id) for row in rows[:cap]]
        where = describe_rows([(table, row) for row in rows])
        return context.issues.create(
            self.spec,
            rule_id=RULE_REQUIRED,
            category=IssueCategory.MISSING_VALUE,
            severity=severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{label} is missing in {len(rows)} rows of '{table.name}'", 200),
            explanation=(
                f"The profile requires {label}, but it is empty in {len(rows)} rows of table "
                f"'{table.name}' ({where}). They are reported as one finding; the first "
                f"{len(refs)} cells are highlighted."
            ),
            table=table,
            cells=refs,
            evidence=[
                _rule_evidence(field_def, label),
                _empty_evidence(label, refs, total=len(rows)),
            ],
            suggested_action=_action(label),
            subject=field_def.field_id,
        )


def _fields(context: ValidationContext, config: RequiredValuesConfig) -> list[SemanticField]:
    profile = context.profile
    if config.fields is None:
        return [f for f in profile.fields if f.required]
    return [f for f in (profile.field(i) for i in config.fields) if f is not None]


def _exempt(
    context: ValidationContext,
    config: RequiredValuesConfig,
    table: Table,
    row: Row,
    field_id: str,
) -> bool:
    for exemption in config.exemptions:
        if field_id not in exemption.fields:
            continue
        if exemption.not_counted and row.counts_toward_totals is True:
            continue
        if exemption.unit_dimensions:
            lookup = context.unit(table, row)
            if lookup is None or lookup.unit.dimension not in exemption.unit_dimensions:
                continue
        if exemption.text_field is not None and exemption.text_pattern is not None:
            text = context.text(table, row, exemption.text_field)
            if not text or patterns.search(exemption.text_pattern, text) is None:
                continue
        marker_field = exemption.marker_field
        if marker_field and context.marker(table, row, marker_field) not in exemption.markers:
            continue
        if any(context.number(table, row, f) != 0 for f in exemption.zero_fields):
            continue
        return True
    return False


def _default_severity(field_def: SemanticField) -> Severity:
    return Severity.HIGH if field_def.role in _HIGH_ROLES else Severity.MEDIUM


def _kind_text(kind: RowKind) -> str:
    return "an item" if kind is RowKind.ITEM else f"a {kind.value.replace('_', ' ')} row"


def _rule_evidence(field_def: SemanticField, label: str) -> EvidenceItem:
    kinds = ", ".join(k.value for k in field_def.required_row_kinds)
    return EvidenceItem(
        kind=EvidenceKind.RULE,
        label="Required field",
        detail=f"The profile marks {label} as required on rows of kind: {kinds}.",
        data={"field": field_def.field_id, "required_row_kinds": kinds},
    )


def _empty_evidence(label: str, refs: list[CellRef], total: int | None = None) -> EvidenceItem:
    count = total if total is not None else len(refs)
    detail = f"{label} is empty." if count == 1 else f"{label} is empty in {count} cells."
    return EvidenceItem(
        kind=EvidenceKind.VALUE,
        label="Empty cell" if count == 1 else "Empty cells",
        detail=detail,
        cells=refs,
        data={"cells": count, "cells_highlighted": len(refs)},
    )


def _action(label: str) -> str:
    return (
        f"Fill in the {label} in the source document, or confirm that it is intentionally "
        "blank (for example an item priced elsewhere)."
    )


def _valid_field_id(field_id: str) -> bool:
    return re.fullmatch(FIELD_ID_PATTERN, field_id) is not None
