"""Invalid numerical values: bounds, whole numbers, decimal places and zero.

For every number field with constraints (the profile's ``FieldConstraints``, or the detector
configuration's ``constraints``, which replace the profile's for that field) and every item
row with a usable number (exact or inferred), each failed constraint is a
``confirmed_rule_violation``:

* ``minimum`` / ``maximum`` (with ``exclusive_minimum`` / ``exclusive_maximum``): medium;
* ``integer_only``: low;
* ``max_decimal_places``: low. Places are counted on the normalized value, so ``12.50`` has
  one decimal place and ``12.505`` has three;
* ``zero`` (``allow_zero: false``): low.

Empty cells, value markers and unusable cells are skipped and counted (their owners report
them). Pattern, allowed values and uniqueness belong to ``deterministic.field_constraints``.
The BoQ profile sets no lower bound: negative quantities and prices (credits, deductions)
are not errors there.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from app.models.dataset import CellRef, Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import FieldConstraints, SemanticField
from app.models.values import DataType
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import format_decimal
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._reference_support import clip
from app.validation.deterministic._support import (
    FieldId,
    field_label,
    fmt,
    row_guard,
    row_label,
)


class NumericValidityConfig(DetectorConfig):
    fields: list[FieldId] | None = plannable(
        None, description="Fields to check; None = every number field with constraints."
    )
    constraints: dict[FieldId, FieldConstraints] = Field(
        default_factory=dict,
        description="Constraints per field id, replacing the profile's for that field.",
    )
    severity_minimum: Severity = Field(
        default=Severity.MEDIUM, description="Severity of values below the minimum."
    )
    severity_maximum: Severity = Field(
        default=Severity.MEDIUM, description="Severity of values above the maximum."
    )
    severity_integer_only: Severity = Field(
        default=Severity.LOW, description="Severity of fractions in whole-number fields."
    )
    severity_max_decimal_places: Severity = Field(
        default=Severity.LOW, description="Severity of too many decimal places."
    )
    severity_zero: Severity = Field(
        default=Severity.LOW, description="Severity of zero where it is not allowed."
    )

    def severity_of(self, rule: str) -> Severity:
        return {
            "minimum": self.severity_minimum,
            "maximum": self.severity_maximum,
            "integer_only": self.severity_integer_only,
            "max_decimal_places": self.severity_max_decimal_places,
            "zero": self.severity_zero,
        }[rule]


class NumericValidityDetector(Detector[NumericValidityConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.numeric_validity",
        name="Invalid numerical values",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Checks numbers of item rows against the bounds, whole-number, decimal-place and "
            "zero rules the profile (or the configuration) sets for their field."
        ),
        supported_data_types=(DataType.NUMBER,),
        applicability="Tables that map a number field with constraints.",
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.NUMERIC_VALUE,),
        limitations=(
            "Only usable numbers are checked; empty, marker and unreadable cells are skipped "
            "and counted.",
            "Decimal places are counted on the normalized value (12.50 has one).",
        ),
        cost="low",
    )
    config_model = NumericValidityConfig

    def applicability(
        self, context: ValidationContext, config: NumericValidityConfig
    ) -> Applicability:
        fields = _fields(context, config)
        mapped = [
            t.name
            for t in context.tables()
            if any(t.column_for_field(f.field_id) for f, _ in fields)
        ]
        if not mapped:
            return Applicability.no("No mapped number field has constraints.")
        return Applicability.yes(f"Constrained number fields are mapped in: {', '.join(mapped)}.")

    def validate(self, context: ValidationContext, config: NumericValidityConfig) -> DetectorResult:
        result = DetectorResult()
        fields = _fields(context, config)
        for table in context.tables():
            for field_def, constraints in fields:
                if table.column_for_field(field_def.field_id) is None:
                    continue
                source = (
                    "the profile's settings for this detector"
                    if field_def.field_id in config.constraints
                    else "the profile's field constraints"
                )
                for row in context.rows(table):
                    with row_guard(result, table, row):
                        self._check(
                            context, config, table, row, field_def, constraints, source, result
                        )
        return result

    def _check(
        self,
        context: ValidationContext,
        config: NumericValidityConfig,
        table: Table,
        row: Row,
        field_def: SemanticField,
        constraints: FieldConstraints,
        source: str,
        result: DetectorResult,
    ) -> None:
        field_id = field_def.field_id
        value = context.number(table, row, field_id)
        if value is None:
            condition = cell_condition(context.cell(table, row, field_id))
            if condition is CellCondition.EMPTY:
                result.count(Coverage.ROWS_SKIPPED_MISSING_INPUTS)
            elif condition is CellCondition.MARKER:
                result.count(Coverage.ROWS_SKIPPED_MARKER)
            else:
                result.count(Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS)
            return
        result.count(Coverage.CELLS_CHECKED)
        failures = _failures(value, constraints)
        if not failures:
            result.count(Coverage.ROWS_CONSISTENT)
            return
        result.count(Coverage.ROWS_INCONSISTENT)
        ref = context.cell_ref(table, row, field_id)
        for failure in failures:
            context.checkpoint()
            result.add(
                self._issue(context, config, table, row, field_id, ref, value, failure, source)
            )

    def _issue(
        self,
        context: ValidationContext,
        config: NumericValidityConfig,
        table: Table,
        row: Row,
        field_id: str,
        ref: CellRef,
        value: Decimal,
        failure: tuple[str, str, str],
        source: str,
    ) -> ValidationIssue:
        name, expected, rule_text = failure
        label = field_label(context, field_id)
        shown = format_decimal(value)
        return context.issues.create(
            self.spec,
            rule_id=name,
            category=IssueCategory.NUMERIC_VALUE,
            severity=config.severity_of(name),
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{label} {shown} must {rule_text}", 200),
            explanation=(
                f"{row_label(table, row)}: {label} is {shown}, but {source} require it to "
                f"{rule_text}."
            ),
            table=table,
            row=row,
            cells=[ref],
            observed_value=shown,
            expected_value=expected,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Constraint",
                    detail=f"{label} must {rule_text} (set by {source}).",
                    data={"field": field_id, "constraint": name, "expected": expected},
                ),
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Value",
                    detail=f"{label} = {shown}",
                    cells=[ref],
                    data={"value": shown},
                ),
            ],
            suggested_action=(
                f"Check {label} in the source document; correct it, or adjust the constraint "
                "if this value is legitimate."
            ),
            subject=f"{field_id}:{name}",
        )


def _fields(
    context: ValidationContext, config: NumericValidityConfig
) -> list[tuple[SemanticField, FieldConstraints]]:
    profile = context.profile
    ids = config.fields if config.fields is not None else [f.field_id for f in profile.fields]
    found = []
    for field_id in ids:
        field_def = profile.field(field_id)
        if field_def is None or field_def.data_type is not DataType.NUMBER:
            continue
        constraints = config.constraints.get(field_id) or field_def.constraints
        if constraints is not None and _numeric_rules(constraints):
            found.append((field_def, constraints))
    return found


def _numeric_rules(constraints: FieldConstraints) -> bool:
    return (
        constraints.minimum is not None
        or constraints.maximum is not None
        or constraints.integer_only
        or constraints.max_decimal_places is not None
        or not constraints.allow_zero
    )


def _failures(value: Decimal, c: FieldConstraints) -> list[tuple[str, str, str]]:
    """``(constraint, expected, rule text)`` for every constraint the value fails."""
    found: list[tuple[str, str, str]] = []
    if c.minimum is not None:
        low = fmt(c.minimum)
        if value < c.minimum or (c.exclusive_minimum and value == c.minimum):
            sign = ">" if c.exclusive_minimum else ">="
            words = "be greater than" if c.exclusive_minimum else "be at least"
            found.append(("minimum", f"{sign} {low}", f"{words} {low}"))
    if c.maximum is not None:
        high = fmt(c.maximum)
        if value > c.maximum or (c.exclusive_maximum and value == c.maximum):
            sign = "<" if c.exclusive_maximum else "<="
            words = "be less than" if c.exclusive_maximum else "be at most"
            found.append(("maximum", f"{sign} {high}", f"{words} {high}"))
    if c.integer_only and value != value.to_integral_value():
        found.append(("integer_only", "a whole number", "be a whole number"))
    if c.max_decimal_places is not None and decimal_places(value) > c.max_decimal_places:
        places = c.max_decimal_places
        found.append(
            (
                "max_decimal_places",
                f"at most {places} decimal places",
                f"have at most {places} decimal place{'s' if places != 1 else ''}",
            )
        )
    if not c.allow_zero and value == 0:
        found.append(("zero", "not 0", "not be zero"))
    return found


def decimal_places(value: Decimal) -> int:
    """Decimal places of the normalized value (``12.50`` -> 1, ``1E+3`` -> 0)."""
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0
