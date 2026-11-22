"""The ablation of the default list: one part of the design left out per variant."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.bill_review import Issue, PartResult, Review, rank
from app.evaluation import review_ablation as ra
from app.evaluation.answer_key import Checked
from app.evaluation.scoring import Finding


def _check(issue_id: str, rule: str, *rows: int) -> Finding:
    return Finding(issue_id, "domain.x", rule, "low", issue_id, frozenset(rows), frozenset())


def _part(focus: str, oz: str, row: int, certainty: str) -> PartResult:
    part = PartResult(part=1, section="01", positions=[], prompt_chars=10, seconds=1.0)
    part.focus = focus
    part.issues = [
        Issue(
            part=1,
            oz=oz,
            row_numbers=(row,),
            issue_type="051",
            issue_name="Text contradiction",
            category=None,
            quote="DN50",
            grounded=True,
            why="Short and long text name different diameters.",
            related_oz=(),
            certainty=certainty,
        )
    ]
    return part


def _bill(*parts: PartResult) -> ra.Bill:
    review = Review("v", "bill", list(parts), 0)
    checked = Checked(
        findings=[_check("proven", "line_total", 4), _check("noise", "repeated_word", 5)],
        identities={},
        dataset=None,
        status="processed",
    )
    return ra.Bill(checked, frozenset({"proven"}), review, rank(review))


def test_each_variant_leaves_one_part_of_the_design_out() -> None:
    bill = _bill(_part("text", "01.0001", 8, "high"), _part("basis", "01.0002", 9, "high"))
    counts = {"domain.x:repeated_word": (10, 0)}
    variant = {v.name: v for v in ra.VARIANTS}

    def rows(name: str) -> list[list[int]]:
        return [sorted(f.rows) for f in ra.built(variant[name], bill, counts)]

    assert rows("default") == [[4], [8], [9]]  # the weak rule is only worth a look
    assert rows("no_model") == [[4]]
    assert rows("no_checks") == [[8], [9]]
    assert rows("no_rates") == [[4], [5], [8], [9]]
    assert rows("no_text") == [[4], [9]]  # the claims of the other passes, ranked again
    assert rows("no_basis") == [[4], [8]]


def test_the_runs_are_put_side_by_side(tmp_path: Path) -> None:
    run = tmp_path / "per-row"
    run.mkdir()
    entry = {
        "label": "x",
        "f2_at_50": 0.5,
        "after_discount": 0.4,
        "found_in_first_50": 10,
        "planted": 22,
        "findings": 30,
        "findings_on_clean_bills": 7,
        "must_not_flag_hits": 1,
        "by_bill": {},
    }
    ablation = {
        "bills": ["b"],
        "variants": {"default": entry, "no_model": {**entry, "f2_at_50": 0.3}},
    }
    (run / ra.FILE).write_text(json.dumps(ablation), encoding="utf-8")
    practice = {"model": "m", "whole_bill": False, "settings": {"part_size": 1, "passes": "text"}}
    (run / "practice.json").write_text(json.dumps(practice), encoding="utf-8")
    table = ra.compare([run])
    assert "| per-row | m | at most 1 positions | text | yes | 0.5000 |" in table
    assert table.rstrip().endswith("| 0.3000 |")
    assert "| The default list |" not in ra.render(ablation)  # labels come from the run
    assert "| x | 0.5000 | +0.0000 |" in ra.render(ablation)
