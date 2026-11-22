"""Score every check against a bill with hand-planted faults and its answer key (plan step B7).

``python -m app.evaluation --answer-key KEY.json --clean CLEAN_FILE [--bill BILL]``, with any
paths and file names. The key (JSON) names the faulty bill (``file``, next to the key; ``--bill``
overrides it and is needed when the key names none), and lists:

* ``planted`` (required): each fault with ``error_id``, ``rows`` (the 1-based spreadsheet rows
  of the faulty file where reporting it is correct) and ``finding_category`` (optional);
* ``not_planted`` (optional): oddities the original bill already holds (``rows``); a finding
  there is right;
* ``must_not_flag`` (optional): rows that are right and must not be reported (``rows``).

``file_sha256``, when the key has it, is compared with the bill scored and the result reported.

Both files are uploaded with the ``boq`` profile and validated with every registered check, on
in-memory storage in a temporary folder that is deleted afterwards. A finding *hits* a fault
when one of its rows is one of the fault's rows. The
findings are taken in the issue register's order (spelling and text-style findings last,
otherwise severity, then position), which is the order of the register in the app; *found in
the first K* means a hit among the first K findings.

**F2 at 50**, the main score: the F-beta score with beta = 2 of precision at 50 (findings among
the first 50 that hit a fault, over the findings shown there) and recall at 50 (faults found in
the first 50 findings, over the planted faults), as in :mod:`app.evaluation.scoring`. After the
discount, a finding whose hits are all discounted counts as a miss.

**Clean-original discount.** A hit is not credited when the same check and rule also report the
same line of the clean original: a finding of that check and rule on the clean file names a row
with the same identity (the item code of an item or section row; otherwise the row kind and its
text with runs of white space as one space). Rows are compared by identity because the faulty
copy has positions removed, added and moved, so row numbers differ. All counts are given before
and after the discount.

**Must-not-flag hits** count the findings that hit no fault and name a must-not-flag row; those
of them the clean file also reports (same check, rule and line) are counted apart. **Single-check
finds** are faults whose hits (credited hits, after the discount) all come from one check, counted
per check.

The report holds counts and check ids only: no file names, rows, texts or values of the bill, so
it can be quoted. The review-budget baselines of :mod:`app.evaluation.ablation` are computed on
the faulty bill as well (without the discount).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation import ablation
from app.evaluation.boq_report import fmt
from app.evaluation.runner import benchmark_workbench, run_findings
from app.evaluation.scoring import F2_BUDGET, Finding, f2_of
from app.models.dataset import Dataset
from app.services import documents

LABEL = (
    "Hand-planted faults in one real bill: test material, not real-world performance; counts only"
)
BUDGETS: tuple[int, ...] = (20, 50)
Identity = tuple[str, ...]


@dataclass(frozen=True)
class Checked:
    findings: list[Finding]
    identities: dict[int, Identity]  # source row -> identity of its line
    dataset: Dataset | None
    status: str


def _text(value: str | None) -> str:
    return " ".join((value or "").split())


def identities(dataset: Dataset | None) -> dict[int, Identity]:
    """Source row -> the identity of its line: (``code``, item code) when the row has one,
    else (row kind, text)."""
    if dataset is None:
        return {}
    result: dict[int, Identity] = {}
    for table in dataset.tables:
        fields = {
            column.column_id: column.mapping.field_id
            for column in table.columns
            if column.mapping is not None
        }
        for row in table.rows:
            values = {
                fields[column_id]: cell.raw_value
                for column_id, cell in row.cells.items()
                if column_id in fields
            }
            code = _text(values.get("item_code"))
            result[row.source_row_number] = (
                ("code", code)
                if code
                else (row.classification.kind.value, _text(values.get("description")))
            )
    return result


def check_file(path: Path) -> Checked:
    """``path`` uploaded with the ``boq`` profile and validated with every registered check."""
    with tempfile.TemporaryDirectory(prefix="twb-answer-key-") as scratch:
        wb = benchmark_workbench(Path(scratch))
        document, dataset = documents.upload(
            wb, filename=path.name, chunks=[path.read_bytes()], profile_id="boq"
        )
        findings = run_findings(wb, dataset) if dataset else []
        return Checked(
            findings=findings,
            identities=identities(dataset),
            dataset=dataset,
            status=document.processing_status.value,
        )


def _clean_lines(clean: Checked) -> set[tuple[str, str, Identity]]:
    return {
        (f.detector_id, f.rule_id, clean.identities[row])
        for f in clean.findings
        for row in f.rows
        if row in clean.identities
    }


def _also_on_clean(
    finding: Finding,
    rows: frozenset[int],
    faulty: Checked,
    clean_lines: set[tuple[str, str, Identity]],
) -> bool:
    """Every row of ``rows`` the finding names is a line the clean file reports with the same
    check and rule."""
    return all(
        row in faulty.identities
        and (finding.detector_id, finding.rule_id, faulty.identities[row]) in clean_lines
        for row in rows
    )


def _rows(entries: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    return frozenset(int(row) for entry in entries for row in entry["rows"])


def _counts(
    hits: Sequence[set[str]],
    findings: Sequence[Finding],
    faults: Mapping[str, frozenset[int]],
    categories: Mapping[str, str],
) -> dict[str, Any]:
    """The fault counts of one reading of the hits (``hits[i]``: faults finding i hits)."""
    by_fault: dict[str, set[str]] = {fault: set() for fault in faults}
    for finding, hit in zip(findings, hits, strict=True):
        for fault in hit:
            by_fault[fault].add(finding.detector_id)
    found = {fault for fault, checks in by_fault.items() if checks}
    single = Counter(next(iter(checks)) for checks in by_fault.values() if len(checks) == 1)
    per_check: Counter[str] = Counter()
    for checks in by_fault.values():
        per_check.update(checks)
    found_by_category: Counter[str] = Counter(categories[fault] for fault in found)
    first = hits[:F2_BUDGET]
    f2, precision, recall = f2_of(
        sum(1 for hit in first if hit), len(first), len(set().union(*first)), len(faults)
    ) or (None, None, None)
    return {
        "f2_at_50": f2,
        "precision_at_50": precision,
        "recall_at_50": recall,
        "found": len(found),
        **{f"found_in_first_{k}": len(set().union(*hits[:k])) if hits[:k] else 0 for k in BUDGETS},
        "findings_hitting_a_fault": sum(1 for hit in hits if hit),
        "single_check_finds": sum(single.values()),
        "single_check_finds_by_check": dict(sorted(single.items())),
        "faults_matched_by_check": dict(sorted(per_check.items())),
        "found_by_category": {
            category: found_by_category[category] for category in sorted(set(categories.values()))
        },
    }


def score(key: Mapping[str, Any], faulty: Checked, clean: Checked, *, seed: int) -> dict[str, Any]:
    """The answer-key report (counts and check ids only)."""
    faults = {str(p["error_id"]): frozenset(int(r) for r in p["rows"]) for p in key["planted"]}
    categories = {
        str(p["error_id"]): str(p.get("finding_category", "none")) for p in key["planted"]
    }
    must_not_flag = _rows(key.get("must_not_flag", []))
    original = _rows(key.get("not_planted", []))
    clean_lines = _clean_lines(clean)
    findings = faulty.findings
    raw: list[set[str]] = []
    credited: list[set[str]] = []
    for finding in findings:
        hit = {fault for fault, rows in faults.items() if not finding.rows.isdisjoint(rows)}
        raw.append(hit)
        credited.append(
            {
                fault
                for fault in hit
                if not _also_on_clean(finding, finding.rows & faults[fault], faulty, clean_lines)
            }
        )
    misses = [f for f, hit in zip(findings, raw, strict=True) if not hit]
    on_mnf = [f for f in misses if not f.rows.isdisjoint(must_not_flag)]
    planted_rows = frozenset().union(*faults.values()) if faults else frozenset()
    orders = ablation.reading_orders(
        [f.rows for f in findings], faulty.dataset, seed=f"{seed}:answer-key"
    )
    by_category = Counter(categories.values())
    return {
        "label": LABEL,
        "seed": seed,
        "faulty_file_matches_key": None,
        "upload_status": {"faulty": faulty.status, "clean": clean.status},
        "planted": len(faults),
        "planted_by_category": dict(sorted(by_category.items())),
        "findings": len(findings),
        "findings_on_clean_file": len(clean.findings),
        "findings_by_check": dict(sorted(Counter(f.detector_id for f in findings).items())),
        "findings_on_clean_file_by_check": dict(
            sorted(Counter(f.detector_id for f in clean.findings).items())
        ),
        "before_discount": _counts(raw, findings, faults, categories),
        "after_discount": _counts(credited, findings, faults, categories),
        "must_not_flag_hits": len(on_mnf),
        "must_not_flag_hits_also_on_clean_file": sum(
            1 for f in on_mnf if _also_on_clean(f, f.rows & must_not_flag, faulty, clean_lines)
        ),
        "must_not_flag_hits_by_check": dict(sorted(Counter(f.detector_id for f in on_mnf).items())),
        "findings_on_original_oddities": sum(1 for f in misses if not f.rows.isdisjoint(original)),
        "findings_on_no_listed_row": sum(
            1
            for f in misses
            if f.rows.isdisjoint(must_not_flag) and f.rows.isdisjoint(original | planted_rows)
        ),
        "review_budget": ablation.budget_counts(orders, faults, len(findings)),
        "review_budget_f2_at_50": {
            name: None if score is None else score[0]
            for name, score in ablation.budget_at_50(orders, faults).items()
        },
    }


def run_answer_key(
    key_path: Path, *, clean_path: Path, bill_path: Path | None, out_dir: Path, seed: int
) -> dict[str, Any]:
    """Score the bill against the key at ``key_path`` (any paths and file names). ``bill_path``
    defaults to the key's ``file``, next to the key. Raises ValueError when the key lists no
    ``planted`` faults or names no bill and ``bill_path`` is None."""
    key = json.loads(key_path.read_text(encoding="utf-8"))
    if not isinstance(key, dict) or not isinstance(key.get("planted"), list):
        raise ValueError("the answer key needs a 'planted' list")
    if bill_path is None and not key.get("file"):
        raise ValueError("the answer key names no 'file'; give the bill with --bill")
    bill = bill_path if bill_path is not None else key_path.parent / str(key["file"])
    faulty = check_file(bill)
    clean = check_file(clean_path)
    report = score(key, faulty, clean, seed=seed)
    expected = key.get("file_sha256")
    if expected:
        report["faulty_file_matches_key"] = (
            hashlib.sha256(bill.read_bytes()).hexdigest() == expected
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "answer-key-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "answer-key-report.md").write_text(render(report), encoding="utf-8")
    return report


def _checks(counts: Mapping[str, int]) -> str:
    return ", ".join(f"`{check}` {n}" for check, n in counts.items()) or "none"


def render(report: Mapping[str, Any]) -> str:
    before, after = report["before_discount"], report["after_discount"]
    rows = [
        ("**F2 at 50 (main score)**", "f2_at_50"),
        ("Precision at 50", "precision_at_50"),
        ("Recall at 50", "recall_at_50"),
        ("Faults found", "found"),
        ("Found in the first 20 findings", "found_in_first_20"),
        ("Found in the first 50 findings", "found_in_first_50"),
        ("Findings that hit a fault", "findings_hitting_a_fault"),
        ("Faults only one check finds", "single_check_finds"),
    ]
    budget = report["review_budget"]
    labels = ablation.budget_labels()
    lines = [
        "# Answer-key score",
        "",
        f"{report['label']}.",
        "",
        f"{report['planted']} planted faults; every registered check runs. Findings: "
        f"{report['findings']} on the faulty bill, {report['findings_on_clean_file']} on the "
        "clean original. Order: the issue register's (spelling and text-style findings last, "
        "otherwise severity, then position). Faulty file "
        f"matches the key's checksum: {fmt(report['faulty_file_matches_key'])}.",
        "",
        "| Metric | Before discount | After clean-original discount |",
        "| --- | --- | --- |",
        *(f"| {label} | {fmt(before[name])} | {fmt(after[name])} |" for label, name in rows),
        f"| Must-not-flag hits (findings) | {report['must_not_flag_hits']} | "
        f"{report['must_not_flag_hits'] - report['must_not_flag_hits_also_on_clean_file']} "
        "not also on the clean original |",
        "",
        f"Findings on oddities of the original: {report['findings_on_original_oddities']}; on "
        f"no row the key lists: {report['findings_on_no_listed_row']}.",
        "",
        "| Category | Planted | Found before discount | Found after discount |",
        "| --- | --- | --- | --- |",
        *(
            f"| {category} | {planted} | {before['found_by_category'].get(category, 0)} | "
            f"{after['found_by_category'].get(category, 0)} |"
            for category, planted in report["planted_by_category"].items()
        ),
        "",
        f"Single-check finds by check, after discount: "
        f"{_checks(after['single_check_finds_by_check'])}; before: "
        f"{_checks(before['single_check_finds_by_check'])}.",
        "",
        f"Faults matched per check, after discount: {_checks(after['faults_matched_by_check'])}.",
        "",
        f"Must-not-flag hits by check: {_checks(report['must_not_flag_hits_by_check'])}.",
        "",
        f"Findings by check (faulty bill): {_checks(report['findings_by_check'])}.",
        "",
        "Findings by check (clean original): "
        f"{_checks(report['findings_on_clean_file_by_check'])}.",
        "",
        "## Review budget (before discount)",
        "",
        "| Reading list | F2 at 50 | "
        + " | ".join(
            f"K = {label}" if label != ablation.FINDINGS_BUDGET else "K = our findings"
            for label in labels
        )
        + " |",
        "| --- | --- | " + " | ".join("---" for _ in labels) + " |",
        *(
            f"| {ablation.STRATEGY_LABELS[name]} | "
            f"{fmt(report['review_budget_f2_at_50'][name])} | "
            + " | ".join(str(counts[label]) for label in labels)
            + " |"
            for name, counts in budget.items()
        ),
        "",
    ]
    return "\n".join(lines)
