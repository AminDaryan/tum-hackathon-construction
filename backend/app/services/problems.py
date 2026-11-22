"""Problems (plan step B4): the findings of one run that concern the same mistake, joined
deterministically and computed from the stored findings whenever they are read, never stored.

Two findings join when one of these holds (``ProblemLinkKind``):

* ``same_cell``: both highlight the same cell;
* ``same_row``: both concern the same row (a wrong unit price that breaks its line total and
  stands out against similar positions);
* ``carried_difference``: a total's finding computed from a cell another finding highlights,
  with the same exact amount of money in the same currency (a wrong line total carried into its
  subtotal and the grand total). Equal amounts are required, so two unrelated mistakes under
  one subtotal stay two problems.

Joining is transitive (a line total, its subtotal and the grand total become one problem). The
primary finding is the strongest: confirmed before signals, then by severity, then a finding on
an item row before one on a total. The money at stake is the primary finding's exact amount when
it has one in an explicit currency and the amount was computed exactly (a difference or a double
count); a comparison with other positions is an estimate, shown as ``reference_deviation`` and
never ranked as money at stake. Amounts of the other findings are never added, because they are
the same difference seen again. The corrected value is the primary finding's recomputed
value (``corrected_value``), shown only when a rule computed it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from pydantic import Field

from app.core.errors import NotFoundError
from app.models.base import FrozenModel
from app.models.finding_category import FindingCategory
from app.models.issue import SEVERITY_RANK, EvidenceClass, ValidationIssue
from app.models.problem import AnomalyType, Problem, ProblemLink, ProblemLinkKind
from app.models.values import ExactDecimal
from app.repositories.base import IssueQuery
from app.services.workbench import Workbench

# The anomaly type of a check's findings, by its detector id; the prefix decides for the rest.
ANOMALY_TYPE_BY_DETECTOR: dict[str, AnomalyType] = {
    "deterministic.line_total": AnomalyType.LOGICAL,
    "deterministic.subtotal": AnomalyType.LOGICAL,
    "deterministic.grand_total": AnomalyType.LOGICAL,
    "deterministic.formula_errors": AnomalyType.LOGICAL,
    "deterministic.currency_consistency": AnomalyType.LOGICAL,
    "deterministic.exact_duplicates": AnomalyType.DUPLICATE,
    "machine_learning.near_duplicates": AnomalyType.DUPLICATE,
    "deterministic.unit_vocabulary": AnomalyType.UNIT,
    "deterministic.unit_compatibility": AnomalyType.UNIT,
    "semantic.unit_fit": AnomalyType.UNIT,
    "deterministic.data_type_conformance": AnomalyType.QUANTITY,
    "statistical.quantity_factor": AnomalyType.QUANTITY,
    "statistical.peer_price": AnomalyType.PRICE,
    "statistical.rate_consistency": AnomalyType.PRICE,
    "domain.standard_text_keys": AnomalyType.PRICE,
    "semantic.section_fit": AnomalyType.SEMANTIC,
    "domain.boq_description_clarity": AnomalyType.SEMANTIC,
    "domain.boq_contradictions": AnomalyType.SEMANTIC,
    "domain.boq_typos": AnomalyType.SEMANTIC,
}
_TOTALS = frozenset(
    {"deterministic.subtotal", "deterministic.grand_total"},
)
# Amounts a check computed exactly: a difference between stated and recomputed figures, or the
# line total of a possible double count. A comparison with other positions is an estimate.
_EXACT_KINDS = frozenset({"discrepancy", "potential_double_count"})
_EVIDENCE_RANK = {
    EvidenceClass.HUMAN_CONFIRMED_ERROR: 0,
    EvidenceClass.CONFIRMED_RULE_VIOLATION: 1,
    EvidenceClass.SUSPECTED_ANOMALY: 2,
    EvidenceClass.SEMANTIC_WARNING: 3,
    EvidenceClass.NEEDS_EXTERNAL_CONTEXT: 4,
    EvidenceClass.EXTRACTION_UNCERTAINTY: 5,
}


class ProblemView(Problem):
    """A problem as the API shows it: the stored model plus what the reviewer reads first.
    ``reference_deviation`` is what would change if the primary finding's row were priced or
    measured like the positions it was compared with: an estimate, never money at stake."""

    finding_category: FindingCategory | None = None
    reference_deviation: ExactDecimal | None = None
    severity: str
    corrected_value: ExactDecimal | None = None
    row_ids: list[str] = Field(default_factory=list)


class ProblemList(FrozenModel):
    run_id: str
    total: int = Field(ge=0)
    findings: int = Field(ge=0, description="Findings of the run, joined into the problems.")
    problems: list[ProblemView]


def anomaly_type_of(issue: ValidationIssue) -> AnomalyType:
    known = ANOMALY_TYPE_BY_DETECTOR.get(issue.detector_id)
    if known is not None:
        return known
    if issue.detector_id.startswith("deterministic."):
        return AnomalyType.STRUCTURAL
    return AnomalyType.SEMANTIC


def _strength(issue: ValidationIssue) -> tuple[int, int, int, str]:
    on_total = 1 if issue.detector_id in _TOTALS else 0
    return (
        _EVIDENCE_RANK.get(issue.effective_evidence_class, 9),
        -SEVERITY_RANK[issue.severity],
        on_total,
        issue.issue_id,
    )


def _amount(issue: ValidationIssue) -> tuple[Decimal, str] | None:
    impact = issue.estimated_financial_impact
    if impact is None or impact.kind != "discrepancy":
        return None
    return abs(impact.amount), impact.currency


def build_problems(issues: Sequence[ValidationIssue]) -> list[ProblemView]:
    """Join ``issues`` (one run's findings) into problems, the most money at stake first, then
    the strongest evidence."""
    parent = list(range(len(issues)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    links: list[tuple[int, int, ProblemLinkKind, str]] = []

    def join(a: int, b: int, kind: ProblemLinkKind, detail: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        parent[max(ra, rb)] = min(ra, rb)
        links.append((a, b, kind, detail))

    by_cell: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    by_row: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, issue in enumerate(issues):
        for cell in issue.affected_cells:
            by_cell[cell.key].append(i)
        if issue.table_id and issue.row_id:
            by_row[(issue.table_id, issue.row_id)].append(i)
    for members in by_cell.values():
        for other in members[1:]:
            join(members[0], other, ProblemLinkKind.SAME_CELL, "Both highlight the same cell.")
    for members in by_row.values():
        for other in members[1:]:
            join(members[0], other, ProblemLinkKind.SAME_ROW, "Both concern the same position.")
    for t, total in enumerate(issues):
        if total.detector_id not in _TOTALS or (amount := _amount(total)) is None:
            continue
        for cell in total.input_cells:
            for i in by_cell.get(cell.key, ()):
                if i != t and _amount(issues[i]) == amount:
                    join(
                        i,
                        t,
                        ProblemLinkKind.CARRIED_DIFFERENCE,
                        f"The same difference of {amount[0]} {amount[1]} is carried into the "
                        "total.",
                    )

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(issues)):
        groups[find(i)].append(i)
    group_links: dict[int, list[tuple[int, int, ProblemLinkKind, str]]] = defaultdict(list)
    for link in links:
        group_links[find(link[0])].append(link)

    by_id = {issue.issue_id: issue for issue in issues}
    problems: list[ProblemView] = []
    for root, members in groups.items():
        primary = min((issues[i] for i in members), key=_strength)
        impact = primary.estimated_financial_impact
        exact = impact if impact is not None and impact.kind in _EXACT_KINDS else None
        estimate = impact if impact is not None and impact.kind == "reference_deviation" else None
        corrected = exact.recomputed if exact is not None and exact.kind == "discrepancy" else None
        rows = list(dict.fromkeys(issues[i].row_id for i in members if issues[i].row_id))
        problems.append(
            ProblemView(
                problem_id=f"prb_{primary.issue_id}",
                issue_ids=[issues[i].issue_id for i in members],
                primary_issue_id=primary.issue_id,
                links=[
                    ProblemLink(
                        kind=kind,
                        from_issue_id=issues[a].issue_id,
                        to_issue_id=issues[b].issue_id,
                        detail=detail,
                    )
                    for a, b, kind, detail in group_links[root]
                ],
                anomaly_type=anomaly_type_of(primary),
                money_at_stake=exact.amount if exact is not None else None,
                currency=exact.currency if exact is not None else None,
                reference_deviation=estimate.amount if estimate is not None else None,
                title=primary.title,
                finding_category=primary.finding_category,
                severity=primary.severity.value,
                corrected_value=corrected,
                row_ids=[row for row in rows if row is not None],
            )
        )
    strength = {p.problem_id: _strength(by_id[p.primary_issue_id]) for p in problems}
    problems.sort(
        key=lambda p: (
            -(abs(p.money_at_stake) if p.money_at_stake is not None else Decimal(-1)),
            strength[p.problem_id],
        )
    )
    return problems


def list_for_run(wb: Workbench, run_id: str) -> ProblemList:
    with wb.uow() as uow:
        if uow.runs.get(run_id) is None:
            raise NotFoundError(f"Unknown validation run {run_id!r}.")
        issues = list(uow.issues.iter_all(IssueQuery(run_id=run_id)))
    problems = build_problems(issues)
    return ProblemList(run_id=run_id, total=len(problems), findings=len(issues), problems=problems)
