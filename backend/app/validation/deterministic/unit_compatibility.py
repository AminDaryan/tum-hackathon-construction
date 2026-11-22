"""Unit compatibility: advisory checks of units against descriptions and quantities.

Every finding is a ``semantic_warning``: the brief (Part E) allows contextual unit rules only
where the category is sufficiently established, and these rules judge from wording and
conventions, not from a fact the document states. Rows whose unit is empty or unknown are
ignored by every rule (``required_values`` and ``unit_vocabulary`` report those).

* ``<rule_id>`` of a profile description rule: the description matches ``description_pattern``
  (and not ``exclude_pattern``) while the unit's dimension is outside ``allowed_dimensions``
  ("Stundenlohnarbeiten" measured in m³) -> medium.
* ``fractional_count``: a unit counted in whole numbers (``integer_quantities``) with a usable
  quantity that has a fractional part -> low. A leading unit multiplier counts ("2.5" of
  "100 St" are 250 pieces); value markers and percentages are not quantities to judge.
* ``lump_sum_quantity``: a unit of dimension ``lump_sum`` with a usable quantity other than 1
  (or -1, a credited lump sum) -> low.
* ``same_description_dimension``: item rows of all tables with the same normalized description
  (NFKC, case folded, whitespace collapsed, at least ``min_description_words`` words) whose
  units span more than one dimension -> one finding per description, medium. Descriptions
  matching ``same_description_exclude_pattern`` (relative wording such as "wie vor, jedoch
  30 cm", which repeats verbatim for different work) are not compared.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar

from pydantic import Field, field_validator, model_validator

from app.core import patterns
from app.models.base import FrozenModel
from app.models.dataset import CellRef, Row, Table
from app.models.issue import (
    RULE_ID_PATTERN,
    Calculation,
    CalculationOperand,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import FIELD_ID_PATTERN
from app.models.values import DataType, significant_digits
from app.profiles.units import UnitLookup
from app.validation.contracts.conditions import (
    USABLE_CONDITIONS,
    CellCondition,
    Coverage,
    cell_condition,
    skip_key,
)
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import multiply
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
    checked_pattern,
    clip,
    describe_rows,
    match_window,
    short_digest,
)
from app.validation.deterministic._support import field_label, fmt, row_guard, row_label
from app.validation.support.text_keys import description_key

RULE_FRACTIONAL = "fractional_count"
RULE_LUMP_SUM = "lump_sum_quantity"
RULE_SAME_DESCRIPTION = "same_description_dimension"
BUILT_IN_RULES = frozenset({RULE_FRACTIONAL, RULE_LUMP_SUM, RULE_SAME_DESCRIPTION})
LUMP_SUM_DIMENSION = "lump_sum"  # the unit dimension of lump sums in profiles
_DIMENSION_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"  # as UnitDefinition.dimension

# Coverage keys specific to this detector.
ROWS_SKIPPED_UNKNOWN_UNIT = "rows_skipped_unknown_unit"
DESCRIPTIONS_CHECKED = "descriptions_checked"
DESCRIPTIONS_SKIPPED_UNUSABLE = "descriptions_skipped_unusable"
DESCRIPTION_RULES_EXCLUDED = "description_rule_matches_excluded"
TEXTS_TRUNCATED = "texts_truncated"
QUANTITIES_CHECKED = "quantities_checked"
QUANTITIES_SKIPPED_MISSING = "quantities_skipped_missing"
QUANTITIES_SKIPPED_MARKER = "quantities_skipped_marker"
QUANTITIES_SKIPPED_UNUSABLE = "quantities_skipped_unusable"
QUANTITIES_SKIPPED_PERCENT = "quantities_skipped_percent"
DESCRIPTIONS_NOT_GROUPED = "descriptions_not_grouped_excluded"
DESCRIPTION_GROUPS_COMPARED = "description_groups_compared"
DESCRIPTION_GROUPS_INCONSISTENT = "description_groups_inconsistent"

_ONE = Decimal(1)
_READABLE_UNIT = frozenset({CellCondition.TEXT, *USABLE_CONDITIONS})


class UnitDescriptionRule(FrozenModel):
    """Descriptions matching ``description_pattern`` (and not ``exclude_pattern``) are
    expected in units of ``allowed_dimensions``. Patterns are case-insensitive; their capture
    groups are not used (the whole match is shown as evidence), so any number is allowed."""

    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    description_pattern: str
    exclude_pattern: str | None = None
    allowed_dimensions: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=500)
    severity: Severity = Severity.MEDIUM

    @field_validator("description_pattern", "exclude_pattern")
    @classmethod
    def _valid_pattern(cls, value: str | None) -> str | None:
        return None if value is None else checked_pattern(value, groups=None)

    @field_validator("allowed_dimensions")
    @classmethod
    def _valid_dimensions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        bad = [d for d in value if not patterns.fullmatch(_DIMENSION_PATTERN, d) or d != d.lower()]
        if bad:
            raise ValueError(f"invalid dimension names: {bad}")
        return value

    @field_validator("rule_id")
    @classmethod
    def _not_built_in(cls, value: str) -> str:
        if value in BUILT_IN_RULES:
            raise ValueError(f"rule id {value!r} is reserved for a built-in check")
        return value


class UnitCompatibilityConfig(DetectorConfig):
    description_rules: tuple[UnitDescriptionRule, ...] = Field(
        default=(), description="Description wording -> allowed unit dimensions (profile)."
    )
    check_integer_quantities: bool = Field(
        default=True, description="Warn about fractional quantities in whole-number units."
    )
    check_lump_sum_quantity: bool = Field(
        default=True, description="Warn about lump sums with a quantity other than 1."
    )
    check_same_description_dimension: bool = Field(
        default=True,
        description="Warn when identical descriptions use units of different dimensions.",
    )
    min_description_words: int = Field(
        default=3, ge=1, le=50, description="Words a description needs to be compared."
    )
    same_description_exclude_pattern: str | None = Field(
        default=None,
        description="Descriptions matching this pattern are not compared with each other: "
        "relative wording ('wie vor, jedoch ...', 'as before but ...') repeats verbatim for "
        "different work (profile-controlled).",
    )
    description_field: str = plannable("description", pattern=FIELD_ID_PATTERN)
    quantity_field: str = plannable("quantity", pattern=FIELD_ID_PATTERN)
    unit_field: str = plannable("unit", pattern=FIELD_ID_PATTERN)
    max_cells_per_issue: int = plannable(
        50, ge=1, le=1000, description="Cells highlighted per description group."
    )
    severity_same_description_dimension: Severity = Field(
        default=Severity.MEDIUM,
        description="Severity of identical descriptions in units of different dimensions.",
    )
    severity_fractional_count: Severity = Field(
        default=Severity.LOW, description="Severity of fractions in whole-number units."
    )
    severity_lump_sum_quantity: Severity = Field(
        default=Severity.LOW, description="Severity of lump sums with a quantity other than 1."
    )

    @field_validator("same_description_exclude_pattern")
    @classmethod
    def _valid_exclude(cls, value: str | None) -> str | None:
        return None if value is None else checked_pattern(value, groups=None)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> UnitCompatibilityConfig:
        ids = [rule.rule_id for rule in self.description_rules]
        duplicates = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate description rule ids: {', '.join(duplicates)}")
        return self


@dataclass(frozen=True, slots=True)
class _Member:
    """An item row of a description group."""

    table_index: int
    table: Table
    row: Row
    unit_ref: CellRef
    lookup: UnitLookup
    unit_text: str


@dataclass(slots=True)
class _DescriptionGroup:
    shown: str  # the first description as written (clipped)
    members: list[_Member] = field(default_factory=list)


@dataclass(slots=True)
class _RowUnit:
    """The resolved unit of the row being checked."""

    lookup: UnitLookup
    ref: CellRef
    text: str

    @property
    def dimension(self) -> str:
        return self.lookup.unit.dimension


class UnitCompatibilityDetector(Detector[UnitCompatibilityConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.unit_compatibility",
        name="Unit compatibility",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Advisory warnings about units: descriptions whose wording the profile associates "
            "with other unit dimensions (for example hourly work measured in m³), fractional "
            "quantities in whole-number units, lump sums with a quantity other than 1, and "
            "identical descriptions measured in units of different dimensions. Findings are "
            "semantic warnings, never confirmed violations."
        ),
        required_fields=("unit",),
        optional_fields=("description", "quantity"),
        supported_data_types=(DataType.TEXT, DataType.NUMBER),
        applicability=(
            "The profile defines units, the unit field is mapped, and the description or "
            "quantity field needed by an enabled check is mapped in the same table."
        ),
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(IssueCategory.UNIT,),
        limitations=(
            "Advisory: description rules infer the kind of work from wording, which can be "
            "wrong; the findings are warnings for a reviewer, not errors.",
            "Only the first 500 characters of a description are matched against rules.",
            "Identical descriptions are compared after Unicode normalization, case folding and "
            "whitespace collapsing only; near-identical wording is not grouped.",
            "Rows with empty or unknown units are ignored.",
        ),
        cost="low",
    )
    config_model = UnitCompatibilityConfig

    def required_fields(self, config: UnitCompatibilityConfig) -> tuple[str, ...]:
        return (config.unit_field,)

    def applicability(
        self, context: ValidationContext, config: UnitCompatibilityConfig
    ) -> Applicability:
        if context.units.is_empty:
            return Applicability.no(
                f"Profile '{context.profile.profile_id}' defines no unit vocabulary."
            )
        needs = _enabled_check_fields(config)
        if not needs:
            return Applicability.no("Every unit compatibility check is switched off.")
        tables = [
            table.name
            for table in context.tables()
            if context.has_fields(table, config.unit_field)
            and any(context.has_fields(table, needed) for needed in needs)
        ]
        if not tables:
            fields = ", ".join(sorted({config.unit_field, *needs}))
            return Applicability.no(
                f"No table maps the unit field together with a field an enabled check needs "
                f"({fields})."
            )
        return Applicability.yes(f"Unit checks apply to: {', '.join(tables)}.")

    def validate(
        self, context: ValidationContext, config: UnitCompatibilityConfig
    ) -> DetectorResult:
        result = DetectorResult()
        _note_unknown_dimensions(context, config, result)
        groups: dict[str, _DescriptionGroup] = {}
        for table_index, table in enumerate(context.tables()):
            if not context.has_fields(table, config.unit_field):
                continue
            has_description = context.has_fields(table, config.description_field)
            has_quantity = context.has_fields(table, config.quantity_field)
            for row in context.rows(table):
                with row_guard(result, table, row):
                    unit = _row_unit(context, config, table, row, result)
                    if unit is None:
                        continue
                    result.count(Coverage.ROWS_CHECKED)
                    if has_description:
                        self._check_description(
                            context, config, table_index, table, row, unit, groups, result
                        )
                    if has_quantity:
                        self._check_quantity(context, config, table, row, unit, result)
        if config.check_same_description_dimension:
            self._report_description_groups(context, config, groups, result)
        truncated = result.coverage.get(TEXTS_TRUNCATED, 0)
        if truncated:
            result.notes.append(
                f"{truncated} description(s) are longer than the pattern window; only their "
                "first part was matched against the description rules."
            )
        return result

    # ------------------------------------------------------------------ descriptions
    def _check_description(
        self,
        context: ValidationContext,
        config: UnitCompatibilityConfig,
        table_index: int,
        table: Table,
        row: Row,
        unit: _RowUnit,
        groups: dict[str, _DescriptionGroup],
        result: DetectorResult,
    ) -> None:
        condition = cell_condition(context.cell(table, row, config.description_field))
        if condition is CellCondition.EMPTY:
            return
        if condition is not CellCondition.TEXT:
            result.count(DESCRIPTIONS_SKIPPED_UNUSABLE)
            return
        text = context.text(table, row, config.description_field) or ""
        result.count(DESCRIPTIONS_CHECKED)
        window, truncated = match_window(text)
        if truncated and (config.description_rules or config.same_description_exclude_pattern):
            result.count(TEXTS_TRUNCATED)
        if config.description_rules:
            for rule in config.description_rules:
                found = patterns.search(rule.description_pattern, window)
                if found is None or unit.dimension in rule.allowed_dimensions:
                    continue
                if rule.exclude_pattern and patterns.search(rule.exclude_pattern, window):
                    result.count(DESCRIPTION_RULES_EXCLUDED)
                    continue
                result.add(
                    self._description_issue(context, config, table, row, unit, rule, found[0])
                )
        if config.check_same_description_dimension:
            exclude = config.same_description_exclude_pattern
            if exclude and patterns.search(exclude, window):
                result.count(DESCRIPTIONS_NOT_GROUPED)
                return
            key = description_key(text)
            if key.count(" ") + 1 >= config.min_description_words:
                group = groups.setdefault(
                    short_digest(key), _DescriptionGroup(shown=clip(text, 80))
                )
                group.members.append(
                    _Member(table_index, table, row, unit.ref, unit.lookup, unit.text)
                )

    def _description_issue(
        self,
        context: ValidationContext,
        config: UnitCompatibilityConfig,
        table: Table,
        row: Row,
        unit: _RowUnit,
        rule: UnitDescriptionRule,
        matched: str,
    ) -> ValidationIssue:
        description = field_label(context, config.description_field)
        unit_label = field_label(context, config.unit_field)
        words = clip(" ".join(matched.split()), 60)
        allowed = _dimension_list(rule.allowed_dimensions)
        unit_shown = clip(unit.text, 30)
        description_ref = context.cell_ref(table, row, config.description_field)
        return context.issues.create(
            self.spec,
            rule_id=rule.rule_id,
            category=IssueCategory.UNIT,
            severity=rule.severity,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(
                f"'{words}' is usually measured in {allowed} units, not in {unit_shown} "
                f"({_dimension_name(unit.dimension)})",
                200,
            ),
            explanation=(
                f"{row_label(table, row)}: the {description} contains '{words}', which profile "
                f"rule '{rule.rule_id}' associates with {allowed} units, but the {unit_label} is "
                f"'{unit_shown}' ({unit.lookup.unit.label}, dimension "
                f"{_dimension_name(unit.dimension)}). {rule.rationale} This is an advisory "
                "warning: the item may be priced this way on purpose."
            ),
            table=table,
            row=row,
            cells=[unit.ref],
            inputs=[description_ref],
            observed_value=unit.text,
            expected_value=f"a unit of dimension {allowed}",
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Matched description wording",
                    detail=f"'{words}' in the {description}.",
                    cells=[description_ref],
                    data={"matched_text": words},
                ),
                _unit_evidence(unit, unit_label),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Description rule",
                    detail=f"Rule '{rule.rule_id}' allows units of dimension {allowed}. "
                    f"{rule.rationale}",
                    data={
                        "rule_id": rule.rule_id,
                        "allowed_dimensions": ", ".join(rule.allowed_dimensions),
                    },
                ),
            ],
            suggested_action=(
                f"Check whether the {unit_label} matches the work described; correct the unit "
                "or the description, or confirm the item if it is priced this way on purpose."
            ),
        )

    def _report_description_groups(
        self,
        context: ValidationContext,
        config: UnitCompatibilityConfig,
        groups: dict[str, _DescriptionGroup],
        result: DetectorResult,
    ) -> None:
        for digest, group in groups.items():
            if len(group.members) < 2:
                continue
            context.checkpoint()
            result.count(DESCRIPTION_GROUPS_COMPARED)
            if len({member.lookup.unit.dimension for member in group.members}) > 1:
                result.count(DESCRIPTION_GROUPS_INCONSISTENT)
                result.add(self._group_issue(context, config, digest, group))

    def _group_issue(
        self,
        context: ValidationContext,
        config: UnitCompatibilityConfig,
        digest: str,
        group: _DescriptionGroup,
    ) -> ValidationIssue:
        counts = Counter(member.lookup.unit.dimension for member in group.members)
        # Rows of the rarest dimension first, so a capped list still shows the deviation.
        ordered = sorted(
            group.members,
            key=lambda m: (
                counts[m.lookup.unit.dimension],
                m.lookup.unit.dimension,
                m.table_index,
                m.row.position,
            ),
        )
        anchor_table = ordered[0].table
        cap = config.max_cells_per_issue
        anchor = [m.unit_ref for m in ordered if m.table is anchor_table][:cap]
        inputs = [m.unit_ref for m in ordered][:cap]
        dimensions = sorted(counts, key=lambda d: (counts[d], d))
        per_dimension = "; ".join(
            f"{_dimension_name(d)} ({_unit_texts(group.members, d)}): "
            f"{describe_rows(_rows_of(ordered, d), 4)}"
            for d in dimensions
        )
        unit_label = field_label(context, config.unit_field)
        description = field_label(context, config.description_field)
        names = " and ".join(_dimension_name(d) for d in dimensions)
        count = len(group.members)
        return context.issues.create(
            self.spec,
            rule_id=RULE_SAME_DESCRIPTION,
            category=IssueCategory.UNIT,
            severity=config.severity_same_description_dimension,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(f"Same {description} measured in {names}: '{clip(group.shown, 60)}'", 200),
            explanation=(
                f"{count} item rows share the {description} '{group.shown}' (compared after "
                "Unicode normalization, case folding and whitespace collapsing), but their "
                f"units belong to different dimensions: {per_dimension}. Identical work is "
                "normally measured in one way, so one of the units may be wrong. This is an "
                "advisory warning."
                + (f" The first {len(inputs)} rows are listed." if count > len(inputs) else "")
            ),
            table=anchor_table,
            cells=anchor,
            inputs=inputs,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"{unit_label} by dimension",
                    detail=per_dimension,
                    cells=inputs,
                    data={
                        "rows": count,
                        "dimensions": ", ".join(dimensions),
                        "rows_per_dimension": "; ".join(f"{d}: {counts[d]}" for d in dimensions),
                        "rows_listed": len(inputs),
                    },
                ),
            ],
            suggested_action=(
                f"Check the {unit_label} of these rows: if they describe the same work, measure "
                f"it in one unit; if the work differs, make the {description} distinguishable."
            ),
            subject=digest,
        )

    # ------------------------------------------------------------------ quantities
    def _check_quantity(
        self,
        context: ValidationContext,
        config: UnitCompatibilityConfig,
        table: Table,
        row: Row,
        unit: _RowUnit,
        result: DetectorResult,
    ) -> None:
        lump_sum = config.check_lump_sum_quantity and unit.dimension == LUMP_SUM_DIMENSION
        whole = (
            not lump_sum and config.check_integer_quantities and unit.lookup.unit.integer_quantities
        )
        if not (lump_sum or whole):
            return
        condition = cell_condition(context.cell(table, row, config.quantity_field))
        value = context.number_value(table, row, config.quantity_field)
        if condition is CellCondition.EMPTY:
            result.count(QUANTITIES_SKIPPED_MISSING)
            return
        if condition is CellCondition.MARKER:
            result.count(QUANTITIES_SKIPPED_MARKER)
            return
        if condition not in USABLE_CONDITIONS or value is None:
            result.count(QUANTITIES_SKIPPED_UNUSABLE)
            return
        if value.is_percent:
            result.count(QUANTITIES_SKIPPED_PERCENT)
            return
        result.count(QUANTITIES_CHECKED)
        multiplier = unit.lookup.multiplier
        effective = value.value if multiplier is None else multiply(value.value, multiplier)
        if lump_sum and abs(effective) != _ONE:
            result.add(self._lump_sum_issue(context, config, table, row, unit, value.value))
        elif whole and is_fractional(effective):
            result.add(
                self._fractional_issue(context, config, table, row, unit, value.value, effective)
            )

    def _fractional_issue(
        self,
        context: ValidationContext,
        config: UnitCompatibilityConfig,
        table: Table,
        row: Row,
        unit: _RowUnit,
        quantity: Decimal,
        effective: Decimal,
    ) -> ValidationIssue:
        quantity_label = field_label(context, config.quantity_field)
        unit_label = field_label(context, config.unit_field)
        quantity_ref = context.cell_ref(table, row, config.quantity_field)
        definition = unit.lookup.unit
        shown = clip(unit.text, 30)
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.VALUE,
                label=quantity_label,
                detail=f"{quantity_label} {fmt(quantity)}.",
                cells=[quantity_ref],
                data={"quantity": format(quantity, "f")},
            ),
            _unit_evidence(unit, unit_label),
            EvidenceItem(
                kind=EvidenceKind.RULE,
                label="Whole-number unit",
                detail=f"The profile counts unit '{definition.unit_id}' ({definition.label}) in "
                "whole numbers.",
                data={"unit_id": definition.unit_id},
            ),
        ]
        counted = ""
        if unit.lookup.multiplier is not None:
            counted = f" ({fmt(quantity)} × {fmt(unit.lookup.multiplier)} = {fmt(effective)})"
            evidence.append(_multiplier_evidence(quantity, quantity_ref, unit, effective))
        return context.issues.create(
            self.spec,
            rule_id=RULE_FRACTIONAL,
            category=IssueCategory.UNIT,
            severity=config.severity_fractional_count,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(
                f"Fractional {quantity_label} {fmt(quantity)} in a unit counted in whole "
                f"numbers ({shown})",
                200,
            ),
            explanation=(
                f"{row_label(table, row)}: the {quantity_label} is {fmt(quantity)} and the "
                f"{unit_label} is '{shown}' ({definition.label}), which the profile counts in "
                f"whole numbers, but the count is fractional{counted}. This may be a typing "
                "error or a mix-up of units. This is an advisory warning."
            ),
            table=table,
            row=row,
            cells=[quantity_ref],
            inputs=[unit.ref],
            observed_value=fmt(effective),
            expected_value="a whole number",
            evidence=evidence,
            suggested_action=(
                f"Check the {quantity_label} and the {unit_label}: correct the quantity if the "
                "item is counted in whole units, or use a unit that allows fractions if it is "
                "measured."
            ),
        )

    def _lump_sum_issue(
        self,
        context: ValidationContext,
        config: UnitCompatibilityConfig,
        table: Table,
        row: Row,
        unit: _RowUnit,
        quantity: Decimal,
    ) -> ValidationIssue:
        quantity_label = field_label(context, config.quantity_field)
        unit_label = field_label(context, config.unit_field)
        quantity_ref = context.cell_ref(table, row, config.quantity_field)
        shown = clip(unit.text, 30)
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.VALUE,
                label=quantity_label,
                detail=f"{quantity_label} {fmt(quantity)}.",
                cells=[quantity_ref],
                data={"quantity": format(quantity, "f")},
            ),
            _unit_evidence(unit, unit_label),
            EvidenceItem(
                kind=EvidenceKind.RULE,
                label="Lump sum",
                detail="A lump sum is normally priced once: quantity 1 (or -1 when it is "
                "credited).",
            ),
        ]
        if unit.lookup.multiplier is not None:
            effective = multiply(quantity, unit.lookup.multiplier)
            evidence.append(_multiplier_evidence(quantity, quantity_ref, unit, effective))
        return context.issues.create(
            self.spec,
            rule_id=RULE_LUMP_SUM,
            category=IssueCategory.UNIT,
            severity=config.severity_lump_sum_quantity,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(f"Lump-sum item ({shown}) with {quantity_label} {fmt(quantity)}", 200),
            explanation=(
                f"{row_label(table, row)}: the {unit_label} '{shown}' is a lump sum "
                f"({unit.lookup.unit.label}), which is normally priced once (quantity 1), but "
                f"the {quantity_label} is {fmt(quantity)}. Several lump sums may be intended, or "
                "the unit may be wrong. This is an advisory warning."
            ),
            table=table,
            row=row,
            cells=[quantity_ref],
            inputs=[unit.ref],
            observed_value=fmt(quantity),
            expected_value="1",
            evidence=evidence,
            suggested_action=(
                f"Check whether the {quantity_label} belongs to another unit, or whether the item "
                "should be priced as one lump sum."
            ),
        )


# ---------------------------------------------------------------------------- helpers
def is_fractional(value: Decimal) -> bool:
    """True when a finite decimal has a non-zero fractional part (exact, no rounding)."""
    return not value.is_zero() and significant_digits(value)[1] < 0


def _enabled_check_fields(config: UnitCompatibilityConfig) -> set[str]:
    """Fields (besides the unit) that the enabled checks read."""
    needs: set[str] = set()
    if config.description_rules or config.check_same_description_dimension:
        needs.add(config.description_field)
    if config.check_integer_quantities or config.check_lump_sum_quantity:
        needs.add(config.quantity_field)
    return needs


def _row_unit(
    context: ValidationContext,
    config: UnitCompatibilityConfig,
    table: Table,
    row: Row,
    result: DetectorResult,
) -> _RowUnit | None:
    """The row's resolved unit, or ``None`` (counted) when it is empty, unreadable or
    unknown; such rows are left to required_values and unit_vocabulary."""
    cell = context.cell(table, row, config.unit_field)
    condition = cell_condition(cell)
    if condition not in _READABLE_UNIT:
        result.count(skip_key(condition) or Coverage.ROWS_SKIPPED_NOT_APPLICABLE)
        return None
    lookup = context.unit(table, row, config.unit_field)
    if lookup is None:
        result.count(ROWS_SKIPPED_UNKNOWN_UNIT)
        return None
    # The unit as the document writes it: a resolved unit cell's normalized value is the
    # canonical unit id, so the (collapsed) raw text is shown instead.
    written = " ".join((cell.raw_value or "").split()) if cell is not None else ""
    text = written or context.text(table, row, config.unit_field) or lookup.unit.unit_id
    return _RowUnit(lookup=lookup, ref=context.cell_ref(table, row, config.unit_field), text=text)


def _note_unknown_dimensions(
    context: ValidationContext, config: UnitCompatibilityConfig, result: DetectorResult
) -> None:
    """A rule that allows a dimension no unit has is a profile inconsistency worth seeing."""
    known = {unit.dimension for unit in context.units.units()}
    for rule in config.description_rules:
        unknown = [d for d in rule.allowed_dimensions if d not in known]
        if unknown:
            result.notes.append(
                f"Description rule '{rule.rule_id}' allows dimension(s) {', '.join(unknown)} "
                "that no unit of the profile has."
            )


def _dimension_name(dimension: str) -> str:
    return dimension.replace("_", " ")


def _dimension_list(dimensions: tuple[str, ...]) -> str:
    names = [_dimension_name(d) for d in dimensions]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


def _rows_of(members: list[_Member], dimension: str) -> list[tuple[Table, Row]]:
    return [(m.table, m.row) for m in members if m.lookup.unit.dimension == dimension]


def _unit_texts(members: list[_Member], dimension: str) -> str:
    texts = list(
        dict.fromkeys(
            clip(m.unit_text, 20) for m in members if m.lookup.unit.dimension == dimension
        )
    )
    return ", ".join(texts[:3]) + (" ..." if len(texts) > 3 else "")


def _unit_evidence(unit: _RowUnit, unit_label: str) -> EvidenceItem:
    definition = unit.lookup.unit
    return EvidenceItem(
        kind=EvidenceKind.VALUE,
        label=unit_label,
        detail=f"'{clip(unit.text, 30)}' = {definition.label} ({definition.unit_id}), "
        f"dimension {_dimension_name(definition.dimension)}"
        + (f", multiplier {fmt(unit.lookup.multiplier)}" if unit.lookup.multiplier else "")
        + ".",
        cells=[unit.ref],
        data={
            "unit_id": definition.unit_id,
            "dimension": definition.dimension,
            "multiplier": fmt(unit.lookup.multiplier),
        },
    )


def _multiplier_evidence(
    quantity: Decimal, quantity_ref: CellRef, unit: _RowUnit, effective: Decimal
) -> EvidenceItem:
    multiplier = unit.lookup.multiplier or _ONE
    return EvidenceItem(
        kind=EvidenceKind.CALCULATION,
        label="Quantity in single units",
        detail=f"{fmt(quantity)} × {fmt(multiplier)} = {fmt(effective)} {unit.lookup.unit.label}.",
        cells=[quantity_ref, unit.ref],
        calculation=Calculation(
            operation="product",
            operands=[
                CalculationOperand(label="quantity", value=quantity, cell=quantity_ref),
                CalculationOperand(label="unit multiplier", value=multiplier, cell=unit.ref),
            ],
            terms=2,
            exact_result=effective,
        ),
    )
