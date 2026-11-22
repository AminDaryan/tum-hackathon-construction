"""Grand total, tax line and gross total reconciliation through the shared total scopes.

* GRAND_TOTAL rows are judged like subtotals, against the bases of
  :meth:`ValidationContext.rows_in_scope` (the counted items of the span, its summary lines,
  or the previous grand total plus the adjustments and tax lines after it), and reported by
  :class:`_totals_support.TotalReporter`.
* TAX rows (``check_tax_lines``): the rate is read from the row's text with
  ``tax_rate_pattern`` (label fields first, then the row's other cells, never the amount).
  The expected tax is rate × net / 100 for each admissible net (:func:`scopes.net_bases`: the
  nearest preceding grand total, and that total plus the adjustments between them, each as
  written or reversed), rounded with ``tax_rounding`` (the exact value is accepted too). A tax
  line without a rate or without a net is not checked; neither are the tax lines of a net
  that has several whose rates differ or are not all stated (which part of the net each one
  taxes is unknown). Each case is counted and noted.
* GROSS_TOTAL rows (``check_gross_totals``): net + adjustments (either sign) + the tax lines
  between them (:func:`scopes.gross_total_bases`), judged and reported like a subtotal. A gross
  total without a net, or with no tax line after its net, is not checked.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from pydantic import Field, field_validator

from app.core import patterns
from app.models.dataset import Column, Row, RowKind, Table
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
from app.models.values import DataType, ExactDecimal
from app.validation.contracts import scopes
from app.validation.contracts.conditions import Coverage
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import (
    Reconciliation,
    RoundingSpec,
    TolerancePolicy,
    format_decimal,
    multiply,
    reconcile,
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
from app.validation.deterministic._reference_support import clip, describe_rows
from app.validation.deterministic._support import FieldId, row_guard, row_label
from app.validation.deterministic._totals_support import (
    TotalReporter,
    display_drift,
    incomplete_reason,
)

RULE_TAX = "tax_mismatch"
# The first part of the rule ids of the net and the gross total (grand_total_mismatch, ...).
GRAND_TOTAL_PREFIX = "grand_total"
GROSS_TOTAL_PREFIX = "gross_total"
TAX_ROWS_CHECKED = "tax_rows_checked"
TAX_ROWS_CONSISTENT = "tax_rows_consistent"
TAX_ROWS_INCONSISTENT = "tax_rows_inconsistent"
TAX_ROWS_WITHOUT_RATE = "tax_rows_without_rate"
TAX_ROWS_SKIPPED_NO_NET = "tax_rows_skipped_no_net"
TAX_ROWS_SKIPPED_MIXED_RATES = "tax_rows_skipped_mixed_rates"
TAX_ROWS_SKIPPED_INCOMPLETE = "tax_rows_skipped_incomplete"
TAX_ROWS_SKIPPED_MISSING_AMOUNT = "tax_rows_skipped_missing_amount"
TAX_ROWS_SKIPPED_UNDECIDED = "tax_rows_skipped_undecided"

DEFAULT_TAX_RATE_PATTERN = r"(\d{1,3}(?:[.,]\d{1,4})?)\s*%"
_PERCENT = Decimal("0.01")


class GrandTotalConfig(DetectorConfig):
    total_field: FieldId = plannable("line_total", description="Field holding the amounts.")
    severity: Severity = plannable(Severity.HIGH, description="Severity of a confirmed mismatch.")
    max_reference_cells: int = plannable(
        50, ge=1, le=1000, description="The most summed cells a finding lists."
    )
    rounding: RoundingSpec = Field(
        default_factory=RoundingSpec, description="How a sum is rounded before comparison."
    )
    tolerance: TolerancePolicy = Field(
        default_factory=TolerancePolicy, description="Allowed difference."
    )
    display_rounding_drift_per_term: ExactDecimal = Field(
        default=Decimal("0.005"),
        ge=0,
        le=1,
        description="Per printed value, for delimited-text tables only.",
    )
    check_tax_lines: bool = Field(default=True, description="Check tax lines: rate × net.")
    tax_rate_pattern: str = Field(
        default=DEFAULT_TAX_RATE_PATTERN,
        min_length=1,
        max_length=200,
        description="Finds the rate in a tax line's text; its one capture group is the percent.",
    )
    tax_rounding: RoundingSpec = Field(
        default_factory=RoundingSpec, description="How rate × net is rounded."
    )
    check_gross_totals: bool = Field(
        default=True, description="Check gross totals: net + adjustments + tax lines."
    )
    severity_undecided: Severity = Field(
        default=Severity.MEDIUM, description="Severity of totals that depend on undecided items."
    )
    severity_ambiguous_structure: Severity = Field(
        default=Severity.MEDIUM,
        description="Severity of totals matching none of several possible scopes.",
    )
    severity_display_rounding: Severity = Field(
        default=Severity.INFO, description="Severity of differences explained by printed rounding."
    )

    @field_validator("tax_rate_pattern")
    @classmethod
    def _one_capture_group(cls, value: str) -> str:
        if patterns.compile_pattern(value).groups != 1:  # raises ValueError when invalid
            raise ValueError("tax_rate_pattern must have exactly one capture group (the rate)")
        return value


class GrandTotalDetector(Detector[GrandTotalConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.grand_total",
        name="Grand total, tax and gross reconciliation",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Checks each grand total against the sum of what it covers, each tax line against "
            "its rate times the net, and each gross total against net plus tax, under every "
            "admissible reading."
        ),
        supported_data_types=(DataType.NUMBER,),
        applicability="Tables with grand total, tax or gross total rows and a mapped amount field.",
        evidence_classes=(
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
            EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            EvidenceClass.EXTRACTION_UNCERTAINTY,
        ),
        issue_categories=(IssueCategory.GRAND_TOTAL,),
        limitations=(
            "Members are summed by their stated amounts; a wrong line or subtotal is reported "
            "once, by its own check.",
            "A tax rate is read only from the tax line's text; a tax line without a stated "
            "rate, or one of several tax lines of one net with different rates, is not checked.",
            "A total whose scope cannot be established, or whose members cannot all be read, "
            "is not checked (it is counted and noted).",
        ),
        cost="low",
    )
    config_model = GrandTotalConfig

    def applicability(self, context: ValidationContext, config: GrandTotalConfig) -> Applicability:
        kinds = _checked_kinds(config)
        tables = [
            table.name
            for table in context.tables()
            if table.column_for_field(config.total_field) is not None
            and any(True for _ in context.rows(table, kinds))
        ]
        if not tables:
            return Applicability.no(
                "No table has grand total, tax or gross total rows and a mapped amount field."
            )
        return Applicability.yes(
            f"Grand total, tax or gross total rows found in: {', '.join(tables)}."
        )

    def validate(self, context: ValidationContext, config: GrandTotalConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            if table.column_for_field(config.total_field) is None:
                continue
            grand = self._reporter(context, config, table, GRAND_TOTAL_PREFIX, "Grand total")
            gross = self._reporter(
                context, config, table, GROSS_TOTAL_PREFIX, "Gross total", "the sum of net and tax"
            )
            drift = display_drift(table, config.display_rounding_drift_per_term)
            taxes: list[Row] = []
            for row in context.rows(table, _checked_kinds(config)):
                if row.kind is RowKind.TAX:
                    taxes.append(row)
                    continue
                with row_guard(result, table, row):
                    if row.kind is RowKind.GROSS_TOTAL and not self._has_net_and_tax(
                        context, table, row, result
                    ):
                        continue
                    reporter = grand if row.kind is RowKind.GRAND_TOTAL else gross
                    reporter.check(
                        row,
                        rounding=config.rounding,
                        tolerance=config.tolerance,
                        drift_per_term=drift,
                        result=result,
                    )
            if taxes:
                _TaxCheck(self.spec, context, config, table, result).run(taxes)
        return result

    def _reporter(
        self,
        context: ValidationContext,
        config: GrandTotalConfig,
        table: Table,
        prefix: str,
        noun: str,
        parts: str = "the sum of its items",
    ) -> TotalReporter:
        return TotalReporter(
            spec=self.spec,
            context=context,
            table=table,
            total_field=config.total_field,
            category=IssueCategory.GRAND_TOTAL,
            severity=config.severity,
            severity_undecided=config.severity_undecided,
            severity_ambiguous_structure=config.severity_ambiguous_structure,
            severity_display_rounding=config.severity_display_rounding,
            rule_prefix=prefix,
            noun=noun,
            max_cells=config.max_reference_cells,
            parts=parts,
        )

    @staticmethod
    def _has_net_and_tax(
        context: ValidationContext, table: Table, row: Row, result: DetectorResult
    ) -> bool:
        layout = scopes.net_layout(context, table, row)
        if layout is not None and layout.taxes:
            return True
        result.count(Coverage.TOTALS_SKIPPED_NO_SCOPE)
        where = row_label(table, row)
        if layout is None:
            result.notes.append(
                f"{where}: gross total not checked, because no net total (grand total) "
                "directly precedes it."
            )
        else:
            result.notes.append(
                f"{where}: gross total not checked, because no tax line stands between it and "
                f"the net total in row {layout.net.source_row_number}."
            )
        return False


def _checked_kinds(config: GrandTotalConfig) -> frozenset[RowKind]:
    kinds = {RowKind.GRAND_TOTAL}
    if config.check_tax_lines:
        kinds.add(RowKind.TAX)
    if config.check_gross_totals:
        kinds.add(RowKind.GROSS_TOTAL)
    return frozenset(kinds)


class _TaxCheck:
    """Tax lines of one table: rate × net, per the module docstring."""

    def __init__(
        self,
        spec: DetectorSpec,
        context: ValidationContext,
        config: GrandTotalConfig,
        table: Table,
        result: DetectorResult,
    ) -> None:
        self.spec, self.context, self.config = spec, context, config
        self.table, self.result = table, result

    def run(self, rows: list[Row]) -> None:
        lines: list[tuple[Row, Decimal | None, scopes.NetLayout | None]] = []
        for row in rows:
            with row_guard(self.result, self.table, row):
                layout = scopes.net_layout(self.context, self.table, row)
                lines.append((row, self._rate(row), layout))
        rates_by_net: dict[str, set[Decimal | None]] = defaultdict(set)
        lines_by_net: dict[str, int] = defaultdict(int)
        for _, rate, layout in lines:
            if layout is not None:
                rates_by_net[layout.net.row_id].add(rate)
                lines_by_net[layout.net.row_id] += 1
        for row, rate, layout in lines:
            with row_guard(self.result, self.table, row):
                where = row_label(self.table, row)
                reported = self.context.number(self.table, row, self.config.total_field)
                if reported is None:
                    self.result.count(TAX_ROWS_SKIPPED_MISSING_AMOUNT)
                elif rate is None:
                    self.result.count(TAX_ROWS_WITHOUT_RATE)
                    self.result.notes.append(
                        f"{where}: tax line not checked, because its text states no rate."
                    )
                elif layout is None:
                    self.result.count(TAX_ROWS_SKIPPED_NO_NET)
                    self.result.notes.append(
                        f"{where}: tax line not checked, because no net total (grand total) "
                        "directly precedes it."
                    )
                elif (
                    lines_by_net[layout.net.row_id] > 1 and len(rates_by_net[layout.net.row_id]) > 1
                ):
                    self.result.count(TAX_ROWS_SKIPPED_MIXED_RATES)
                    self.result.notes.append(
                        f"{where}: tax line not checked, because the net total in row "
                        f"{layout.net.source_row_number} has several tax lines whose rates differ "
                        "or are not all stated, so which part of the net each one taxes is "
                        "unknown."
                    )
                else:
                    self._check(row, reported, rate, layout)

    def _rate(self, row: Row) -> Decimal | None:
        """The first rate ``tax_rate_pattern`` finds in the row's text, in percent."""
        for column in self._text_columns():
            text = self.context.text_at(row, column.column_id)
            found = patterns.search(self.config.tax_rate_pattern, text) if text else None
            if found is None or found.group(1) is None:
                continue
            try:
                rate = Decimal(found.group(1).replace(",", "."))
            except InvalidOperation:
                return None
            return rate if rate.is_finite() and 0 <= rate <= 100 else None
        return None

    def _text_columns(self) -> list[Column]:
        """Label fields first (the profile's order), then the other columns; never the amount."""
        total = self.table.column_for_field(self.config.total_field)
        skip = {total.column_id} if total is not None else set()
        ordered: list[Column] = []
        labels = self.context.profile.row_classification.label_fields
        candidates = [self.table.column_for_field(field_id) for field_id in labels]
        for column in [*candidates, *self.table.columns]:
            if column is not None and column.column_id not in skip:
                skip.add(column.column_id)
                ordered.append(column)
        return ordered

    def _check(self, row: Row, reported: Decimal, rate: Decimal, layout: scopes.NetLayout) -> None:
        where = row_label(self.table, row)
        bases = scopes.net_bases(self.context, self.table, layout, row, self.config.total_field)
        complete = [basis for basis in bases if basis.complete]
        if not complete:
            self.result.count(TAX_ROWS_SKIPPED_INCOMPLETE)
            self.result.notes.append(
                f"{where}: tax line not checked, because {incomplete_reason(self.table, bases)}."
            )
            return
        fraction = multiply(rate, _PERCENT)
        best: tuple[scopes.Basis, scopes.Reading, Reconciliation] | None = None
        tested, truncated = 0, False
        for basis in complete:
            found = scopes.readings(basis)
            truncated = truncated or found.truncated
            for reading in found.readings:
                tested += 1
                outcome = reconcile(
                    reported,
                    multiply(reading.total, fraction),
                    rounding=self.config.tax_rounding,
                    tolerance=self.config.tolerance,
                )
                if outcome.matched:
                    self.result.count(TAX_ROWS_CHECKED)
                    self.result.count(TAX_ROWS_CONSISTENT)
                    if reading.choices or len(basis.terms) > 1:
                        self.result.notes.append(
                            f"{where}: the tax line matches {format_decimal(rate)} % of "
                            f"{basis.description}, {reading.describe()}."
                        )
                    return
                if best is None or abs(outcome.difference) < abs(best[2].difference):
                    best = (basis, reading, outcome)
        if truncated:
            self.result.count(TAX_ROWS_SKIPPED_UNDECIDED)
            self.result.notes.append(
                f"{where}: tax line not checked, because too many adjustments stand between it "
                "and its net total to test every reading."
            )
            return
        assert best is not None  # a complete basis has at least one reading
        self.result.count(TAX_ROWS_CHECKED)
        self.result.count(TAX_ROWS_INCONSISTENT)
        self.context.checkpoint()
        self.result.add(self._issue(row, reported, rate, *best, tested))

    def _issue(
        self,
        row: Row,
        reported: Decimal,
        rate: Decimal,
        basis: scopes.Basis,
        reading: scopes.Reading,
        outcome: Reconciliation,
        tested: int,
    ) -> ValidationIssue:
        field = self.config.total_field
        stated, expected = format_decimal(reported), format_decimal(outcome.expected)
        rate_text, net_text = f"{format_decimal(rate)} %", format_decimal(reading.total)
        difference, allowed = format_decimal(outcome.difference), format_decimal(outcome.allowed)
        refs = [
            self.context.cell_ref(self.table, term.row, field)
            for term in basis.terms[: self.config.max_reference_cells]
        ]
        rounding = self.config.tax_rounding
        rounded = rounding.decimal_places is not None
        net_cell = refs[0] if len(basis.terms) == 1 and refs else None
        calculation = Calculation(
            operation="percentage",
            operands=[
                CalculationOperand(label="net", value=reading.total, cell=net_cell),
                CalculationOperand(label="rate (%)", value=rate),
            ],
            terms=2,
            exact_result=outcome.exact,
            rounding=rounding.describe() if rounded else None,
            rounded_result=outcome.expected if rounded else None,
            reported=reported,
            difference=outcome.difference,
            allowed_difference=outcome.allowed,
        )
        net_description = f"{basis.description} ({reading.describe()})"
        explanation = (
            f"{row_label(self.table, row)}: {rate_text} of {net_description}, {net_text}, is "
            f"{format_decimal(outcome.exact)} ({expected} rounded), but the stated tax is "
            f"{stated} (difference {difference}, allowed ±{allowed}). No admissible net "
            f"matches ({tested} tested)."
        )
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.CALCULATION,
                label="Tax",
                detail=clip(
                    f"{rate_text} × {net_text} = {format_decimal(outcome.exact)} → {expected}; "
                    f"stated {stated}; difference {difference}; allowed ±{allowed}",
                    1000,
                ),
                calculation=calculation,
            ),
            EvidenceItem(
                kind=EvidenceKind.REFERENCE,
                label="Net",
                detail=clip(
                    f"{net_description}: "
                    + describe_rows([(self.table, term.row) for term in basis.terms], limit=20),
                    1000,
                ),
                cells=refs,
                data={
                    "rate_percent": format_decimal(rate),
                    "basis": basis.kind.value,
                    "readings_tested": tested,
                },
            ),
        ]
        impact = None
        if len(basis.currencies) == 1:
            impact = FinancialImpact(
                amount=outcome.difference,
                currency=next(iter(basis.currencies)),
                basis="stated tax minus rate × net",
                kind="discrepancy",
                reported=reported,
                recomputed=outcome.expected,
            )
        return self.context.issues.create(
            self.spec,
            rule_id=RULE_TAX,
            category=IssueCategory.GRAND_TOTAL,
            severity=self.config.severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(
                f"Tax {stated} does not match {rate_text} of the net total {net_text} ({expected})",
                200,
            ),
            explanation=clip(explanation, 2000),
            table=self.table,
            row=row,
            cells=[self.context.cell_ref(self.table, row, field)],
            inputs=refs,
            observed_value=stated,
            expected_value=expected,
            evidence=evidence,
            suggested_action=(
                "Check the tax rate, the net amount it applies to and the tax amount in the "
                "source document."
            ),
            financial_impact=impact,
            subject=field,
        )
