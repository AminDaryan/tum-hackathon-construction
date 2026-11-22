"""The default reading list of the sandwich review: the measured design without the judge.

Order:

1. proven check findings (an arithmetic or a required value the checks prove);
2. the other check findings, by how often their check and rule hit a planted fault on labelled
   bills (:data:`RATES_FILE`); a rule below :data:`CUT`, or a rule the table does not know,
   goes to "worth a look" (unknown rules scored higher there in every whole-bill run of P1);
3. the model's claims of certainty high; claims of certainty medium or low go to "worth a look".

A finding whose rows are all named by earlier entries is left out. "Worth a look" is a separate
output, never part of the ranked list.

The rates table is counts only (check, rule, findings, hits), measured on the P1 practice
benchmark by::

    python -m app.evaluation.reading_list --measure "Sample BoQ Dataset/Practice Benchmark P1"

When P1 itself is scored, the rates must not come from that table (it has seen every bill):
:func:`held_out_counts` leaves out every variant of the bill being scored.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.bill_review import Suggestion
from app.evaluation.evidence_bands import finding_band, with_band
from app.evaluation.scoring import Finding

RATES_FILE = Path(__file__).with_name("rule_hit_rates.json")
CUT = 0.14  # a rule that hits a planted fault less often than this is only worth a look

Counts = dict[str, tuple[int, int]]  # rule_key -> (findings, findings on a planted fault)


@dataclass(frozen=True, slots=True)
class ReadingList:
    findings: list[Finding]  # the ranked list
    stage_of: list[str]  # proven, measured, unmeasured or model, per entry
    worth_a_look: list[Finding]  # rules below the cut and claims of certainty medium or low


def rule_key(finding: Finding) -> str:
    """The key a finding's hit rate is counted and looked up under, here and in the held-out
    scoring: the check and its rule, and for the two price checks how far the price is off
    (:func:`~app.evaluation.evidence_bands.finding_band`). The one place to change what a rate
    is measured for."""
    return with_band(f"{finding.detector_id}:{finding.rule_id}", finding_band(finding))


def plain_key(finding: Finding) -> str:
    """The check and its rule only, without a band (for the ablation of the bands)."""
    return f"{finding.detector_id}:{finding.rule_id}"


def count_rules(
    planted_rows: Iterable[Iterable[int]],
    findings: Iterable[Finding],
    key: Callable[[Finding], str] | None = None,
) -> Counts:
    """Findings and hits per check and rule on one labelled bill (pass the unproven ones: proven
    findings are listed first whatever their rule's rate). ``key`` defaults to :func:`rule_key`."""
    key = key or rule_key
    faults = [set(rows) for rows in planted_rows]
    counts: dict[str, list[int]] = {}
    for finding in findings:
        entry = counts.setdefault(key(finding), [0, 0])
        entry[0] += 1
        entry[1] += any(finding.rows & rows for rows in faults)
    return {rule: (n, hits) for rule, (n, hits) in counts.items()}


def add(counts: Iterable[Counts]) -> Counts:
    total: dict[str, list[int]] = {}
    for one in counts:
        for rule, (n, hits) in one.items():
            entry = total.setdefault(rule, [0, 0])
            entry[0] += n
            entry[1] += hits
    return {rule: (n, hits) for rule, (n, hits) in sorted(total.items())}


def held_out_counts(by_bill: Mapping[str, Counts], group: Mapping[str, str], bill: str) -> Counts:
    """The counts of every labelled bill except those of ``bill``'s group (the variants of the
    same base bill), for scoring ``bill`` honestly."""
    return add(c for name, c in by_bill.items() if group[name] != group[bill])


def load_counts(path: Path = RATES_FILE) -> Counts:
    if not path.exists():
        return {}
    table = json.loads(path.read_text(encoding="utf-8"))
    return {r["key"]: (r["findings"], r["hits"]) for r in table["rules"]}


def reading_list(
    checks: Sequence[Finding],
    proven: Iterable[str],
    model: Sequence[Finding],
    suggestions: Sequence[Suggestion],
    counts: Counts,
    cut: float = CUT,
    *,
    key: Callable[[Finding], str] | None = None,
    keep_unmeasured: bool = False,
    certain_only: bool = True,
    skip_covered: bool = True,
) -> ReadingList:
    """The default list (see the module text). ``model`` are the model's suggestions as
    findings, in the same order as ``suggestions``. The keyword switches exist for the ablation
    (:mod:`app.evaluation.review_ablation`); their defaults are the default list: rates looked
    up by :func:`rule_key`, rules without a rate only worth a look, only claims of certainty
    high listed, and a finding left out when earlier entries name all its rows."""
    key = key or rule_key
    sure = set(proven)
    rate = {rule: hits / n for rule, (n, hits) in counts.items() if n}
    first = [f for f in checks if f.issue_id in sure]
    soft = [f for f in checks if f.issue_id not in sure]
    measured = sorted(
        (f for f in soft if key(f) in rate and rate[key(f)] >= cut),
        key=lambda f: -rate[key(f)],
    )
    unmeasured = [f for f in soft if key(f) not in rate]
    below = [f for f in soft if key(f) in rate and rate[key(f)] < cut]
    if not keep_unmeasured:
        below, unmeasured = [*below, *unmeasured], []
    pairs = list(zip(model, suggestions, strict=True))
    high = [f for f, s in pairs if s.certainty == "high" or not certain_only]
    weak = [f for f, s in pairs if s.certainty != "high" and certain_only]
    listed: list[Finding] = []
    stage_of: list[str] = []
    named: set[int] = set()
    for stage, findings in (
        ("proven", first),
        ("measured", measured),
        ("unmeasured", unmeasured),
        ("model", high),
    ):
        for finding in findings:
            if skip_covered and finding.rows and finding.rows <= named:
                continue
            listed.append(finding)
            stage_of.append(stage)
            named |= finding.rows
    return ReadingList(listed, stage_of, [*below, *weak])


def measure(folder: Path) -> dict[str, Any]:
    """The rates table from the answer keys of a practice benchmark (``folder/out``) and the
    app's checks on its faulty bills. Counts only: no bill texts, rows or file names."""
    from app.evaluation.llm_review import load_checked  # the app's checks, as the review runs them

    per_bill = []
    for key_path in sorted((folder / "out").glob("*-answer-key.json")):
        key = json.loads(key_path.read_text(encoding="utf-8"))
        _, checked, proven = load_checked(key_path.parent / str(key["file"]))
        unproven = [f for f in checked.findings if f.issue_id not in proven]
        per_bill.append(count_rules((f["rows"] for f in key["planted"]), unproven))
    total = add(per_bill)
    return {
        "measured_on": folder.name,
        "bills": len(per_bill),
        "note": "Unproven findings of each check and rule on the faulty bills, and how many name "
        "a row of a planted fault. Counts only. Never use this table to score the bills it "
        "was measured on.",
        "rules": [{"key": key, "findings": n, "hits": h} for key, (n, h) in total.items()],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--measure", type=Path, required=True, help="a practice benchmark folder")
    parser.add_argument("--out", type=Path, default=RATES_FILE)
    args = parser.parse_args(argv)
    table = measure(args.measure)
    args.out.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")
    print(f"{len(table['rules'])} rules from {table['bills']} bills: {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
