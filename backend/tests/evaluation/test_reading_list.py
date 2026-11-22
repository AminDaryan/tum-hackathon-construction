"""The default reading list: proven checks, the other checks by their rule's measured hit rate,
then the model's high-certainty claims; the rest only worth a look."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.bill_review import Issue, PartResult, Review, rank
from app.evaluation import reading_list as rl
from app.evaluation.llm_review import model_findings
from app.evaluation.scoring import Finding


def _check(issue_id: str, rule: str, *rows: int) -> Finding:
    return Finding(issue_id, "domain.x", rule, "low", issue_id, frozenset(rows), frozenset())


def _claim(oz: str, row: int, certainty: str) -> Issue:
    return Issue(
        part=1,
        oz=oz,
        row_numbers=(row,),
        issue_type="018",
        issue_name="Decimal point error",
        category=None,
        quote="2650",
        grounded=True,
        why="Quantity one digit short.",
        related_oz=(),
        certainty=certainty,
    )


def test_rule_key_is_the_one_key_of_counting_and_looking_up() -> None:
    finding = _check("a", "spec_conflict", 4)
    assert rl.rule_key(finding) == "domain.x:spec_conflict"
    counts = rl.count_rules([[4], [9]], [finding, _check("b", "spec_conflict", 5)])
    assert counts == {"domain.x:spec_conflict": (2, 1)}


def test_the_list_orders_checks_by_rate_and_keeps_only_high_claims() -> None:
    checks = [
        _check("proven", "line_total", 4),
        _check("weak", "repeated_word", 5),
        _check("unknown", "new_rule", 6),
        _check("strong", "spec_conflict", 7),
        _check("again", "spec_conflict", 7),  # same rows as an earlier entry: left out
    ]
    counts = {"domain.x:spec_conflict": (10, 8), "domain.x:repeated_word": (8, 0)}
    part = PartResult(part=1, section="01", positions=[], prompt_chars=10, seconds=1.0)
    part.issues = [
        _claim("01.01.0001", 8, "high"),
        _claim("01.01.0002", 9, "medium"),
        _claim("01.01.0003", 7, "high"),  # rows already named by a check
    ]
    suggestions = rank(Review("v", "bill", [part], 0))
    model = model_findings(suggestions)
    made = rl.reading_list(checks, {"proven"}, model, suggestions, counts)
    assert [sorted(f.rows) for f in made.findings] == [[4], [7], [8]]
    assert made.stage_of == ["proven", "measured", "model"]
    # a weak rule, a rule without a rate and a claim of certainty medium
    assert sorted(sorted(f.rows) for f in made.worth_a_look) == [[5], [6], [9]]


def test_held_out_counts_leave_out_every_variant_of_the_same_bill() -> None:
    by_bill = {"A1": {"k": (2, 2)}, "A2": {"k": (2, 2)}, "B1": {"k": (4, 0)}}
    group = {"A1": "A", "A2": "A", "B1": "B"}
    assert rl.held_out_counts(by_bill, group, "A1") == {"k": (4, 0)}
    assert rl.held_out_counts(by_bill, group, "B1") == {"k": (4, 4)}


def test_the_committed_table_is_counts_only_and_readable(tmp_path: Path) -> None:
    table = json.loads(rl.RATES_FILE.read_text(encoding="utf-8"))
    assert table["rules"] and all(set(r) == {"key", "findings", "hits"} for r in table["rules"])
    assert all(0 <= r["hits"] <= r["findings"] for r in table["rules"])
    copy = tmp_path / "rates.json"
    copy.write_text(json.dumps(replace_rules(table)), encoding="utf-8")
    assert rl.load_counts(copy) == {"domain.x:spec_conflict": (3, 2)}
    assert rl.load_counts(tmp_path / "missing.json") == {}


def replace_rules(table: dict[str, object]) -> dict[str, object]:
    return {**table, "rules": [{"key": "domain.x:spec_conflict", "findings": 3, "hits": 2}]}


def test_the_ablation_switches_change_one_part_of_the_list_each() -> None:
    checks = [
        _check("weak", "repeated_word", 5),
        _check("unknown", "new_rule", 6),
        _check("strong", "spec_conflict", 7),
        _check("again", "spec_conflict", 7),
    ]
    counts = {"domain.x:spec_conflict": (10, 8), "domain.x:repeated_word": (8, 0)}
    part = PartResult(part=1, section="01", positions=[], prompt_chars=10, seconds=1.0)
    part.issues = [_claim("01.01.0001", 8, "high"), _claim("01.01.0002", 9, "medium")]
    suggestions = rank(Review("v", "bill", [part], 0))
    model = model_findings(suggestions)

    def rows(**switches: object) -> list[list[int]]:
        made = rl.reading_list(checks, set(), model, suggestions, counts, **switches)  # type: ignore[arg-type]
        return [sorted(f.rows) for f in made.findings]

    assert rows() == [[7], [8]]
    assert rows(cut=0.0) == [[7], [5], [8]]  # a rule without a rate is still only worth a look
    assert rows(keep_unmeasured=True) == [[7], [6], [8]]
    assert rows(certain_only=False) == [[7], [8], [9]]
    assert rows(skip_covered=False) == [[7], [7], [8]]
    assert rows(key=lambda f: f.rule_id) == [[8]]  # no rate under that key
    assert rl.plain_key(checks[0]) == "domain.x:repeated_word"
