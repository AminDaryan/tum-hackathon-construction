"""Subtotal reconciliation through the shared total scopes.

For each SUBTOTAL row with a usable stated amount, :meth:`ValidationContext.rows_in_scope`
gives the candidate bases (the section the row closes; otherwise the items whose code starts
with its code and the block since the previous boundary, or that block's summary lines) and
:func:`scopes.judge` compares the amount with every admissible reading: undecided items in or
out, adjustments with either sign, hidden rows all in or all out, exact or rounded. The
outcome is reported by :class:`_totals_support.TotalReporter` (see its table): a confirmed
violation only when no admissible reading matches; ``needs_external_context`` when undecided
items could not all be combined; ``extraction_uncertainty`` when several structural readings
disagree, or (info) when a delimited-text table's difference is within the display-rounding
drift; no finding, but a count and a note, without a complete scope.

Carry-forward rows are never totals of a scope (they are not SUBTOTAL rows). Summary-block
lines are reconciled here, by the subtotal that closes the block.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, IssueCategory, Severity
from app.models.values import DataType, ExactDecimal
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import RoundingSpec, TolerancePolicy
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._support import FieldId, row_guard
from app.validation.deterministic._totals_support import TotalReporter, display_drift

_SUBTOTALS = frozenset({RowKind.SUBTOTAL})
# The first part of every rule id this check reports (subtotal_mismatch, ...).
SUBTOTAL_PREFIX = "subtotal"


class SubtotalConfig(DetectorConfig):
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


class SubtotalDetector(Detector[SubtotalConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.subtotal",
        name="Subtotal reconciliation",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Checks each subtotal against the sum of the amounts it covers, under every "
            "admissible reading of the section structure and of undecided items."
        ),
        supported_data_types=(DataType.NUMBER,),
        applicability="Tables with subtotal rows and a mapped amount field.",
        evidence_classes=(
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
            EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            EvidenceClass.EXTRACTION_UNCERTAINTY,
        ),
        issue_categories=(IssueCategory.SUBTOTAL,),
        limitations=(
            "Members are summed by their stated amounts; a wrong line is reported once, by "
            "the line total check.",
            "A subtotal whose scope cannot be established, or whose members cannot all be "
            "read, is not checked (it is counted and noted).",
        ),
        cost="low",
    )
    config_model = SubtotalConfig

    def applicability(self, context: ValidationContext, config: SubtotalConfig) -> Applicability:
        tables = [
            table.name
            for table in context.tables()
            if table.column_for_field(config.total_field) is not None
            and any(True for _ in context.rows(table, _SUBTOTALS))
        ]
        if not tables:
            return Applicability.no("No table has subtotal rows and a mapped amount field.")
        return Applicability.yes(f"Subtotal rows found in: {', '.join(tables)}.")

    def validate(self, context: ValidationContext, config: SubtotalConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            if table.column_for_field(config.total_field) is None:
                continue
            reporter = TotalReporter(
                spec=self.spec,
                context=context,
                table=table,
                total_field=config.total_field,
                category=IssueCategory.SUBTOTAL,
                severity=config.severity,
                severity_undecided=config.severity_undecided,
                severity_ambiguous_structure=config.severity_ambiguous_structure,
                severity_display_rounding=config.severity_display_rounding,
                rule_prefix=SUBTOTAL_PREFIX,
                noun="Subtotal",
                max_cells=config.max_reference_cells,
            )
            drift = display_drift(table, config.display_rounding_drift_per_term)
            for row in context.rows(table, _SUBTOTALS):
                with row_guard(result, table, row):
                    reporter.check(
                        row,
                        rounding=config.rounding,
                        tolerance=config.tolerance,
                        drift_per_term=drift,
                        result=result,
                    )
        return result
