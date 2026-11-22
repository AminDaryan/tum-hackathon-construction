"""Matching findings to injected errors, and the benchmark metrics (brief Part L).

A finding is located by its highlighted cells (``affected_cells``) and its row, in source row
numbers; the cells it was computed from (``input_cells``) do not count, or every subtotal finding
would match every item of its section. A finding is a **true positive** when one of its rows is
a row where reporting an injected error is correct (the error's own row or a total it throws
off); otherwise it is a **false positive**, unless it is a correct **risk note**: a finding of a
rule in :data:`RISK_NOTE_RULES` (a list of the bill's contingency and hourly positions) every
row of which is such a position of the generated bill, by the generator's own item types
(``SyntheticDocument.contingency_and_hourly_rows``). The generators write those positions as
normal content, so listing them is correct and claims no error. A list is scored by every row
it names, its highlighted cells and the cells of its evidence (``Finding.evidence_rows``: the
highlighted cells of a long list stop at a cap, its evidence does not). A list that names any
other row is a false positive, even when it also names a row with an injected error: it does
not count as a true positive or match that error. A correct list that names a row with an
injected error is a true positive. Correct risk notes on other rows are counted on their own and
left out of precision, precision at K and false positives per 1,000 rows. An injected error is
**detected** when at
least one finding matches it, and **localized** when a matching finding highlights the exact
cell holding the mistake (the row, for a duplicated row).

Metrics, all computed over the whole set (micro-averaged):

* precision = true-positive findings / (true-positive and false-positive findings); recall =
  detected errors / injected errors;
  F1 = their harmonic mean;
* precision at K = true positives among the first K findings other than correct risk notes, in
  the order a reviewer sees them (spelling and text-style findings last, otherwise severity,
  then position), divided by the number of those findings shown (at most K); averaged over
  documents that have such findings;
* **F2 at 50, the main score** (not micro-averaged) = per document with at least one injected
  error, the F-beta score with beta = 2 (recall weighs four times as much as precision),
  5PR / (4P + R), of P = true-positive findings among its first 50 findings in the reviewer's
  order (the list recall at 50 reads, below) over the findings shown there (at most 50; none
  shown gives P = 0) and R = its injected errors those 50 match over its injected errors;
  averaged over those documents, as are the precision at 50 and the recall at 50 reported
  beside it. Every finding counts, signals included. Documents without injected errors have no
  F2; their findings count in the false positives;
* recall at 20/50 = distinct errors matched in the first 20/50 findings of that same list (a
  risk note that names a wrong row takes its place but matches nothing), divided by all
  injected errors; this does not measure a two-lane review allocation;
* false positives per 1,000 rows (data rows of the generated documents);
* cell localization = localized errors / detected errors;
* row classification accuracy = generated rows whose recognized kind is the kind the generator
  meant.

Values are ratios over this set; they are not probabilities and say nothing about other data.

Each planted error also records which checks matched it (:class:`CheckHit`: the detector, its
rules and whether it highlighted the wrong cell), how many findings did and the finding
categories they carry, for the per-check and per-category metrics of the ``boq`` variant
(:mod:`app.evaluation.boq_report`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.evaluation.synthetic import GroundTruth, SyntheticDocument
from app.models.dataset import Dataset
from app.models.finding_category import FindingCategoryKey, finding_category_of
from app.models.issue import ValidationIssue


@dataclass(frozen=True)
class Finding:
    issue_id: str
    detector_id: str
    rule_id: str
    severity: str
    title: str
    rows: frozenset[int]
    cells: frozenset[tuple[int, str | None]]  # (source row, field id)
    # Used only to order signals for inspection: the detector's raw anomaly score (never a
    # probability) and the amount of its financial impact, both as magnitudes.
    score: float | None = None
    impact: Decimal | None = None
    # Rows of the cells its evidence names (a list names every position there): read only to
    # score a risk note, as evidence also holds the input cells a finding was computed from.
    evidence_rows: frozenset[int] = frozenset()


def findings_of(issues: Iterable[ValidationIssue], dataset: Dataset) -> list[Finding]:
    """The issues located in source coordinates, in the order given (the reviewer's order)."""
    rows = {(t.table_id, r.row_id): r.source_row_number for t in dataset.tables for r in t.rows}
    fields = {
        (t.table_id, c.column_id): c.mapping.field_id if c.mapping else None
        for t in dataset.tables
        for c in t.columns
    }
    result = []
    for issue in issues:
        located_rows: set[int] = set()
        cells: set[tuple[int, str | None]] = set()
        for cell in issue.affected_cells:
            row = rows.get((cell.table_id, cell.row_id))
            if row is not None:
                located_rows.add(row)
                cells.add((row, fields.get((cell.table_id, cell.column_id))))
        if issue.table_id is not None and issue.row_id is not None:
            row = rows.get((issue.table_id, issue.row_id))
            if row is not None:
                located_rows.add(row)
        evidence_rows = {
            row
            for item in issue.evidence
            for cell in item.cells
            if (row := rows.get((cell.table_id, cell.row_id))) is not None
        }
        impact = issue.estimated_financial_impact
        result.append(
            Finding(
                issue_id=issue.issue_id,
                detector_id=issue.detector_id,
                rule_id=issue.rule_id,
                severity=issue.severity.value,
                title=issue.title,
                rows=frozenset(located_rows),
                cells=frozenset(cells),
                score=abs(issue.anomaly_score.value) if issue.anomaly_score else None,
                impact=abs(impact.amount) if impact is not None else None,
                evidence_rows=frozenset(evidence_rows),
            )
        )
    return result


# Rules whose finding lists positions a bill holds as normal content (plan section 5a: risk
# notes): domain.boq_position_types lists the contingency and hourly positions.
RISK_NOTE_RULES: frozenset[tuple[str, str]] = frozenset(
    {("domain.boq_position_types", "contingency_and_hourly")}
)


RISK_NOTES_LINE = "Risk notes on unplanted rows, checked against the generated bill"


def risk_notes_text(correct: int, false: int) -> str:
    """The value of :data:`RISK_NOTES_LINE` in a report: the risk notes on unplanted rows and
    how many were correct (the others count as false positives)."""
    if not false:
        return f"{correct}, all correct"
    return f"{correct + false}, {correct} correct ({false} counted as false positives)"


def is_risk_note(finding: Finding) -> bool:
    """True when ``finding`` is of a rule in :data:`RISK_NOTE_RULES` (a list of positions)."""
    return (finding.detector_id, finding.rule_id) in RISK_NOTE_RULES


def is_correct_risk_note(finding: Finding, noted_rows: frozenset[int]) -> bool:
    """True when ``finding`` is a risk note every row of which, highlighted or in its evidence,
    is in ``noted_rows`` (the contingency and hourly positions of the generated bill)."""
    listed = finding.rows | finding.evidence_rows
    return is_risk_note(finding) and bool(listed) and listed <= noted_rows


def _matches(finding: Finding, truth: GroundTruth) -> bool:
    return not finding.rows.isdisjoint(truth.rows)


def finding_category_key(finding: Finding) -> str:
    """The finding category ``finding`` carries, as filters and counts name it (``none``
    without one): the same computation as ``ValidationIssue.finding_category``."""
    category = finding_category_of(detector_id=finding.detector_id, rule_id=finding.rule_id)
    return FindingCategoryKey(category or FindingCategoryKey.NONE).value


def _localizes(finding: Finding, truth: GroundTruth) -> bool:
    if truth.field is None:
        return truth.row in finding.rows
    return (truth.row, truth.field) in finding.cells


@dataclass(frozen=True)
class CheckHit:
    """The findings of one check that match one injected error."""

    detector_id: str
    rule_ids: tuple[str, ...]
    localized: bool


@dataclass(frozen=True)
class ErrorOutcome:
    truth: GroundTruth
    detected: bool
    expected_rule: bool
    localized: bool
    rules: tuple[str, ...]  # rules of the matching findings
    checks: tuple[CheckHit, ...] = ()  # per check, in detector id order
    findings: int = 0  # matching findings
    # The finding categories of the matching findings (FindingCategoryKey values, "none" for a
    # finding about reading the file), sorted.
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentResult:
    document: SyntheticDocument
    score: DocumentScore
    classified: tuple[int, int]  # (rows recognized as the intended kind, rows compared)
    misclassified: tuple[tuple[int, str, str], ...]  # (row, intended, recognized)
    seconds: float
    status: str  # the document's processing status


@dataclass(frozen=True)
class DocumentScore:
    findings: int
    true_positives: int
    false_positives: tuple[Finding, ...]
    outcomes: tuple[ErrorOutcome, ...]
    precision_at_k: float | None  # None when the document has no findings but risk notes
    detectors: tuple[str, ...] = ()  # the detector of every finding, in the reviewer's order
    # Correct risk notes (see the module docstring): neither true nor false positives.
    correct_notes: tuple[Finding, ...] = ()
    detected_at_20: int = 0
    detected_at_50: int = 0
    shown_at_50: int = 0  # findings among the first 50 of the reviewer's list
    true_positives_at_50: int = 0  # of them, true positives

    def at_50(self) -> tuple[float, float, float] | None:
        """(F2, precision, recall) at 50; None without injected errors."""
        return f2_of(
            self.true_positives_at_50, self.shown_at_50, self.detected_at_50, len(self.outcomes)
        )


F2_BUDGET = 50  # the first findings per bill that F2 at 50 reads


def f_beta(precision: float | None, recall: float | None, beta: float = 2.0) -> float | None:
    """The F-beta score (``beta`` = 2: recall weighs four times as much as precision); None
    when either is undefined, 0 when both are 0."""
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def f2_of(hits: int, shown: int, found: int, planted: int) -> tuple[float, float, float] | None:
    """(F2, precision, recall) of one bill's first findings: ``hits`` of the ``shown`` findings
    are right and they find ``found`` of its ``planted`` errors; None when nothing is planted."""
    if not planted:
        return None
    precision = hits / shown if shown else 0.0
    recall = found / planted
    return f_beta(precision, recall) or 0.0, precision, recall


def mean_at_50(scores: Iterable[tuple[float, float, float] | None]) -> dict[str, float | None]:
    """``f2_at_50``, ``mean_precision_at_50`` and ``mean_recall_at_50``: means over the bills
    that have a score (those with planted errors)."""
    present = [score for score in scores if score is not None]
    names = ("f2_at_50", "mean_precision_at_50", "mean_recall_at_50")
    return {
        name: sum(score[i] for score in present) / len(present) if present else None
        for i, name in enumerate(names)
    }


def score_document(
    findings: Sequence[Finding],
    truths: Sequence[GroundTruth],
    *,
    k: int,
    noted_rows: frozenset[int] = frozenset(),
) -> DocumentScore:
    """Score ``findings`` against ``truths``; ``noted_rows`` are the rows a correct risk note
    may name (the generated bill's contingency and hourly positions)."""
    # A risk note that names a row it should not is false, whatever else it names.
    wrong = [is_risk_note(f) and not is_correct_risk_note(f, noted_rows) for f in findings]
    hits = [
        not bad and any(_matches(f, t) for t in truths)
        for f, bad in zip(findings, wrong, strict=True)
    ]
    notes = [
        not hit and not bad and is_risk_note(f)
        for f, hit, bad in zip(findings, hits, wrong, strict=True)
    ]
    scored = [f for f, bad in zip(findings, wrong, strict=True) if not bad]
    outcomes = []
    for truth in truths:
        matching = [f for f in scored if _matches(f, truth)]
        by_check: dict[str, list[Finding]] = defaultdict(list)
        for finding in matching:
            by_check[finding.detector_id].append(finding)
        outcomes.append(
            ErrorOutcome(
                truth=truth,
                detected=bool(matching),
                expected_rule=any(f.rule_id in truth.expected_rules for f in matching),
                localized=any(_localizes(f, truth) for f in matching),
                rules=tuple(sorted({f.rule_id for f in matching})),
                checks=tuple(
                    CheckHit(
                        detector_id=detector_id,
                        rule_ids=tuple(sorted({f.rule_id for f in hits})),
                        localized=any(_localizes(f, truth) for f in hits),
                    )
                    for detector_id, hits in sorted(by_check.items())
                ),
                findings=len(matching),
                categories=tuple(sorted({finding_category_key(f) for f in matching})),
            )
        )
    shown = [hit for hit, note in zip(hits, notes, strict=True) if not note][:k]
    # The same list for recall at 20/50: a wrong risk note keeps its place but matches nothing.
    ranked = [
        None if bad else f for f, note, bad in zip(findings, notes, wrong, strict=True) if not note
    ]
    ranked_hits = [hit for hit, note in zip(hits, notes, strict=True) if not note][:F2_BUDGET]
    return DocumentScore(
        findings=len(findings),
        true_positives=sum(hits),
        false_positives=tuple(
            f for f, hit, note in zip(findings, hits, notes, strict=True) if not hit and not note
        ),
        outcomes=tuple(outcomes),
        precision_at_k=sum(shown) / len(shown) if shown else None,
        detectors=tuple(f.detector_id for f in findings),
        correct_notes=tuple(f for f, note in zip(findings, notes, strict=True) if note),
        detected_at_20=_detected_within(ranked, truths, 20),
        detected_at_50=_detected_within(ranked, truths, 50),
        shown_at_50=len(ranked_hits),
        true_positives_at_50=sum(ranked_hits),
    )


def _detected_within(
    ranked: Sequence[Finding | None], truths: Sequence[GroundTruth], k: int
) -> int:
    """The errors of ``truths`` that one of the first ``k`` findings of ``ranked`` matches (None
    stands for a finding that matches nothing)."""
    return sum(any(f is not None and _matches(f, t) for f in ranked[:k]) for t in truths)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


@dataclass
class Tally:
    """Sums over any group of documents (all, one variant, ...)."""

    documents: int = 0
    rows: int = 0
    findings: int = 0
    true_positives: int = 0
    false_positives: int = 0
    correct_notes: int = 0
    injected: int = 0
    detected: int = 0
    detected_at_20: int = 0
    detected_at_50: int = 0
    expected_rule: int = 0
    localized: int = 0
    classified_rows: int = 0
    correctly_classified: int = 0
    seconds: float = 0.0
    precision_at_k: list[float] = field(default_factory=list)
    at_50: list[tuple[float, float, float] | None] = field(default_factory=list)

    def add(
        self, score: DocumentScore, *, rows: int, classified: tuple[int, int], seconds: float
    ) -> None:
        self.documents += 1
        self.rows += rows
        self.findings += score.findings
        self.true_positives += score.true_positives
        self.false_positives += len(score.false_positives)
        self.correct_notes += len(score.correct_notes)
        self.injected += len(score.outcomes)
        self.detected += sum(o.detected for o in score.outcomes)
        self.detected_at_20 += score.detected_at_20
        self.detected_at_50 += score.detected_at_50
        self.at_50.append(score.at_50())
        self.expected_rule += sum(o.expected_rule for o in score.outcomes)
        self.localized += sum(o.localized for o in score.outcomes)
        self.correctly_classified += classified[0]
        self.classified_rows += classified[1]
        self.seconds += seconds
        if score.precision_at_k is not None:
            self.precision_at_k.append(score.precision_at_k)

    def metrics(self) -> dict[str, float | int | None]:
        precision = _ratio(self.true_positives, self.true_positives + self.false_positives)
        recall = _ratio(self.detected, self.injected)
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall > 0
            else None
        )
        p_at_k = (
            sum(self.precision_at_k) / len(self.precision_at_k) if self.precision_at_k else None
        )
        return {
            "documents": self.documents,
            "rows": self.rows,
            "injected_errors": self.injected,
            "findings": self.findings,
            "true_positive_findings": self.true_positives,
            "false_positive_findings": self.false_positives,
            "correct_risk_notes": self.correct_notes,
            "detected_errors": self.detected,
            **mean_at_50(self.at_50),
            "precision": precision,
            "recall": recall,
            "recall_at_20": _ratio(self.detected_at_20, self.injected),
            "recall_at_50": _ratio(self.detected_at_50, self.injected),
            "f1": f1,
            "precision_at_k": p_at_k,
            "false_positives_per_1000_rows": (
                1000 * self.false_positives / self.rows if self.rows else None
            ),
            "detected_with_expected_rule": _ratio(self.expected_rule, self.injected),
            "cell_localization": _ratio(self.localized, self.detected),
            "row_classification_accuracy": _ratio(self.correctly_classified, self.classified_rows),
            "seconds": round(self.seconds, 3),
        }
