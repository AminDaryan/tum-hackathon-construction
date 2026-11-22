"""Every check at once, the value of each check by leaving it out, and status-quo baselines.

Used by the ``boq`` variant with ``--ablation`` (plan step B7) and by the answer-key scorer
(:mod:`app.evaluation.answer_key`). Every validation run checks with every registered check.

* **Leave-one-out ablation.** Each bill is validated again once per registered check, with that
  check left out of the registry (``runner.without_check``); nothing is attributed from the
  findings of the full run. For each
  check: the planted errors that no finding matches any more without it (*lost*), those that
  only a run without it finds (*gained*, when checks interact), and how the number of signals
  and rule findings on unplanted rows changes when it is left out (negative: it adds them).
  Every run is scored by :func:`app.evaluation.scoring.score_document`, as the benchmark scores.
* **Review budget.** A reviewer reads a limited number of items: the first K of a list, K = 20
  and 50 per bill, and K = the number of our findings in that bill (below). One item is one
  finding or one line. The lists compared:

  - ``findings``: the findings of every check, in the issue register's order (spelling and
    text-style findings last, otherwise severity, then position: ``ISSUE_ORDER`` of the
    repositories, the order ``iter_all`` returns), read as the
    benchmark's recall at 20 and 50 reads it: a correct risk note on an unplanted row (a list of
    the bill's contingency positions, :data:`app.evaluation.scoring.RISK_NOTE_RULES`) takes no
    place, a wrong one keeps its place and matches nothing. K = our findings counts the
    findings of that list;
  - ``top_to_bottom``: the lines of the bill in file order;
  - ``random``: the same lines in a random order (``random.Random`` seeded with the corpus seed
    and the bill's name, so every run draws the same order);
  - ``most_expensive``: the item lines by the size of their line total, largest first (ties in
    file order);
  - ``findings_and_most_expensive``: the two lists interleaved, a finding first, then the most
    expensive line not shown in a finding before it, and so on; when one list ends the other
    goes on. Each entry is one item of the budget.

  A *line* is an item row or a total row (subtotal, net total, tax, gross total): the rows that
  carry an amount. Section, text and blank rows are not counted, which favours the baselines.
  A planted error counts as found when an item read within the budget is on one of the rows
  where reporting it is correct, the same rule as for findings (:mod:`app.evaluation.scoring`).
  For the line lists this assumes a reviewer recognizes every error on a line read, which also
  favours the baselines.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.evaluation.boq_report import LABEL, fmt
from app.evaluation.scoring import (
    F2_BUDGET,
    Finding,
    f2_of,
    is_correct_risk_note,
    is_risk_note,
    mean_at_50,
    score_document,
)
from app.evaluation.synthetic import SyntheticDocument
from app.models.dataset import TOTAL_ROW_KINDS, Dataset, RowKind
from app.models.values import NumberValue

BUDGETS: tuple[int, ...] = (20, 50)
FINDINGS_BUDGET = "findings"  # K = the number of findings of every check in the bill
STRATEGIES: tuple[str, ...] = (
    "findings",
    "top_to_bottom",
    "random",
    "most_expensive",
    "findings_and_most_expensive",
)
STRATEGY_LABELS: dict[str, str] = {
    "findings": "Our findings (register order)",
    "top_to_bottom": "Lines top to bottom",
    "random": "Lines in random order",
    "most_expensive": "Most expensive lines first",
    "findings_and_most_expensive": "Findings and most expensive lines, interleaved",
}


def budget_labels() -> tuple[str, ...]:
    return (*(str(k) for k in BUDGETS), FINDINGS_BUDGET)


@dataclass(frozen=True)
class RunScore:
    """One validation run of a bill against its planted errors."""

    detected: frozenset[str]  # error ids a finding matches
    findings: int
    signals_on_unplanted_rows: int
    rules_on_unplanted_rows: int
    matched_by: dict[str, frozenset[str]]  # per check: error ids its findings match
    planted: int
    detected_at_50: int  # errors the first 50 findings of the reading list match
    shown_at_50: int  # findings among those 50
    true_positives_at_50: int  # of them, true positives
    # The findings as a reading list in the register's order, each as the rows it shows: a
    # correct risk note on an unplanted row takes no place, a wrong one shows nothing.
    order: list[frozenset[int]]


def run_score(
    findings: Sequence[Finding], doc: SyntheticDocument, signal_checks: Collection[str]
) -> RunScore:
    """``findings`` scored as the benchmark scores them
    (:func:`app.evaluation.scoring.score_document`, with the bill's contingency positions as the
    rows a correct risk note may name): a correct risk note on an unplanted row is neither a hit
    nor a finding on an unplanted row and takes no place in the reading list, as in the
    benchmark's recall at 20 and 50; a wrong one matches nothing and counts as a rule finding on
    an unplanted row."""
    noted = doc.contingency_and_hourly_rows
    score = score_document(findings, doc.truths, k=1, noted_rows=noted)
    signals = sum(1 for f in score.false_positives if f.detector_id in signal_checks)
    matched: dict[str, set[str]] = {}
    for outcome in score.outcomes:
        for hit in outcome.checks:
            matched.setdefault(hit.detector_id, set()).add(outcome.truth.error_id)
    correct_notes = {id(f) for f in score.correct_notes}
    return RunScore(
        detected=frozenset(o.truth.error_id for o in score.outcomes if o.detected),
        findings=len(findings),
        signals_on_unplanted_rows=signals,
        rules_on_unplanted_rows=len(score.false_positives) - signals,
        matched_by={check: frozenset(ids) for check, ids in matched.items()},
        planted=len(doc.truths),
        detected_at_50=score.detected_at_50,
        shown_at_50=score.shown_at_50,
        true_positives_at_50=score.true_positives_at_50,
        order=[
            frozenset() if is_risk_note(f) and not is_correct_risk_note(f, noted) else f.rows
            for f in findings
            if id(f) not in correct_notes
        ],
    )


def _amount(dataset: Dataset, table_index: int, row_index: int) -> Decimal | None:
    table = dataset.tables[table_index]
    for column in table.columns:
        if column.mapping is not None and column.mapping.field_id == "line_total":
            cell = table.rows[row_index].cells.get(column.column_id)
            value = cell and (cell.normalized_value or cell.parsed_value)
            return value.value if isinstance(value, NumberValue) else None
    return None


def reading_lists(dataset: Dataset | None) -> tuple[list[int], list[int]]:
    """(the lines in file order, the item lines by the size of their line total, largest
    first), as source row numbers."""
    if dataset is None:
        return [], []
    lines: list[int] = []
    priced: list[tuple[Decimal, int]] = []
    for t, table in enumerate(dataset.tables):
        for r, row in enumerate(table.rows):
            kind = row.classification.kind
            if row.excluded or (kind is not RowKind.ITEM and kind not in TOTAL_ROW_KINDS):
                continue
            lines.append(row.source_row_number)
            if kind is RowKind.ITEM:
                amount = _amount(dataset, t, r)
                if amount is not None:
                    priced.append((abs(amount), row.source_row_number))
    lines.sort()
    priced.sort(key=lambda item: (-item[0], item[1]))
    return lines, [row for _, row in priced]


def interleave(
    findings: Sequence[frozenset[int]], expensive: Sequence[int]
) -> list[frozenset[int]]:
    """A finding, then the most expensive line no finding shown so far covers, in turn."""
    merged: list[frozenset[int]] = []
    shown: set[int] = set()
    lines = iter(expensive)
    for rows in findings:
        merged.append(rows)
        shown |= rows
        for row in lines:
            if row not in shown:
                merged.append(frozenset({row}))
                shown.add(row)
                break
    merged.extend(frozenset({row}) for row in lines if row not in shown)
    return merged


def reading_orders(
    ours: Sequence[frozenset[int]], dataset: Dataset | None, *, seed: str
) -> dict[str, list[frozenset[int]]]:
    """The item lists of the review-budget comparison, each item as the rows it shows; ``ours``
    is our findings in the register's order."""
    lines, expensive = reading_lists(dataset)
    shuffled = list(lines)
    random.Random(seed).shuffle(shuffled)  # noqa: S311 - a fixed reading order, not security
    return {
        "findings": list(ours),
        "top_to_bottom": [frozenset({row}) for row in lines],
        "random": [frozenset({row}) for row in shuffled],
        "most_expensive": [frozenset({row}) for row in expensive],
        "findings_and_most_expensive": interleave(ours, expensive),
    }


def found_within(
    order: Sequence[frozenset[int]], truths: Mapping[str, frozenset[int]], budget: int
) -> frozenset[str]:
    read = frozenset().union(*order[:budget]) if budget else frozenset()
    return frozenset(error for error, rows in truths.items() if not rows.isdisjoint(read))


def budget_at_50(
    orders: Mapping[str, Sequence[frozenset[int]]], truths: Mapping[str, frozenset[int]]
) -> dict[str, tuple[float, float, float] | None]:
    """Per list, (F2, precision, recall) at 50 of one bill: precision is the items among its
    first ``F2_BUDGET`` that show a row of a planted error, over the items read; recall is the
    planted errors those items find (:func:`app.evaluation.scoring.f2_of`)."""
    planted = frozenset().union(*truths.values()) if truths else frozenset()
    return {
        name: f2_of(
            sum(1 for rows in order[:F2_BUDGET] if not rows.isdisjoint(planted)),
            len(order[:F2_BUDGET]),
            len(found_within(order, truths, F2_BUDGET)),
            len(truths),
        )
        for name, order in orders.items()
    }


def budget_counts(
    orders: Mapping[str, Sequence[frozenset[int]]],
    truths: Mapping[str, frozenset[int]],
    findings: int,
) -> dict[str, dict[str, int]]:
    """Per list and budget: the planted errors found within it."""
    budgets = {**{str(k): k for k in BUDGETS}, FINDINGS_BUDGET: findings}
    return {
        name: {label: len(found_within(order, truths, k)) for label, k in budgets.items()}
        for name, order in orders.items()
    }


@dataclass(frozen=True)
class BillMeasure:
    planted: int
    all_checks: RunScore
    without: dict[str, RunScore]  # per registered check: the run with it left out
    matched_by: dict[str, frozenset[str]]  # per check: error ids its findings match (full run)
    budgets: dict[str, dict[str, int]]  # list -> budget -> planted errors found within it
    budget_at_50: dict[str, tuple[float, float, float] | None]  # list -> (F2, P, R) at 50
    lines: int


def measure_bill(
    doc: SyntheticDocument,
    dataset: Dataset | None,
    findings: Sequence[Finding],
    without: dict[str, RunScore],
    *,
    signal_checks: Collection[str],
    seed: int,
) -> BillMeasure:
    truths = {truth.error_id: frozenset(truth.rows) for truth in doc.truths}
    full = run_score(findings, doc, signal_checks)
    orders = reading_orders(full.order, dataset, seed=f"{seed}:{doc.name}")
    return BillMeasure(
        planted=len(doc.truths),
        all_checks=full,
        without=without,
        matched_by=full.matched_by,
        budgets=budget_counts(orders, truths, len(full.order)),
        budget_at_50=budget_at_50(orders, truths),
        lines=len(orders["top_to_bottom"]),
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def at_50(runs: Sequence[RunScore]) -> dict[str, float | None]:
    """F2 at 50 and its mean precision and recall over the bills of ``runs`` with planted errors
    (:mod:`app.evaluation.scoring`)."""
    return mean_at_50(
        f2_of(r.true_positives_at_50, r.shown_at_50, r.detected_at_50, r.planted) for r in runs
    )


def build(
    measures: Sequence[BillMeasure],
    *,
    checks: Sequence[str],
    signal_checks: Collection[str],
    seed: int,
) -> dict[str, Any]:
    """The ``ablation`` section of a boq report."""
    planted = sum(m.planted for m in measures)
    detected = sum(len(m.all_checks.detected) for m in measures)
    per_check: dict[str, dict[str, Any]] = {}
    scores = at_50([m.all_checks for m in measures])
    f2_all = scores["f2_at_50"]
    for check in checks:
        lost = gained = matched = only = 0
        signals = rules = findings = 0
        for m in measures:
            run = m.without[check]
            lost += len(m.all_checks.detected - run.detected)
            gained += len(run.detected - m.all_checks.detected)
            mine = m.matched_by.get(check, frozenset())
            matched += len(mine)
            others = frozenset().union(*(ids for c, ids in m.matched_by.items() if c != check))
            only += len(mine - others)
            signals += m.all_checks.signals_on_unplanted_rows - run.signals_on_unplanted_rows
            rules += m.all_checks.rules_on_unplanted_rows - run.rules_on_unplanted_rows
            findings += m.all_checks.findings - run.findings
        f2_without = at_50([m.without[check] for m in measures])["f2_at_50"]
        per_check[check] = {
            "signal": check in signal_checks,
            "f2_at_50_without": f2_without,
            "f2_at_50_added": (
                f2_all - f2_without if f2_all is not None and f2_without is not None else None
            ),
            "matched": matched,
            "only_match": only,
            "lost_without": lost,
            "gained_without": gained,
            "findings_added": findings,
            "signals_on_unplanted_rows_added": signals,
            "rule_findings_on_unplanted_rows_added": rules,
        }
    budgets: dict[str, dict[str, int]] = {
        name: dict.fromkeys(budget_labels(), 0) for name in STRATEGIES
    }
    for m in measures:
        for name, counts in m.budgets.items():
            for label, found in counts.items():
                budgets[name][label] += found
    findings_total = sum(m.all_checks.findings for m in measures)
    return {
        "label": LABEL,
        "seed": seed,
        "bills": len(measures),
        "checks": list(checks),
        **scores,
        "planted_errors": planted,
        "detected": detected,
        "recall": _ratio(detected, planted),
        "findings": findings_total,
        "lines": sum(m.lines for m in measures),
        "signals_on_unplanted_rows": sum(m.all_checks.signals_on_unplanted_rows for m in measures),
        "rule_findings_on_unplanted_rows": sum(
            m.all_checks.rules_on_unplanted_rows for m in measures
        ),
        "per_check": per_check,
        "review_budget": {
            name: {
                label: {"found": found, "recall": _ratio(found, planted)}
                for label, found in counts.items()
            }
            for name, counts in budgets.items()
        },
        "review_budget_f2_at_50": {
            name: mean_at_50(m.budget_at_50[name] for m in measures)["f2_at_50"]
            for name in STRATEGIES
        },
    }


def ablation_table(per_check: Mapping[str, Mapping[str, Any]]) -> list[str]:
    lines = [
        "| Check | Kind | F2 at 50 it adds | Errors its findings match | Only it matches | "
        "Lost without it | "
        "Gained without it | Findings it adds | Signals on unplanted rows it adds | "
        "Rule findings on unplanted rows it adds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for check, entry in per_check.items():
        lines.append(
            f"| `{check}` | {'signal' if entry['signal'] else 'rule'} | "
            f"{_signed(entry['f2_at_50_added'])} | {entry['matched']} | "
            f"{entry['only_match']} | {entry['lost_without']} | {entry['gained_without']} | "
            f"{entry['findings_added']} | {entry['signals_on_unplanted_rows_added']} | "
            f"{entry['rule_findings_on_unplanted_rows_added']} |"
        )
    return lines


def _signed(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.3f}"


def budget_table(
    review_budget: Mapping[str, Mapping[str, Mapping[str, Any]]],
    f2: Mapping[str, float | None],
) -> list[str]:
    labels = budget_labels()
    head = [f"K = {label}" if label != FINDINGS_BUDGET else "K = our findings" for label in labels]
    lines = [
        "| Reading list | F2 at 50 | " + " | ".join(head) + " |",
        "| --- | --- | " + " | ".join("---" for _ in labels) + " |",
    ]
    for name, counts in review_budget.items():
        cells = [f"{counts[label]['found']} ({fmt(counts[label]['recall'])})" for label in labels]
        lines.append(
            f"| {STRATEGY_LABELS[name]} | {fmt(f2.get(name))} | " + " | ".join(cells) + " |"
        )
    return lines


def unhelpful(per_check: Mapping[str, Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """(checks whose removal loses no planted error, those of them that add findings on
    unplanted rows)."""
    idle = [check for check, entry in per_check.items() if entry["lost_without"] == 0]
    harmful = [
        check
        for check in idle
        if per_check[check]["signals_on_unplanted_rows_added"] > 0
        or per_check[check]["rule_findings_on_unplanted_rows_added"] > 0
    ]
    return idle, harmful


def render(section: Mapping[str, Any]) -> list[str]:
    """The markdown of the ``ablation`` section."""
    caption = f"{LABEL}."
    idle, harmful = unhelpful(section["per_check"])
    counts = Counter(entry["signal"] for entry in section["per_check"].values())
    return [
        "",
        "## All checks",
        "",
        caption,
        "",
        f"Every registered check runs: {counts[False]} rule checks and {counts[True]} signal "
        "checks.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| **F2 at 50 (main score)** | **{fmt(section['f2_at_50'])}** |",
        f"| Precision at 50 (mean) | {fmt(section['mean_precision_at_50'])} |",
        f"| Recall at 50 (mean) | {fmt(section['mean_recall_at_50'])} |",
        f"| Planted errors | {section['planted_errors']} |",
        f"| Found by any check | {section['detected']} |",
        f"| Recall | {fmt(section['recall'])} |",
        f"| Findings | {section['findings']} |",
        f"| Signals on unplanted rows | {section['signals_on_unplanted_rows']} |",
        f"| Rule findings on unplanted rows | {section['rule_findings_on_unplanted_rows']} |",
        "",
        "### Leave-one-out ablation",
        "",
        caption,
        "",
        "Each bill validated again once per check, with that check left out. *Lost without it*: "
        "planted errors no finding matches any more; *gained*: errors only the run without it "
        "finds. The last three columns are the full run's count minus the run without the "
        "check. *Errors its findings match* and *only it matches* are read from the full run, "
        "for comparison. *F2 at 50 it adds*: the full run's F2 at 50 minus the run without it "
        "(negative: the score rises without it).",
        "",
        *ablation_table(section["per_check"]),
        "",
        "Checks whose removal loses no planted error: "
        + (", ".join(f"`{c}`" for c in idle) or "none")
        + ". Of them adding findings on unplanted rows: "
        + (", ".join(f"`{c}`" for c in harmful) or "none")
        + ".",
        "",
        "### Review budget",
        "",
        caption,
        "",
        "Planted errors found within the first K items a reviewer reads per bill (recall in "
        "brackets). One item is one finding or one line (an item or total row); the lists and "
        "their assumptions are described in `backend/app/evaluation/ablation.py`. The interleaved "
        "list alternates a finding and the most expensive line not yet shown. F2 at 50 of a "
        "list, per bill with planted errors and then averaged: precision is the items among "
        "its first 50 that show a row of a planted error, over the items read; recall is the "
        "planted errors they find.",
        "",
        *budget_table(section["review_budget"], section["review_budget_f2_at_50"]),
    ]
