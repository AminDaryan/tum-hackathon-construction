"""Reporting a total-scope verdict (private module: not discovered).

``deterministic.subtotal`` and ``deterministic.grand_total`` judge total rows with
:func:`app.validation.contracts.scopes.judge`; this module turns a verdict into coverage, notes
and findings the same way for both:

========================  ================================  ==========================
outcome                   evidence class (severity)          coverage
========================  ================================  ==========================
consistent                (none; a note names a non-plain    ``totals_consistent``
                          reading)
violation                 confirmed_rule_violation (config)  ``totals_inconsistent``
undecided                 needs_external_context (config)    ``totals_undecided``
ambiguous_structure       extraction_uncertainty (config)    ``totals_inconsistent``
display_rounding          extraction_uncertainty (config)    ``totals_inconsistent``
no_scope                  (none; a note)                     ``totals_skipped_no_scope``
incomplete                (none; a note)                     ``totals_skipped_incomplete_scope``
========================  ================================  ==========================
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.models.dataset import Row, Table
from app.models.issue import (
    Calculation,
    CalculationOperand,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    FinancialImpact,
    Severity,
    ValidationIssue,
)
from app.models.source import SourceKind
from app.validation.contracts.conditions import Coverage
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import RoundingSpec, TolerancePolicy, format_decimal
from app.validation.contracts.detector import DetectorResult, DetectorSpec
from app.validation.contracts.scopes import Basis, Outcome, Verdict, judge
from app.validation.deterministic._reference_support import clip, describe_rows
from app.validation.deterministic._support import row_label

_EVIDENCE = {
    Outcome.VIOLATION: EvidenceClass.CONFIRMED_RULE_VIOLATION,
    Outcome.UNDECIDED: EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
    Outcome.AMBIGUOUS_STRUCTURE: EvidenceClass.EXTRACTION_UNCERTAINTY,
    Outcome.DISPLAY_ROUNDING: EvidenceClass.EXTRACTION_UNCERTAINTY,
}
_RULE_SUFFIX = {
    Outcome.VIOLATION: "mismatch",
    Outcome.UNDECIDED: "undecided",
    Outcome.AMBIGUOUS_STRUCTURE: "scope_ambiguous",
    Outcome.DISPLAY_ROUNDING: "display_rounding",
}


def display_drift(table: Table, drift_per_term: Decimal) -> Decimal | None:
    """The drift allowance, only for display-rounded sources (delimited text)."""
    return drift_per_term if table.source.kind is SourceKind.DELIMITED_TEXT else None


@dataclass(frozen=True, slots=True)
class TotalReporter:
    spec: DetectorSpec
    context: ValidationContext
    table: Table
    total_field: str
    category: str  # an IssueCategory constant
    severity: Severity  # of a confirmed violation
    severity_undecided: Severity  # defaults: medium, medium, info (profile-controlled)
    severity_ambiguous_structure: Severity
    severity_display_rounding: Severity
    rule_prefix: str  # "subtotal", "grand_total", "gross_total"
    noun: str  # "Subtotal", "Grand total", "Gross total"
    max_cells: int
    parts: str = "the sum of its items"  # what the total should equal, for titles

    def check(
        self,
        row: Row,
        *,
        rounding: RoundingSpec,
        tolerance: TolerancePolicy,
        drift_per_term: Decimal | None,
        result: DetectorResult,
    ) -> None:
        """Judge the total row's stated amount against its scope and report the verdict."""
        reported = self.context.number(self.table, row, self.total_field)
        if reported is None:
            result.count(Coverage.TOTALS_SKIPPED_MISSING_AMOUNT)
            return
        verdict = judge(
            reported,
            self.context.rows_in_scope(self.table, row, self.total_field),
            rounding=rounding,
            tolerance=tolerance,
            drift_per_term=drift_per_term,
        )
        self.report(row, reported, verdict, result)

    def report(self, row: Row, reported: Decimal, verdict: Verdict, result: DetectorResult) -> None:
        where = row_label(self.table, row)
        outcome = verdict.outcome
        if outcome is Outcome.NO_SCOPE:
            result.count(Coverage.TOTALS_SKIPPED_NO_SCOPE)
            result.notes.append(f"{where}: no rows could be identified as what this total sums.")
            return
        if outcome is Outcome.INCOMPLETE:
            result.count(Coverage.TOTALS_SKIPPED_INCOMPLETE_SCOPE)
            result.notes.append(
                f"{where}: not checked, because {incomplete_reason(self.table, verdict.bases)}."
            )
            return
        result.count(Coverage.TOTALS_CHECKED)
        basis, reading = verdict.basis, verdict.reading
        assert basis is not None
        assert reading is not None
        assert verdict.reconciliation is not None
        if basis.left_out:
            result.notes.append(
                f"{where}: not counted in this total: "
                f"{describe_rows([(self.table, r) for r in basis.left_out])}."
            )
        if outcome is Outcome.CONSISTENT:
            result.count(Coverage.TOTALS_CONSISTENT)
            if reading.choices:
                result.notes.append(f"{where}: matches {basis.description}, {reading.describe()}.")
            return
        result.count(
            Coverage.TOTALS_UNDECIDED
            if outcome is Outcome.UNDECIDED
            else Coverage.TOTALS_INCONSISTENT
        )
        self.context.checkpoint()
        result.add(self._issue(row, reported, verdict))

    def _issue(self, row: Row, reported: Decimal, verdict: Verdict) -> ValidationIssue:
        basis, reading, outcome = verdict.basis, verdict.reading, verdict.outcome
        rec = verdict.reconciliation
        assert basis is not None
        assert reading is not None
        assert rec is not None
        stated, expected = format_decimal(reported), format_decimal(rec.expected)
        difference, allowed = format_decimal(rec.difference), format_decimal(rec.allowed)
        refs = [
            self.context.cell_ref(self.table, term.row, self.total_field)
            for term in basis.terms[: self.max_cells]
        ]
        sum_text = (
            f"the sum of {basis.description} ({reading.describe()}) is {format_decimal(rec.exact)}"
        )
        if outcome is Outcome.VIOLATION:
            title = f"{self.noun} {stated} does not match {self.parts} ({expected})"
            explanation = (
                f"{row_label(self.table, row)}: {sum_text}, but the stated {self.noun.lower()} "
                f"is {stated} (difference {difference}, allowed ±{allowed}). No admissible "
                f"reading matches ({verdict.readings_tested} tested)."
            )
            severity = self.severity
        elif outcome is Outcome.UNDECIDED:
            title = f"{self.noun} {stated} depends on undecided items that could not all be tested"
            explanation = (
                f"{row_label(self.table, row)}: the {self.noun.lower()} is {stated}; too many "
                f"items are undecided (in or out of the total) to test every combination, and "
                f"none of the {verdict.readings_tested} tested readings matches (closest: "
                f"{expected})."
            )
            severity = self.severity_undecided
        elif outcome is Outcome.AMBIGUOUS_STRUCTURE:
            title = f"{self.noun} {stated} matches none of the possible scopes"
            scopes_text = "; ".join(candidate.description for candidate in verdict.bases)
            explanation = (
                f"{row_label(self.table, row)}: the {self.noun.lower()} {stated} could sum "
                f"{scopes_text}, and matches none of them (closest: {expected}). The mismatch "
                "may come from how the section structure was read."
            )
            severity = self.severity_ambiguous_structure
        else:
            title = f"{self.noun} {stated} differs from {expected} by printed rounding"
            explanation = (
                f"{row_label(self.table, row)}: {sum_text}; the difference of {difference} is "
                f"explainable by rounding of {len(basis.terms)} printed values."
            )
            severity = self.severity_display_rounding
        calculation = Calculation(
            operation="sum",
            operands=[
                CalculationOperand(
                    label=f"row {term.row.source_row_number}", value=term.amount, cell=ref
                )
                for term, ref in zip(basis.terms, refs, strict=False)
            ],
            operands_truncated=len(basis.terms) > len(refs),
            terms=len(basis.terms),
            exact_result=rec.exact,
            rounded_result=rec.expected,
            reported=reported,
            difference=rec.difference,
            allowed_difference=rec.allowed,
        )
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.CALCULATION,
                label="Sum",
                detail=clip(
                    f"{sum_text}; stated {stated}; difference {difference}; allowed ±{allowed}",
                    1000,
                ),
                calculation=calculation,
            ),
            EvidenceItem(
                kind=EvidenceKind.REFERENCE,
                label="Rows summed",
                detail=clip(
                    describe_rows([(self.table, term.row) for term in basis.terms], limit=20),
                    1000,
                ),
                cells=refs,
                data={
                    "members": len(basis.terms),
                    "basis": basis.kind.value,
                    "readings_tested": verdict.readings_tested,
                    "truncated": verdict.truncated,
                },
            ),
        ]
        if basis.left_out:
            # The rows themselves, not only their names: a stated total that includes them is
            # the usual cause of the difference, and a reader has to find them.
            evidence.append(
                EvidenceItem(
                    kind=EvidenceKind.NOTE,
                    label="Not counted",
                    detail=clip(
                        "Left out as not counted toward totals: "
                        + describe_rows([(self.table, r) for r in basis.left_out]),
                        1000,
                    ),
                    cells=[
                        self.context.cell_ref(self.table, r, self.total_field)
                        for r in basis.left_out[: self.max_cells]
                    ],
                    data={"rows": len(basis.left_out)},
                )
            )
        impact = None
        if outcome is Outcome.VIOLATION and len(basis.currencies) == 1:
            impact = FinancialImpact(
                amount=rec.difference,
                currency=next(iter(basis.currencies)),
                basis=f"stated {self.noun.lower()} minus {self.parts}",
                kind="discrepancy",
                reported=reported,
                recomputed=rec.expected,
            )
        return self.context.issues.create(
            self.spec,
            rule_id=f"{self.rule_prefix}_{_RULE_SUFFIX[outcome]}",
            category=self.category,
            severity=severity,
            evidence_class=_EVIDENCE[outcome],
            title=clip(title, 200),
            explanation=clip(explanation, 2000),
            table=self.table,
            row=row,
            cells=[self.context.cell_ref(self.table, row, self.total_field)],
            inputs=refs,
            observed_value=stated,
            expected_value=expected,
            evidence=evidence,
            suggested_action=(
                f"Check the {self.noun.lower()} and the amounts it sums in the source document; "
                "if the scope was read wrongly, correct the row classification."
            ),
            financial_impact=impact,
            subject=self.total_field,
        )


def incomplete_reason(table: Table, bases: Sequence[Basis]) -> str:
    """Why incomplete bases could not be checked, for a note ("... because <reason>.")."""
    unusable: list[Row] = []
    seen: set[str] = set()
    conflict = False
    for basis in bases:
        conflict = conflict or len(basis.currencies) > 1
        for row in basis.unusable:
            if row.row_id not in seen:
                seen.add(row.row_id)
                unusable.append(row)
    parts = []
    if unusable:
        rows = describe_rows([(table, row) for row in unusable])
        parts.append(f"amounts it would sum could not be read ({rows})")
    if conflict:
        parts.append("the amounts it would sum are marked with different currencies")
    return " and ".join(parts) or "its scope is incomplete"
