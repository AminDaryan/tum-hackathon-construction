"""Unit vocabulary: units that the profile does not know.

An item row whose unit text ``ValidationContext.unit`` cannot resolve (it knows the profile's
units and aliases, leading multipliers such as "100 St" and the units a reviewer aliased in the
extraction review) has a unit nobody can interpret, so unit-dependent checks ignore the row.
Unknown units are grouped per table by their comparison key
(:func:`app.profiles.units.unit_key`, so "VE", "ve" and "V.E." are one group): one finding per
distinct unknown unit, ``needs_external_context`` (whether "VE" is a valid unit is a question
of vocabulary the document cannot answer), with the affected cells capped and the full count
in the evidence. Empty units are left to ``required_values``; unreadable cells to their owners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from app.models.dataset import CellRef, Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import FIELD_ID_PATTERN, FieldRole
from app.models.values import DataType
from app.profiles.units import unit_key
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition, skip_key
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
from app.validation.deterministic._reference_support import clip, describe_rows
from app.validation.deterministic._support import field_label, row_guard

RULE_UNKNOWN_UNIT = "unknown_unit"
UNKNOWN_UNITS = "unknown_units"  # coverage: distinct unknown units (groups)
_MAX_KEY_CHARS = 200  # unit texts are short; longer text is keyed by its beginning
_MAX_SPELLINGS = 5
_PROFILE_UNITS_LISTED = 12
_READABLE = frozenset({CellCondition.TEXT, CellCondition.USABLE, CellCondition.INFERRED})


class UnitVocabularyConfig(DetectorConfig):
    unit_field: str = plannable(
        "unit", pattern=FIELD_ID_PATTERN, description="Field holding the unit of item rows."
    )
    severity: Severity = plannable(Severity.LOW, description="Severity of unknown units.")
    max_cells_per_issue: int = plannable(
        200, ge=1, le=1000, description="Cells highlighted per unknown unit."
    )


@dataclass(slots=True)
class _UnknownUnit:
    """All rows of one table whose unit has the same unknown key."""

    key: str
    spellings: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    cells: list[CellRef] = field(default_factory=list)


class UnitVocabularyDetector(Detector[UnitVocabularyConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.unit_vocabulary",
        name="Unit vocabulary",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Reports units of item rows that the profile's unit vocabulary does not know "
            "(after aliases, leading multipliers such as '100 St' and reviewer unit aliases), "
            "one finding per distinct unknown unit and table. Such rows cannot take part in "
            "unit-dependent checks until the unit is corrected or confirmed as an alias."
        ),
        required_fields=("unit",),
        supported_data_types=(DataType.TEXT,),
        applicability="The unit field is mapped and the profile defines a unit vocabulary.",
        evidence_classes=(EvidenceClass.NEEDS_EXTERNAL_CONTEXT,),
        issue_categories=(IssueCategory.UNIT,),
        limitations=(
            "Only the profile's vocabulary, leading multipliers and reviewer aliases are "
            "known: a correct unit missing from the profile is reported until it is added or "
            "aliased.",
            "Units are grouped by their normalized spelling; different spellings of one "
            "unknown unit that normalize differently are reported separately.",
        ),
        cost="low",
    )
    config_model = UnitVocabularyConfig

    def required_fields(self, config: UnitVocabularyConfig) -> tuple[str, ...]:
        return (config.unit_field,)

    def applicability(
        self, context: ValidationContext, config: UnitVocabularyConfig
    ) -> Applicability:
        if context.units.is_empty:
            return Applicability.no(
                f"Profile '{context.profile.profile_id}' defines no unit vocabulary."
            )
        definition = context.profile_field(config.unit_field)
        if definition is not None and definition.role is not FieldRole.UNIT:
            return Applicability.no(
                f"Field '{config.unit_field}' is not a unit field of profile "
                f"'{context.profile.profile_id}'."
            )
        return super().applicability(context, config)

    def validate(self, context: ValidationContext, config: UnitVocabularyConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            if not context.has_fields(table, config.unit_field):
                continue
            groups: dict[str, _UnknownUnit] = {}
            for row in context.rows(table):
                with row_guard(result, table, row):
                    _check_row(context, config, table, row, groups, result)
            for group in groups.values():
                context.checkpoint()
                result.count(UNKNOWN_UNITS)
                result.add(self._issue(context, config, table, group))
        return result

    def _issue(
        self,
        context: ValidationContext,
        config: UnitVocabularyConfig,
        table: Table,
        group: _UnknownUnit,
    ) -> ValidationIssue:
        unit_label = field_label(context, config.unit_field)
        shown = clip(group.spellings[0], 40)
        count = len(group.rows)
        rows_text = "1 row" if count == 1 else f"{count} rows"
        listed = group.cells[: config.max_cells_per_issue]
        spellings = ", ".join(f"'{clip(s, 40)}'" for s in group.spellings)
        known = [unit.unit_id for unit in context.units.units()]
        known_text = ", ".join(known[:_PROFILE_UNITS_LISTED]) + (
            f" and {len(known) - _PROFILE_UNITS_LISTED} more"
            if len(known) > _PROFILE_UNITS_LISTED
            else ""
        )
        highlighted = (
            f" The first {len(listed)} cells are highlighted." if count > len(listed) else ""
        )
        return context.issues.create(
            self.spec,
            rule_id=RULE_UNKNOWN_UNIT,
            category=IssueCategory.UNIT,
            severity=config.severity,
            evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            title=clip(
                f"Unit '{shown}' is not in the profile's unit vocabulary ({rows_text})", 200
            ),
            explanation=(
                f"{describe_rows([(table, row) for row in group.rows])} "
                f"{'uses' if count == 1 else 'use'} the {unit_label} "
                f"'{shown}', which neither the unit vocabulary of profile "
                f"'{context.profile.profile_id}', a leading multiplier (such as '100 St') nor a "
                "reviewer's unit alias resolves. Checks that depend on the unit ignore these "
                f"rows.{highlighted}"
            ),
            table=table,
            cells=listed,
            observed_value=group.spellings[0],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Unit as written",
                    detail=f"{rows_text} with the {unit_label} {spellings}.",
                    cells=listed,
                    data={
                        "unit_key": group.key,
                        "rows": count,
                        "cells_highlighted": len(listed),
                        "spellings": ", ".join(group.spellings),
                    },
                ),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Profile unit vocabulary",
                    detail=f"Profile '{context.profile.profile_id}' defines {len(known)} units "
                    f"({known_text}) with their aliases.",
                    data={"profile_units": len(known)},
                ),
            ],
            suggested_action=(
                f"Correct the unit in the source document, or confirm '{shown}' as an alias of a "
                "profile unit in the extraction review (unit aliases), then validate again."
            ),
            subject=group.key,
        )


def _check_row(
    context: ValidationContext,
    config: UnitVocabularyConfig,
    table: Table,
    row: Row,
    groups: dict[str, _UnknownUnit],
    result: DetectorResult,
) -> None:
    """Resolve one item row's unit; collect it into its group when it is unknown."""
    cell = context.cell(table, row, config.unit_field)
    condition = cell_condition(cell)
    if condition is CellCondition.EMPTY:
        result.count(Coverage.ROWS_SKIPPED_MISSING_INPUTS)
        return
    if condition not in _READABLE:
        result.count(skip_key(condition) or Coverage.ROWS_SKIPPED_NOT_APPLICABLE)
        return
    result.count(Coverage.ROWS_CHECKED)
    if context.unit(table, row, config.unit_field) is not None:
        result.count(Coverage.ROWS_CONSISTENT)
        return
    result.count(Coverage.ROWS_INCONSISTENT)
    text = context.text(table, row, config.unit_field) or ""
    key = unit_key(text[:_MAX_KEY_CHARS])
    group = groups.setdefault(key, _UnknownUnit(key=key))
    spelling = clip(text, 80)
    if spelling not in group.spellings and len(group.spellings) < _MAX_SPELLINGS:
        group.spellings.append(spelling)
    group.rows.append(row)
    if len(group.cells) < config.max_cells_per_issue:
        group.cells.append(context.cell_ref(table, row, config.unit_field))
