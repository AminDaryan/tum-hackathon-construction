"""``--ablation``: the leave-one-out ablation of every registered check and the review budget."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.evaluation.ablation import (
    FINDINGS_BUDGET,
    STRATEGIES,
    budget_counts,
    budget_labels,
    found_within,
    interleave,
    run_score,
)
from app.evaluation.boq_report import LABEL
from app.evaluation.runner import (
    BenchmarkConfig,
    benchmark_workbench,
    render_markdown,
    run_benchmark,
    run_findings,
    without_check,
)
from app.evaluation.scoring import Finding
from app.evaluation.synthetic import (
    BoqSettings,
    CorpusConfig,
    ErrorKind,
    GroundTruth,
    SyntheticDocument,
    generate_corpus,
)
from app.services import documents

pytestmark = pytest.mark.evaluation


def test_interleave_alternates_and_skips_lines_a_finding_showed() -> None:
    findings = [frozenset({7}), frozenset({3, 4})]
    assert interleave(findings, [3, 9, 4, 5]) == [
        frozenset({7}),
        frozenset({3}),
        frozenset({3, 4}),
        frozenset({9}),
        frozenset({5}),  # 4 was shown in the second finding
    ]


def test_an_error_is_found_within_a_budget_when_an_item_read_names_one_of_its_rows() -> None:
    truths = {"a": frozenset({2, 10}), "b": frozenset({5})}
    order = [frozenset({1}), frozenset({10}), frozenset({5})]
    assert found_within(order, truths, 0) == frozenset()
    assert found_within(order, truths, 2) == {"a"}
    assert found_within(order, truths, 3) == {"a", "b"}
    counts = budget_counts({"x": order}, truths, findings=1)
    assert counts == {"x": {"20": 2, "50": 2, FINDINGS_BUDGET: 0}}


def _finding(detector_id: str, rule_id: str, rows: set[int]) -> Finding:
    return Finding(
        issue_id=f"{rule_id}-{min(rows)}",
        detector_id=detector_id,
        rule_id=rule_id,
        severity="info",
        title="",
        rows=frozenset(rows),
        cells=frozenset(),
    )


def test_runs_are_scored_as_the_benchmark_scores_risk_notes() -> None:
    truth = GroundTruth(
        error_id="e",
        kind=ErrorKind.LINE_TOTAL,
        row=5,
        field=None,
        rows=(5,),
        expected_rules=(),
        change="",
    )
    doc = SyntheticDocument(
        name="b.xlsx",
        language="de",
        format="xlsx",
        content=b"",
        row_kinds={},
        truths=(truth,),
        contingency_and_hourly_rows=frozenset({8, 9}),
    )
    note, rule = "domain.boq_position_types", "contingency_and_hourly"
    findings = [
        _finding(note, rule, {8, 9}),  # correct risk note: no place, not on an unplanted row
        _finding(note, rule, {5, 7}),  # names a row that is no contingency position: wrong
        _finding("statistical.peer_price", "peer_price_outlier", {3}),
        _finding("deterministic.line_total", "line_total_mismatch", {5}),
    ]
    score = run_score(findings, doc, {"statistical.peer_price", note})
    assert score.detected == {"e"}
    assert score.matched_by == {"deterministic.line_total": frozenset({"e"})}
    assert score.order == [frozenset(), frozenset({3}), frozenset({5})]
    # The wrong note is a finding of a signal check here, so both count as signals.
    assert (score.signals_on_unplanted_rows, score.rules_on_unplanted_rows) == (2, 0)


def test_leaving_a_check_out_turns_off_only_that_check(tmp_path: Path) -> None:
    wb = benchmark_workbench(tmp_path / "wb")
    doc = generate_corpus(
        CorpusConfig(
            seed=3,
            documents_per_variant=1,
            max_errors=8,
            variant="boq",
            boq=BoqSettings(positions=(80, 90)),
        )
    )[0]
    _, dataset = documents.upload(
        wb, filename=doc.name, chunks=[doc.content], profile_id="boq", decisions=doc.decisions()
    )
    assert dataset is not None
    full = run_findings(wb, dataset)
    left_out = Counter(f.detector_id for f in full).most_common(1)[0][0]
    without = run_findings(without_check(wb, left_out), dataset)
    assert not any(f.detector_id == left_out for f in without)

    def keys(findings: list[Finding]) -> list[tuple[str, str, tuple[int, ...]]]:
        return sorted(
            (f.detector_id, f.rule_id, tuple(sorted(f.rows)))
            for f in findings
            if f.detector_id != left_out
        )

    assert keys(without) == keys(full)  # every other check finds the same
    assert wb.detectors.ids().count(left_out) == 1  # the workbench itself is unchanged


def test_ablation_report(tmp_path: Path) -> None:
    corpus = CorpusConfig(
        seed=11,
        documents_per_variant=3,
        max_errors=8,
        variant="boq",
        boq=BoqSettings(positions=(80, 120)),
    )
    report = run_benchmark(BenchmarkConfig(corpus=corpus, ablation=True), tmp_path)
    section = report["boq"]["ablation"]
    wb = benchmark_workbench(tmp_path / "wb")
    assert set(section["per_check"]) == {spec.detector_id for spec in wb.detectors.specs()}
    assert section["planted_errors"] == report["synthetic"]["injected_errors"]
    assert section["detected"] == report["synthetic"]["detected_errors"]
    budget = section["review_budget"]
    assert set(budget) == set(STRATEGIES)
    assert all(set(counts) == set(budget_labels()) for counts in budget.values())
    # K = the number of our findings: reading all of them finds what the checks find.
    assert budget["findings"][FINDINGS_BUDGET]["found"] == section["detected"]
    assert budget["findings"]["20"]["found"] == round(
        report["synthetic"]["recall_at_20"] * section["planted_errors"]
    )
    # Every planted error only one check matches is lost when that check is left out (the
    # checks do not depend on each other).
    for entry in section["per_check"].values():
        assert entry["lost_without"] == entry["only_match"]
        assert entry["gained_without"] == 0
    markdown = render_markdown(report)
    assert "## All checks" in markdown
    assert "### Leave-one-out ablation" in markdown
    assert "--ablation" in markdown
    assert markdown.count(LABEL) >= 3
