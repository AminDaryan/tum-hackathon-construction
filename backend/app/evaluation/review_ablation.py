"""Ablation of the model review's default reading list: each part of the design left out once.

The default list (:mod:`app.evaluation.reading_list`) is built again from the answers of one
practice run, once per :data:`VARIANTS` entry, with one part of the design left out or changed.
Every variant is scored like the default: rule hit rates measured on the other base bills only
(both variants of the scored bill left out), the shared answer-key scorer, F2 at 50 averaged
over the faulty bills, and the same list built for the clean original.

A variant that leaves a pass out re-ranks the model's claims of the other passes. Nothing else
is asked again, so every variant reads the same answers: the differences come from the design,
not from a second sample of the model.

What the model is asked (the whole bill or parts, one position per request, the checks'
findings in the prompt) cannot be changed after a run; those need runs of their own, and
``python -m app.evaluation.review_ablation RUN_DIR ...`` puts the default list of several runs
(their ``ablation.json``) side by side.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.agents.bill_review import Review, Suggestion, rank
from app.evaluation import answer_key
from app.evaluation.answer_key import Checked
from app.evaluation.reading_list import (
    CUT,
    count_rules,
    held_out_counts,
    plain_key,
    reading_list,
    rule_key,
)
from app.evaluation.scoring import Finding

FILE = "ablation.json"


@dataclass(frozen=True, slots=True)
class Bill:
    """One bill as the run read it: the checks' findings, the proven ones among them, the
    model's answers (``review``) and its claims merged by position (``suggestions``)."""

    checked: Checked
    proven: frozenset[str]
    review: Review
    suggestions: list[Suggestion]


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    label: str
    model: bool = True  # the model's claims on the list
    checks: bool = True  # the checks' findings on the list
    rates: bool = True  # checks ordered and cut by their rule's measured hit rate
    cut: float = CUT
    bands: bool = True  # the size bands of the two price checks in the rule key
    keep_unmeasured: bool = False
    certain_only: bool = True
    skip_covered: bool = True
    left_out: str | None = None  # a pass whose answers are left out


VARIANTS: tuple[Variant, ...] = (
    Variant("default", "The default list"),
    Variant("no_model", "Without the model's claims (checks only)", model=False),
    Variant("no_checks", "Without the checks' findings (the model's claims only)", checks=False),
    Variant(
        "no_rates",
        "Without the measured hit rates (checks in register order, none left out)",
        rates=False,
        keep_unmeasured=True,
    ),
    Variant(
        "no_cut",
        "Without the cut at 0.14 (checks ranked, none left out)",
        cut=0.0,
        keep_unmeasured=True,
    ),
    Variant("no_bands", "Without the size bands of the two price checks", bands=False),
    Variant(
        "unmeasured_in",
        "Rules without a measured rate kept after the measured ones",
        keep_unmeasured=True,
    ),
    Variant("all_claims", "Every model claim, not only certainty high", certain_only=False),
    Variant(
        "keep_covered", "A finding kept when earlier entries name all its rows", skip_covered=False
    ),
    Variant("no_numbers", "Without the pass numbers", left_out="numbers"),
    Variant("no_basis", "Without the pass price basis", left_out="basis"),
    Variant("no_text", "Without the pass text", left_out="text"),
)


def built(variant: Variant, bill: Bill, counts: Mapping[str, tuple[int, int]]) -> list[Finding]:
    """The reading list of one bill in one variant."""
    from app.evaluation.llm_review import model_findings  # llm_review imports this module

    suggestions = bill.suggestions
    if variant.left_out is not None:
        parts = [p for p in bill.review.parts if p.focus != variant.left_out]
        suggestions = rank(replace(bill.review, parts=parts))
    if not variant.model:
        suggestions = []
    return reading_list(
        bill.checked.findings if variant.checks else [],
        bill.proven if variant.checks else frozenset(),
        model_findings(suggestions),
        suggestions,
        dict(counts) if variant.rates else {},
        variant.cut,
        key=rule_key if variant.bands else plain_key,
        keep_unmeasured=variant.keep_unmeasured,
        certain_only=variant.certain_only,
        skip_covered=variant.skip_covered,
    ).findings


def ablate(
    keys: Mapping[str, dict[str, Any]],
    checks: Mapping[str, tuple[Checked, frozenset[str]]],
    bills: Mapping[str, Bill],
    clean_of: Mapping[str, str],
    *,
    seed: int,
) -> dict[str, Any]:
    """Score every variant on the faulty bills in ``keys`` that were reviewed with their clean
    original (both in ``bills``). ``checks`` holds the checks of every faulty bill of the
    benchmark, reviewed or not: the held-out rates are counted on them."""
    scored = [stem for stem in keys if stem in bills and clean_of[stem] in bills]
    result: dict[str, Any] = {"bills": scored, "variants": {}}
    for variant in VARIANTS:
        key = rule_key if variant.bands else plain_key
        by_bill = {
            stem: count_rules(
                (f["rows"] for f in keys[stem]["planted"]),
                (f for f in checked.findings if f.issue_id not in proven),
                key,
            )
            for stem, (checked, proven) in checks.items()
            if stem in keys
        }
        rows: dict[str, dict[str, Any]] = {}
        on_clean: dict[str, int] = {}
        for stem in scored:
            counts = held_out_counts(by_bill, clean_of, stem)
            mine = built(variant, bills[stem], counts)
            theirs = built(variant, bills[clean_of[stem]], counts)
            on_clean[clean_of[stem]] = len(theirs)
            s = answer_key.score(
                keys[stem],
                replace(bills[stem].checked, findings=mine),
                replace(bills[clean_of[stem]].checked, findings=theirs),
                seed=seed,
            )
            rows[stem] = {
                "f2_at_50": s["before_discount"]["f2_at_50"] or 0.0,
                "after_discount": s["after_discount"]["f2_at_50"] or 0.0,
                "found_in_first_50": s["before_discount"]["found_in_first_50"],
                "findings": s["findings"],
                "must_not_flag_hits": s["must_not_flag_hits"],
            }
        result["variants"][variant.name] = {
            "label": variant.label,
            "f2_at_50": statistics.mean(r["f2_at_50"] for r in rows.values()) if rows else None,
            "after_discount": (
                statistics.mean(r["after_discount"] for r in rows.values()) if rows else None
            ),
            "found_in_first_50": sum(r["found_in_first_50"] for r in rows.values()),
            "planted": sum(len(keys[stem]["planted"]) for stem in scored),
            "findings": sum(r["findings"] for r in rows.values()),
            "findings_on_clean_bills": sum(on_clean.values()),
            "must_not_flag_hits": sum(r["must_not_flag_hits"] for r in rows.values()),
            "by_bill": {stem: round(r["f2_at_50"], 4) for stem, r in rows.items()},
        }
    return result


def render(result: Mapping[str, Any], title: str = "Ablation of the default list") -> str:
    variants = result["variants"]
    base = variants["default"]["f2_at_50"] or 0.0
    lines = [
        f"# {title}",
        "",
        f"{len(result['bills'])} faulty bills. Every variant reads the same answers of this run "
        "and leaves one part of the design out; rule rates are measured on the other base bills "
        "only. F2@50 is the mean over the faulty bills.",
        "",
        "| Variant | F2@50 | Change | After clean discount | Faults in first 50 | "
        "Findings on faulty bills | On clean bills | Must-not-flag hits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for v in variants.values():
        f2 = v["f2_at_50"] or 0.0
        lines.append(
            f"| {v['label']} | {f2:.4f} | {f2 - base:+.4f} | {v['after_discount'] or 0.0:.4f} | "
            f"{v['found_in_first_50']} of {v['planted']} | {v['findings']} | "
            f"{v['findings_on_clean_bills']} | {v['must_not_flag_hits']} |"
        )
    return "\n".join(lines) + "\n"


def compare(runs: Sequence[Path]) -> str:
    """The default list and the checks alone of several runs, with the settings of each run
    (from its ``practice.json``), for the parts of the design a run fixes."""
    lines = [
        "| Run | Model | Parts | Passes | Checks in the prompt | Default list F2@50 | "
        "After clean discount | Faults in first 50 | Findings | On clean bills | Checks only |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in runs:
        ablation = json.loads((run / FILE).read_text(encoding="utf-8"))
        practice = json.loads((run / "practice.json").read_text(encoding="utf-8"))
        settings = practice.get("settings", {})
        parts = (
            "whole bill"
            if practice.get("whole_bill")
            else f"at most {settings.get('part_size', '?')} positions"
        )
        d = ablation["variants"]["default"]
        c = ablation["variants"]["no_model"]
        lines.append(
            f"| {run.name} | {practice.get('model')} | {parts} | {settings.get('passes', '?')} | "
            f"{'no' if settings.get('no_checks') else 'yes'} | {d['f2_at_50']:.4f} | "
            f"{d['after_discount']:.4f} | {d['found_in_first_50']} of {d['planted']} | "
            f"{d['findings']} | {d['findings_on_clean_bills']} | {c['f2_at_50']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("runs", nargs="+", type=Path, help="output folders of practice runs")
    args = parser.parse_args(argv)
    print(compare(args.runs), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
