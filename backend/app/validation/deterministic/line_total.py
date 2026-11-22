"""Line total = quantity × unit price (× the unit's quantity factor).

For each item row with a usable quantity, unit price and line total (exact or inferred):
``exact = quantity × factor × unit price``. ``factor`` is the unit's ``quantity_factor`` (the
BoQ profile sets 0.01 for ``%``: "5 % of 100,000.00" is 5,000.00) unless the quantity or the
price is itself written as a percentage (already divided by 100: factor 1). The stated line
total passes when it is within tolerance of the exact or the rounded recomputation
(:func:`decimal_math.reconcile`); otherwise it is a ``confirmed_rule_violation`` with the
calculation written out and, with an explicit currency, a ``discrepancy`` financial impact.

Item discount (``discount_field``, mapped only where a file declares it, such as a GAEB bill):
``exact = round(quantity × factor × unit price) × (1 − discount)``, the GAEB rule. The
evidence writes that chain out, so its product equals the stated result. A discount cell that
holds no usable number skips the row (``rows_skipped_unusable_inputs``).

Abstentions, each counted in coverage: an input is empty (``rows_skipped_missing_inputs``; an
item with only a unit price, "nur EP", is normal), a value marker such as a lump-sum token in
the quantity (``rows_skipped_marker``), an unusable input (``rows_skipped_unusable_inputs``),
a unit written with a multiplier other than 1 such as "100 St"
(``rows_skipped_unit_multiplier``), a unit dimension in ``skip_unit_dimensions``
(``rows_skipped_unit_dimension``), explicit currencies on price and total that disagree
(``rows_skipped_currency_conflict``; currency_consistency reports those).

``infer_precision_from_column``: when every usable line total of a table is written with at
most ``k`` decimal places, ``k`` below the rounding's places (whole-euro estimates), the
recomputation is rounded to ``k`` places for that table, and the evidence says so.

``detect_scaling_errors``: when the stated total is about 10^k times the recomputation, a note
says so as context, never as proof; never when the factor is not 1 or the unit is a ratio. The
title then names the factor ("Line total 4800.00 is 10 times Quantity × Unit price = 480.00: a
decimal slip?"), and the note's ``data`` carries ``power_of_ten`` (k, negative when the stated
total is too small). The finding stays the same confirmed mismatch, with the same fingerprint.

``prevailing_value``: ``none`` (the default) says only that the three values disagree.
``unit_price`` applies a rule such as VOB/A § 16c (2) Nr. 1 (the BoQ profile cites it in
``prevailing_rule``): the unit price prevails, so the finding states the corrected line total
(the recomputation, rounded; with an item discount, the discounted amount as computed above), the
impact's basis reads "stated line total minus corrected line total (the unit price prevails)",
and the suggested action asks the reviewer to confirm the unit price. A lump-sum position
(``lump_sums``: a unit dimension, or a type such as "Pauschalposition" in ``text_field``) keeps
its stated amount instead, and the finding says so. A file whose extraction warnings include
one of ``lump_sums.undetermined_warnings`` (a GAEB X84 or D84 bid, which carries no item flags
and often no units) cannot say which positions are lump sums: there the finding adds
``lump_sums.undetermined_note`` (the exception can only be checked with the tender). The rule
evidence's ``data`` carries ``prevails`` (``unit_price``, ``stated_amount`` or
``unit_price_unless_lump_sum``) and ``corrected_line_total`` for a later corrected bill total.
Amounts, observed and expected values, severities and fingerprints are the same as without it.

Finding category (B2): error, for every finding of this detector (``line_total_mismatch``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core import patterns
from app.models.dataset import Row, Table
from app.models.issue import (
    Calculation,
    CalculationOperand,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    FinancialImpact,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType, NumberValue
from app.profiles.units import UnitLookup
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import (
    Reconciliation,
    RoundingSpec,
    TolerancePolicy,
    format_amount,
    format_decimal,
    multiply,
    power_of_ten_factor,
    reconcile,
    subtract,
)
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._reference_support import checked_pattern, clip
from app.validation.deterministic._support import (
    FieldId,
    field_label,
    row_guard,
    row_label,
    written_places,
)

RULE_LINE_TOTAL = "line_total_mismatch"
_ONE = Decimal(1)
_PERCENT = Decimal("0.01")
DISCOUNT_RULE = (
    "GAEB DA XML 3.3 (Fachdokumentation 2023-01, 4.6.17): the item total is rounded, the item "
    "discount is taken from that rounded total, and the result is rounded again."
)
# What prevails in a mismatch (the rule evidence's data["prevails"]).
PREVAILS_UNIT_PRICE = "unit_price"
PREVAILS_STATED_AMOUNT = "stated_amount"
PREVAILS_UNLESS_LUMP_SUM = "unit_price_unless_lump_sum"
_UNIT_PRICE_RULE = "The unit price prevails: the line total is corrected to quantity × unit price."
_LUMP_SUM_RULE = "A lump sum stands as stated, whatever quantity × unit price gives."


class LumpSumRule(BaseModel):
    """Lump-sum positions, whose stated amount prevails over quantity × unit price (used with
    ``prevailing_value: unit_price``). A position is a lump sum when its unit's dimension is in
    ``unit_dimensions`` or its ``text_field`` matches ``text_pattern``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_dimensions: list[str] = Field(
        default_factory=list, description="Unit dimensions of a lump-sum position."
    )
    text_field: FieldId | None = Field(
        default=None, description="Field whose text can name a lump-sum position."
    )
    text_pattern: str | None = Field(
        default=None, description="Pattern of a lump-sum position's text in text_field."
    )
    rule: str = Field(default="", description="The rule the finding cites for a lump sum.")
    undetermined_warnings: list[str] = Field(
        default_factory=list,
        description="Extraction warning codes of a file that does not say which positions are "
        "lump sums.",
    )
    undetermined_note: str = Field(
        default="", description="What a finding in such a file says about lump sums."
    )

    @field_validator("text_pattern")
    @classmethod
    def _valid_pattern(cls, value: str | None) -> str | None:
        return None if value is None else checked_pattern(value, groups=None)

    @model_validator(mode="after")
    def _complete(self) -> LumpSumRule:
        if (self.text_field is None) != (self.text_pattern is None):
            raise ValueError("text_field and text_pattern go together")
        if self.undetermined_warnings and not self.undetermined_note.strip():
            raise ValueError("undetermined_warnings need an undetermined_note")
        return self


@dataclass(frozen=True, slots=True)
class _Prevailing:
    """What prevails for one row: ``kind`` is one of the ``PREVAILS_*`` values; ``reason`` says
    why a position is a lump sum; ``by`` names what showed it (``unit`` or the text field)."""

    kind: str
    reason: str | None = None
    by: str | None = None


class LineTotalConfig(DetectorConfig):
    quantity_field: FieldId = plannable("quantity", description="Field holding the quantity.")
    price_field: FieldId = plannable("unit_price", description="Field holding the unit price.")
    total_field: FieldId = plannable("line_total", description="Field holding the line total.")
    unit_field: FieldId = plannable("unit", description="Field holding the unit.")
    discount_field: FieldId = plannable(
        "discount_percent",
        description="Field holding an item discount in percent; used only where it is mapped.",
    )
    severity: Severity = plannable(Severity.HIGH, description="Severity of a mismatch.")
    rounding: RoundingSpec = Field(
        default_factory=RoundingSpec, description="How the recomputation is rounded."
    )
    tolerance: TolerancePolicy = Field(
        default_factory=TolerancePolicy, description="Allowed difference."
    )
    infer_precision_from_column: bool = Field(
        default=True,
        description="Round to the decimal places the table's line totals are written with.",
    )
    skip_unit_dimensions: list[str] = Field(
        default_factory=list, description="Unit dimensions whose rows are not checked."
    )
    detect_scaling_errors: bool = Field(
        default=True, description="Note when a total is about a power of ten off."
    )
    prevailing_value: Literal["none", "unit_price"] = Field(
        default="none",
        description=(
            "What prevails in a mismatch: none (the finding does not say which value is wrong) "
            "or unit_price (the line total is corrected to quantity × unit price)."
        ),
    )
    prevailing_rule: str | None = Field(
        default=None, description="The rule the finding cites when the unit price prevails."
    )
    lump_sums: LumpSumRule = Field(
        default_factory=LumpSumRule,
        description="Lump-sum positions, whose stated amount prevails instead.",
    )


class LineTotalDetector(Detector[LineTotalConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.line_total",
        name="Line total = quantity × unit price",
        version="1.2.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Recomputes each item's line total from its quantity and unit price (with the "
            "unit's factor, e.g. 0.01 for percent) and compares it with the stated total. An "
            "item discount that the file declares (GAEB) is taken off by the GAEB rounding rule. "
            "Where the profile says the unit price prevails (VOB/A § 16c), a mismatch states the "
            "corrected line total; a lump sum keeps its stated amount."
        ),
        supported_data_types=(DataType.NUMBER,),
        applicability="Tables that map the quantity, unit price and line total fields.",
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.ARITHMETIC,),
        limitations=(
            "A mismatch shows that quantity, unit price and total disagree, not which one is "
            "wrong.",
            "Rows with a unit multiplier such as '100 St' are not checked.",
        ),
        cost="low",
    )
    config_model = LineTotalConfig

    def applicability(self, context: ValidationContext, config: LineTotalConfig) -> Applicability:
        fields = (config.quantity_field, config.price_field, config.total_field)
        mapped = [table.name for table in context.tables() if context.has_fields(table, *fields)]
        if not mapped:
            return Applicability.no("Quantity, unit price and line total are not all mapped.")
        return Applicability.yes(
            f"Quantity, unit price and line total are mapped in: {', '.join(mapped)}."
        )

    def validate(self, context: ValidationContext, config: LineTotalConfig) -> DetectorResult:
        result = DetectorResult()
        fields = (config.quantity_field, config.price_field, config.total_field)
        for table in context.tables():
            if not context.has_fields(table, *fields):
                continue
            rounding, inferred = _table_rounding(context, table, config)
            if inferred is not None:
                result.notes.append(
                    f"Table '{table.name}': every line total is written with at most "
                    f"{inferred} decimal places, so recomputations are rounded to {inferred}."
                )
            undetermined = _lump_sums_undetermined(context, table, config)
            for row in context.rows(table):
                with row_guard(result, table, row):
                    self._check(
                        context, config, table, row, rounding, inferred, undetermined, result
                    )
        return result

    def _check(
        self,
        context: ValidationContext,
        config: LineTotalConfig,
        table: Table,
        row: Row,
        rounding: RoundingSpec,
        inferred: int | None,
        undetermined: bool,
        result: DetectorResult,
    ) -> None:
        fields = (config.quantity_field, config.price_field, config.total_field)
        values = [context.number_value(table, row, field_id) for field_id in fields]
        quantity, price, total = values
        if quantity is None or price is None or total is None:
            conditions = {cell_condition(context.cell(table, row, f)) for f in fields}
            if CellCondition.EMPTY in conditions:
                result.count(Coverage.ROWS_SKIPPED_MISSING_INPUTS)
            elif CellCondition.MARKER in conditions:
                result.count(Coverage.ROWS_SKIPPED_MARKER)
            else:
                result.count(Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS)
            return
        lookup = (
            context.unit(table, row, config.unit_field)
            if table.column_for_field(config.unit_field) is not None
            else None
        )
        if lookup is not None and lookup.multiplier not in (None, _ONE):
            result.count("rows_skipped_unit_multiplier")
            return
        if lookup is not None and lookup.unit.dimension in config.skip_unit_dimensions:
            result.count("rows_skipped_unit_dimension")
            return
        if _currency_conflict(context, table, config, price, total):
            result.count("rows_skipped_currency_conflict")
            return
        discount = _discount(context, config, table, row)
        if discount is False:
            result.count(Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS)
            return
        percent = quantity.is_percent or price.is_percent
        factor = lookup.unit.quantity_factor if lookup is not None and not percent else _ONE
        exact = multiply(quantity.value, factor, price.value)
        if discount is not None:  # rounded total, minus the discount, rounded again (GAEB)
            exact = multiply(rounding.apply(exact), subtract(_ONE, discount))
        outcome = reconcile(total.value, exact, rounding=rounding, tolerance=config.tolerance)
        result.count(Coverage.ROWS_CHECKED)
        if outcome.matched:
            result.count(Coverage.ROWS_CONSISTENT)
            return
        result.count(Coverage.ROWS_INCONSISTENT)
        context.checkpoint()
        values_used = (quantity, price, total)
        issue = self._issue(
            context,
            config,
            table,
            row,
            values_used,
            factor,
            lookup,
            rounding,
            inferred,
            outcome,
            discount,
            _prevailing(context, config, table, row, lookup, undetermined),
        )
        result.add(issue)

    def _issue(
        self,
        context: ValidationContext,
        config: LineTotalConfig,
        table: Table,
        row: Row,
        values: tuple[NumberValue, NumberValue, NumberValue],
        factor: Decimal,
        lookup: UnitLookup | None,
        rounding: RoundingSpec,
        inferred: int | None,
        outcome: Reconciliation,
        discount: Decimal | None = None,
        prevailing: _Prevailing | None = None,
    ) -> ValidationIssue:
        quantity, price, total = values
        q_ref, p_ref, t_ref = (
            context.cell_ref(table, row, field_id)
            for field_id in (config.quantity_field, config.price_field, config.total_field)
        )
        q_label = field_label(context, config.quantity_field)
        p_label = field_label(context, config.price_field)
        t_label = field_label(context, config.total_field)
        operands = [CalculationOperand(label=q_label, value=quantity.value, cell=q_ref)]
        if factor != _ONE:
            unit_id = lookup.unit.unit_id if lookup is not None else "unit"
            operands.append(CalculationOperand(label=f"unit factor ({unit_id})", value=factor))
        operands.append(CalculationOperand(label=p_label, value=price.value, cell=p_ref))
        product = " × ".join(format_decimal(operand.value) for operand in operands)
        cells = [q_ref, p_ref, t_ref]
        if discount is not None:  # the chain the GAEB rule computes: round(q × p) × (1 − d)
            base = multiply(*(operand.value for operand in operands))
            rounded, keep = rounding.apply(base), subtract(_ONE, discount)
            d_ref = context.cell_ref(table, row, config.discount_field)
            cells.append(d_ref)
            product = (
                f"{product} = {format_decimal(base)} → {format_decimal(rounded)}; "
                f"{format_decimal(rounded)} × {format_decimal(keep)}"
            )
            operands = [
                CalculationOperand(label=f"{q_label} × {p_label}, rounded", value=rounded),
                CalculationOperand(
                    label=f"1 − {field_label(context, config.discount_field)}",
                    value=keep,
                    cell=d_ref,
                ),
            ]
        expected, stated = format_decimal(outcome.expected), format_decimal(total.value)
        difference, allowed = format_decimal(outcome.difference), format_decimal(outcome.allowed)
        calculation = Calculation(
            operation="product",
            operands=operands,
            terms=len(operands),
            exact_result=outcome.exact,
            rounding=rounding.describe() if rounding.decimal_places is not None else None,
            rounded_result=outcome.expected if rounding.decimal_places is not None else None,
            reported=total.value,
            difference=outcome.difference,
            allowed_difference=outcome.allowed,
        )
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.CALCULATION,
                label="Recomputation",
                detail=(
                    f"{product} = {format_decimal(outcome.exact)} → {expected} "
                    f"({rounding.describe()}); stated {stated}; difference {difference}; "
                    f"allowed ±{allowed}"
                ),
                cells=cells,
                calculation=calculation,
            ),
            EvidenceItem(
                kind=EvidenceKind.RULE,
                label="Rule",
                detail=(
                    f"{t_label} = {q_label} × "
                    f"{'unit factor × ' if factor != _ONE else ''}{p_label}, compared exactly "
                    f"and rounded to {rounding.describe()}, within ±{allowed}."
                    + (f" With an item discount: {DISCOUNT_RULE}" if discount is not None else "")
                ),
            ),
        ]
        if inferred is not None:
            evidence.append(
                EvidenceItem(
                    kind=EvidenceKind.NOTE,
                    label="Rounding inferred from the column",
                    detail=(
                        f"Every line total of table '{table.name}' is written with at most "
                        f"{inferred} decimal places, so the recomputation is rounded to "
                        f"{inferred}."
                    ),
                    data={"decimal_places": inferred},
                )
            )
        power = _scaling_power(config, total.value, outcome.exact, factor, lookup, rounding)
        if power is not None:
            evidence.append(_scaling_note(power))
        # Sentences show amounts with two decimals (the column's rounding can leave "2000.0");
        # observed_value, expected_value and the evidence keep the exact strings, which the
        # evidence digest that carries reviews forward is computed from.
        shown_expected, shown_stated = format_amount(outcome.expected), format_amount(total.value)
        explanation = (
            f"{row_label(table, row)}: {product} = {shown_expected}, but the stated {t_label} is "
            f"{shown_stated} (difference {format_amount(outcome.difference)}, allowed ±{allowed})."
        )
        basis = "stated line total minus recomputed line total"
        action = (
            f"Check {q_label}, {p_label} and {t_label} in the source document: one of them "
            "is wrong (the recomputation does not show which)."
        )
        if prevailing is not None:
            words = _Words(
                q_label, p_label, t_label, format_amount(price.value), shown_stated, shown_expected
            )
            evidence.extend(_prevailing_evidence(config, prevailing, stated, expected))
            explanation = f"{explanation} {_prevailing_explanation(config, prevailing, words)}"
            basis, action = _prevailing_basis(prevailing), _prevailing_action(prevailing, words)
        currency = context.currency_evidence(table, row, [config.price_field, config.total_field])
        impact = (
            FinancialImpact(
                amount=outcome.difference,
                currency=currency,
                basis=basis,
                kind="discrepancy",
                reported=total.value,
                recomputed=outcome.expected,
            )
            if currency is not None
            else None
        )
        return context.issues.create(
            self.spec,
            rule_id=RULE_LINE_TOTAL,
            category=IssueCategory.ARITHMETIC,
            severity=config.severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(
                f"{t_label} {shown_stated} is {_times(power)} {q_label} × {p_label} = "
                f"{shown_expected}: a decimal slip?"
                if power is not None
                else f"{t_label} {shown_stated} does not match {q_label} × {p_label} = "
                f"{shown_expected}",
                200,
            ),
            explanation=explanation,
            table=table,
            row=row,
            cells=[t_ref],
            inputs=[q_ref, p_ref],
            observed_value=stated,
            expected_value=expected,
            evidence=evidence,
            suggested_action=action,
            financial_impact=impact,
            subject=config.total_field,
        )


def _table_rounding(
    context: ValidationContext, table: Table, config: LineTotalConfig
) -> tuple[RoundingSpec, int | None]:
    """The table's rounding, with the places inferred from its line totals when enabled."""
    places = config.rounding.decimal_places
    if not config.infer_precision_from_column or places is None:
        return config.rounding, None
    written = [
        written_places(value)
        for row in context.rows(table)
        if (value := context.number(table, row, config.total_field)) is not None
    ]
    if not written or max(written) >= places:
        return config.rounding, None
    return config.rounding.with_places(max(written)), max(written)


def _currency_conflict(
    context: ValidationContext,
    table: Table,
    config: LineTotalConfig,
    price: NumberValue,
    total: NumberValue,
) -> bool:
    found = set()
    for field_id, value in ((config.price_field, price), (config.total_field, total)):
        column = table.column_for_field(field_id)
        currency = value.currency or (column.header_currency if column is not None else None)
        if currency is not None:
            found.add(currency)
    return len(found) > 1


def _scaling_power(
    config: LineTotalConfig,
    stated: Decimal,
    exact: Decimal,
    factor: Decimal,
    lookup: UnitLookup | None,
    rounding: RoundingSpec,
) -> int | None:
    """k when the stated total is about 10^k times the recomputation (a decimal slip)."""
    if not config.detect_scaling_errors or factor != _ONE:
        return None
    if lookup is not None and lookup.unit.dimension == "ratio":
        return None
    quantum = _ONE.scaleb(-(rounding.decimal_places if rounding.decimal_places is not None else 2))
    return power_of_ten_factor(stated, exact, quantum=quantum)


def _scaling_note(k: int) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.NOTE,
        label="Possible scaling error",
        detail=(
            f"The stated total is about 10^{k} times the recomputed value, which suggests a "
            "decimal-point or scaling error (context, not proof)."
        ),
        data={"power_of_ten": k},
    )


def _times(k: int) -> str:
    """The factor 10^k in words for a title: "10 times", "1000 times", "1/100 of"."""
    return f"{10**k} times" if k > 0 else f"1/{10**-k} of"


@dataclass(frozen=True, slots=True)
class _Words:
    """Labels and values the prevailing-value sentences use."""

    quantity: str
    price: str
    total: str
    price_value: str
    stated: str
    corrected: str


def _lump_sums_undetermined(
    context: ValidationContext, table: Table, config: LineTotalConfig
) -> bool:
    """True when the file cannot say which positions are lump sums (an extraction warning in
    ``lump_sums.undetermined_warnings``, for the whole file or for this table)."""
    codes = set(config.lump_sums.undetermined_warnings)
    if config.prevailing_value == "none" or not codes:
        return False
    return any(
        warning.code in codes and warning.table_id in (None, table.table_id)
        for warning in context.dataset.extraction.warnings
    )


def _prevailing(
    context: ValidationContext,
    config: LineTotalConfig,
    table: Table,
    row: Row,
    lookup: UnitLookup | None,
    undetermined: bool,
) -> _Prevailing | None:
    """What prevails for this row; ``None`` without a prevailing-value rule."""
    if config.prevailing_value == "none":
        return None
    lump = config.lump_sums
    if lookup is not None and lookup.unit.dimension in lump.unit_dimensions:
        cell = context.cell(table, row, config.unit_field)
        written = (cell.raw_value or "").strip() if cell is not None else ""
        return _Prevailing(
            PREVAILS_STATED_AMOUNT, f"unit {clip(written or lookup.unit.label, 40)}", by="unit"
        )
    if lump.text_field is not None and lump.text_pattern is not None:
        text = context.text(table, row, lump.text_field)
        match = patterns.search(lump.text_pattern, text) if text else None
        if match is not None:
            label = field_label(context, lump.text_field)
            return _Prevailing(
                PREVAILS_STATED_AMOUNT, f"{label} {clip(match.group(0), 60)}", by=lump.text_field
            )
    return _Prevailing(PREVAILS_UNLESS_LUMP_SUM if undetermined else PREVAILS_UNIT_PRICE)


def _prevailing_evidence(
    config: LineTotalConfig, prevailing: _Prevailing, stated: str, corrected: str
) -> list[EvidenceItem]:
    if prevailing.kind == PREVAILS_STATED_AMOUNT:
        return [
            EvidenceItem(
                kind=EvidenceKind.RULE,
                label="Prevailing value",
                detail=config.lump_sums.rule or _LUMP_SUM_RULE,
                data={
                    "prevails": prevailing.kind,
                    "corrected_line_total": stated,
                    "lump_sum_by": prevailing.by,
                },
            )
        ]
    evidence = [
        EvidenceItem(
            kind=EvidenceKind.RULE,
            label="Prevailing value",
            detail=config.prevailing_rule or _UNIT_PRICE_RULE,
            data={"prevails": prevailing.kind, "corrected_line_total": corrected},
        )
    ]
    if prevailing.kind == PREVAILS_UNLESS_LUMP_SUM:
        evidence.append(
            EvidenceItem(
                kind=EvidenceKind.NOTE,
                label="Lump sums not known",
                detail=config.lump_sums.undetermined_note,
            )
        )
    return evidence


def _prevailing_explanation(config: LineTotalConfig, prevailing: _Prevailing, w: _Words) -> str:
    if prevailing.kind == PREVAILS_STATED_AMOUNT:
        return (
            f"The position is a lump sum ({prevailing.reason}), so its stated {w.total} "
            f"{w.stated} prevails, not {w.quantity} × {w.price}."
        )
    corrected = f"The {w.price} prevails, so the corrected {w.total} is {w.corrected}"
    if prevailing.kind == PREVAILS_UNLESS_LUMP_SUM:
        return (
            f"{corrected}, unless the position is a lump sum, whose stated amount stands. "
            f"{config.lump_sums.undetermined_note.strip()}"
        )
    return f"{corrected}."


def _prevailing_basis(prevailing: _Prevailing) -> str:
    if prevailing.kind == PREVAILS_STATED_AMOUNT:
        return (
            "stated line total minus recomputed line total (a lump sum: the stated amount prevails)"
        )
    if prevailing.kind == PREVAILS_UNLESS_LUMP_SUM:
        return (
            "stated line total minus corrected line total (the unit price prevails unless the "
            "position is a lump sum)"
        )
    return "stated line total minus corrected line total (the unit price prevails)"


def _prevailing_action(prevailing: _Prevailing, w: _Words) -> str:
    if prevailing.kind == PREVAILS_STATED_AMOUNT:
        return (
            f"Confirm that {w.stated} is the lump sum meant: it stands as stated, whatever "
            f"{w.quantity} × {w.price} gives."
        )
    confirm = f"Confirm the {w.price} {w.price_value}: it prevails, so the {w.total} counts as"
    if prevailing.kind == PREVAILS_UNLESS_LUMP_SUM:
        return (
            f"{confirm} {w.corrected} unless the position is a lump sum (then {w.stated} "
            f"stands). If {w.stated} was meant and the position is no lump sum, the {w.price} "
            "is the figure to correct."
        )
    return (
        f"{confirm} {w.corrected}. If {w.stated} was meant, the {w.price} is the figure to correct."
    )


def _discount(
    context: ValidationContext, config: LineTotalConfig, table: Table, row: Row
) -> Decimal | Literal[False] | None:
    """The row's item discount as a fraction (1.5 -> 0.015; a cell written as "1,5 %" is
    already divided by 100); None when there is none (unmapped, empty or zero); False when the
    discount cell holds something that is not a usable number."""
    if table.column_for_field(config.discount_field) is None:
        return None
    if cell_condition(context.cell(table, row, config.discount_field)) is CellCondition.EMPTY:
        return None
    value = context.number_value(table, row, config.discount_field)
    if value is None:
        return False
    return (value.value if value.is_percent else multiply(value.value, _PERCENT)) or None
