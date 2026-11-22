"""The report of the ``boq`` variant: recall per kind and per check, and signals on unplanted rows.

* **Per kind**: the planted errors, the check expected to find them (from
  :mod:`app.evaluation.expectations`), and how many it found (recall = planted errors with a
  matching finding of that check, with one of its expected rules when the plan names them) and
  highlighted in the wrong cell (localization = those of them whose wrong cell the check's
  finding highlights). A kind none of whose expected checks is available in this run shows
  "check not available yet", not a recall of 0. Every run plans every registered check, so a
  check is not available only when it is not built yet, or when the profile's defaults lack a
  setting the check needs (``Check.setting``).
* **Per check and kind**: for every check that matched a planted error, the share of that
  kind's errors it flagged and localized, whether or not it is the expected check.
* **Rule findings and signals on unplanted rows**, counted apart. A finding of a rule check
  (deterministic or domain detectors) on a row where nothing was planted is a false positive. A
  finding of a signal check (statistical, machine-learning, semantic or research detectors)
  there is not called one, because a generated bill can hold a genuinely odd price by chance:
  it is counted per check per 1,000 item rows, and the ten strongest are listed for inspection
  (ordered by severity, then the magnitude of the detector's raw score, then the amount at
  stake, then document order; the score is used for ordering only and never shown).
* **Risk notes**: a list of the bill's contingency and hourly positions that names only such
  positions of the generated bill is a correct note, counted on its own line and not as a
  false positive (:mod:`app.evaluation.scoring`).
* **Findings per planted error**: matching findings divided by planted errors.
* **Per finding category**: each kind counts under the category its expected check gives its
  findings (``EXPECTED_CATEGORY``; "Reading the file" for none), in the order of the risk
  report. The kinds with an available expected check are measured: their planted errors, and
  those found with that category (a matching finding of any check carries it). The planted
  errors of the other kinds are counted apart, as "check not available yet", so a category's
  count is never read as a detection rate of checks this run cannot measure.

Every number carries :data:`LABEL`. Ratios are over this generated set, not probabilities.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.evaluation.expectations import ANOMALY_TYPE, EXPECTED_CATEGORY, EXPECTED_CHECKS, Check
from app.evaluation.scoring import (
    RISK_NOTES_LINE,
    DocumentResult,
    ErrorOutcome,
    Finding,
    risk_notes_text,
)
from app.evaluation.synthetic import ErrorKind
from app.models.finding_category import (
    FINDING_CATEGORY_ORDER,
    FindingCategory,
    FindingCategoryKey,
)
from app.models.issue import SEVERITY_RANK, Severity

LABEL = "Synthetic benchmark: measured on generated data, not real-world performance"
NOT_AVAILABLE = "check not available yet"
NO_SIGNAL_CHECK = "No signal check is registered."
STRONGEST = 10
LISTED = 30
# The finding categories in the order of the risk report, findings about reading the file last.
CATEGORY_KEYS: tuple[str, ...] = (
    *(category.value for category in FINDING_CATEGORY_ORDER),
    FindingCategoryKey.NONE.value,
)
CATEGORY_LABELS: dict[str, str] = {
    "error": "Error",
    "inconsistency": "Inconsistency",
    "omission": "Omission",
    "ambiguity": "Ambiguity",
    "risk": "Risk",
    "change_order_opportunity": "Change order opportunity",
    "none": "Reading the file",
}


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _per_thousand(count: int, rows: int) -> float | None:
    return 1000 * count / rows if rows else None


def _found(outcome: ErrorOutcome, checks: Sequence[Check]) -> tuple[bool, bool]:
    """(found by an expected check, localized by it)."""
    hits = [
        hit
        for hit in outcome.checks
        for check in checks
        if any(check.matches(hit.detector_id, rule) for rule in hit.rule_ids)
    ]
    return bool(hits), any(hit.localized for hit in hits)


def _category_key(category: FindingCategory | None) -> str:
    return FindingCategoryKey(category or FindingCategoryKey.NONE).value


def _strongest_first(item: tuple[int, str, Finding]) -> tuple[int, float, Decimal, int]:
    order, _, finding = item
    return (
        -SEVERITY_RANK[Severity(finding.severity)],
        -(finding.score or 0.0),
        -(finding.impact or Decimal(0)),
        order,
    )


def build(
    results: Sequence[DocumentResult],
    kinds: Sequence[ErrorKind],
    *,
    registered: Collection[str],
    signal_checks: Collection[str],
    defaults: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The boq sections of the report (``registered``: the checks the run plans, every
    registered one; ``signal_checks``: those of them that only signal; ``defaults``: the
    profile's detector settings)."""
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in kinds:
        checks = EXPECTED_CHECKS[kind]
        available = [check for check in checks if check.available(registered, defaults)]
        by_kind[kind.value] = {
            "anomaly_type": ANOMALY_TYPE[kind],
            "planted": 0,
            "expected_checks": [
                {
                    "detector_id": check.detector_id,
                    "rule_ids": list(check.rule_ids),
                    "step": check.step,
                    "available": check in available,
                }
                for check in checks
            ],
            "status": "measured" if available else NOT_AVAILABLE,
            "found_by_expected_check": 0,
            "localized_by_expected_check": 0,
            "found_by_any_check": 0,
            "findings": 0,
            "by_check": {},
        }
    # Per category: all its kinds and their planted errors; the kinds with an available expected
    # check ("measured": planted, and found with the category); the others ("not_available").
    by_category: dict[str, dict[str, Any]] = {
        key: {
            "kinds": [],
            "planted": 0,
            "measured": {"kinds": [], "planted": 0, "found": 0},
            "not_available": {"kinds": [], "planted": 0},
        }
        for key in CATEGORY_KEYS
    }
    for kind in kinds:
        category = by_category[_category_key(EXPECTED_CATEGORY[kind])]
        category["kinds"].append(kind.value)
        group = "measured" if by_kind[kind.value]["status"] == "measured" else "not_available"
        category[group]["kinds"].append(kind.value)
    rows = item_rows = rule_findings = signal_findings = 0
    bills: Counter[str] = Counter()
    missed: list[dict[str, Any]] = []
    rule_unplanted: list[tuple[str, Finding]] = []
    signals: list[tuple[int, str, Finding]] = []
    signal_counts: Counter[str] = Counter()
    for order, result in enumerate(results):
        doc = result.document
        bills["bills"] += 1
        bills["english"] += doc.language == "en"
        for name in ("buildings", "keys", "components", "type_column", "type_names"):
            bills[name] += bool(doc.features.get(name))
        rows += doc.data_rows
        item_rows += sum(1 for kind in doc.row_kinds.values() if kind == "item")
        for outcome in result.score.outcomes:
            entry = by_kind[outcome.truth.kind.value]
            checks = EXPECTED_CHECKS[outcome.truth.kind]
            available = [c for c in checks if c.available(registered, defaults)]
            found, localized = _found(outcome, available)
            entry["planted"] += 1
            if available and not found:
                missed.append(
                    {
                        "document": doc.name,
                        "error_id": outcome.truth.error_id,
                        "kind": outcome.truth.kind.value,
                        "row": outcome.truth.row,
                        "change": outcome.truth.change,
                        "rules_found": list(outcome.rules),
                    }
                )
            entry["found_by_expected_check"] += found
            entry["localized_by_expected_check"] += localized
            entry["found_by_any_check"] += outcome.detected
            entry["findings"] += outcome.findings
            key = _category_key(EXPECTED_CATEGORY[outcome.truth.kind])
            category = by_category[key]
            category["planted"] += 1
            if available:
                category["measured"]["planted"] += 1
                category["measured"]["found"] += key in outcome.categories
            else:
                category["not_available"]["planted"] += 1
            for hit in outcome.checks:
                counts = entry["by_check"].setdefault(
                    hit.detector_id, {"flagged": 0, "localized": 0}
                )
                counts["flagged"] += 1
                counts["localized"] += hit.localized
        signal_findings += sum(1 for d in result.score.detectors if d in signal_checks)
        rule_findings += sum(1 for d in result.score.detectors if d not in signal_checks)
        for finding in result.score.false_positives:
            if finding.detector_id in signal_checks:
                signal_counts[finding.detector_id] += 1
                signals.append((order, doc.name, finding))
            else:
                rule_unplanted.append((doc.name, finding))
    planted = sum(entry["planted"] for entry in by_kind.values())
    matched = sum(entry["findings"] for entry in by_kind.values())
    for entry in by_kind.values():
        measured = entry["status"] == "measured"
        entry["recall"] = (
            _ratio(entry["found_by_expected_check"], entry["planted"]) if measured else None
        )
        entry["cell_localization"] = (
            _ratio(entry["localized_by_expected_check"], entry["found_by_expected_check"])
            if measured
            else None
        )
        for counts in entry["by_check"].values():
            counts["recall"] = _ratio(counts["flagged"], entry["planted"])
            counts["cell_localization"] = _ratio(counts["localized"], counts["flagged"])
    signals.sort(key=_strongest_first)
    return {
        "label": LABEL,
        "bills": {
            name: bills[name]
            for name in (
                "bills",
                "buildings",
                "keys",
                "components",
                "type_column",
                "type_names",
                "english",
            )
        },
        "rows": rows,
        "item_rows": item_rows,
        "planted_errors": planted,
        "rule_findings": rule_findings,
        "signals": signal_findings,
        "findings_per_planted_error": _ratio(matched, planted),
        "by_kind": by_kind,
        "by_finding_category": by_category,
        "missed": missed,
        "rule_findings_on_unplanted_rows": {
            "count": len(rule_unplanted),
            "per_1000_rows": _per_thousand(len(rule_unplanted), rows),
            "listed": [
                {
                    "document": name,
                    "detector_id": f.detector_id,
                    "rule_id": f.rule_id,
                    "rows": sorted(f.rows),
                    "title": f.title,
                }
                for name, f in rule_unplanted[:LISTED]
            ],
        },
        "signals_on_unplanted_rows": {
            check: {
                "count": signal_counts[check],
                "per_1000_item_rows": _per_thousand(signal_counts[check], item_rows),
            }
            for check in sorted(signal_checks)
        },
        "strongest_signals": [
            {
                "document": name,
                "detector_id": f.detector_id,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "rows": sorted(f.rows),
                "title": f.title,
            }
            for _, name, f in signals[:STRONGEST]
        ],
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _checks(entry: Mapping[str, Any]) -> str:
    names = []
    for check in entry["expected_checks"]:
        rules = f" ({', '.join(check['rule_ids'])})" if check["rule_ids"] else ""
        when = "" if check["available"] else f", {check['step']}"
        names.append(f"`{check['detector_id']}`{rules}{when}")
    return "; ".join(names)


def kind_table(by_kind: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The markdown table of the ``by_kind`` section: one line per kind."""
    lines = [
        "| Type | Kind | Planted | Expected check | Found by it | Recall | Cell localized | "
        "Found by any check |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for kind, entry in by_kind.items():
        if entry["status"] == "measured":
            found = str(entry["found_by_expected_check"])
            recall, localized = fmt(entry["recall"]), fmt(entry["cell_localization"])
        else:
            found, recall, localized = NOT_AVAILABLE, "", ""
        lines.append(
            f"| {entry['anomaly_type']} | `{kind}` | {entry['planted']} | {_checks(entry)} | "
            f"{found} | {recall} | {localized} | {entry['found_by_any_check']} |"
        )
    return lines


def _kinds(kinds: Sequence[str]) -> str:
    return ", ".join(f"`{kind}`" for kind in kinds)


def category_table(by_category: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The markdown table of the ``by_finding_category`` section: per category a line for its
    kinds with an available expected check and one for the others, whose planted errors show
    "check not available yet" instead of a found count; one line when the category has no kind.
    """
    lines = [
        "| Category | Kinds | Planted | Found with this category |",
        "| --- | --- | --- | --- |",
    ]
    for key, entry in by_category.items():
        label = CATEGORY_LABELS[key]
        measured, unavailable = entry["measured"], entry["not_available"]
        if measured["kinds"]:
            lines.append(
                f"| {label} | {_kinds(measured['kinds'])} | {measured['planted']} | "
                f"{measured['found']} |"
            )
        if unavailable["kinds"]:
            lines.append(
                f"| {label} | {_kinds(unavailable['kinds'])} | {unavailable['planted']} | "
                f"{NOT_AVAILABLE} |"
            )
        if not entry["kinds"]:
            lines.append(f"| {label} | none planted | 0 |  |")
    return lines


def render(report: Mapping[str, Any]) -> str:
    """The markdown report of a boq run (``report`` as written to ``report.json``)."""
    boq, timing, corpus = report["boq"], report["timing"], report["corpus"]
    low, high = corpus["boq"]["positions"]
    bills = boq["bills"]
    caption = f"{LABEL}."
    unplanted = boq["rule_findings_on_unplanted_rows"]
    risk = report.get("risk_notes", {"correct": 0, "false": 0})
    notes = risk_notes_text(risk["correct"], risk["false"])
    lines = [
        "# Synthetic benchmark report: BoQ variant",
        "",
        caption,
        "",
        report["disclaimer"],
        "",
        f"Seed `{report['seed']}`, profile `{report['profile_id']}`, {bills['bills']} bills of "
        f"about {low} to {high} positions, 0 to {corpus['max_errors']} planted errors per bill, "
        "checked with every registered check. Regenerate with `python -m app.evaluation "
        f"--variant boq --seed {report['seed']} --documents {bills['bills']}"
        f"{' --ablation' if report.get('ablation') else ''}` (see `--help`).",
        "",
        "## Bills",
        "",
        caption,
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| **F2 at 50 (main score)** | **{fmt(report['synthetic']['f2_at_50'])}** |",
        f"| Precision at 50 (mean) | {fmt(report['synthetic']['mean_precision_at_50'])} |",
        f"| Recall at 50 (mean) | {fmt(report['synthetic']['mean_recall_at_50'])} |",
        f"| Recall | {fmt(report['synthetic']['recall'])} |",
        f"| Bills | {bills['bills']} |",
        f"| Repeated per building under Lose | {bills['buildings']} |",
        f"| With STLB-Bau keys | {bills['keys']} |",
        f"| With unit price components | {bills['components']} |",
        f"| With a Positionsart column | {bills['type_column']} |",
        f"| Of them with the GAEB import's item type names | {bills['type_names']} |",
        f"| In English | {bills['english']} |",
        f"| Data rows | {boq['rows']} |",
        f"| Item rows | {boq['item_rows']} |",
        f"| Planted errors | {boq['planted_errors']} |",
        f"| Rule findings | {boq['rule_findings']} |",
        f"| Signals | {boq['signals']} |",
        f"| Rule findings on unplanted rows (false positives) | {unplanted['count']} |",
        f"| False positives per 1,000 rows | {fmt(unplanted['per_1000_rows'])} |",
        f"| {RISK_NOTES_LINE} | {notes} |",
        f"| Findings per planted error | {fmt(boq['findings_per_planted_error'])} |",
        f"| Row classification accuracy | "
        f"{fmt(report['synthetic']['row_classification_accuracy'])} |",
        f"| Median time per bill (s) | {fmt(timing['median_seconds_per_document'])} |",
        f"| Rows per second | {fmt(timing['rows_per_second'])} |",
        "",
        f"Timing machine: {timing['machine']}; the whole run took {timing['total_seconds']:.1f} s.",
        "",
        "## By error kind",
        "",
        caption,
        "",
        *kind_table(boq["by_kind"]),
        "",
        "## By finding category",
        "",
        caption,
        "",
        "Each kind counts under the finding category its expected check gives its findings. A "
        "planted error is found with its category when a matching finding of any check carries "
        "that category. Kinds whose expected check is not available yet are listed on a line of "
        f'their own, marked "{NOT_AVAILABLE}": their errors are planted but not measured.',
        "",
        *category_table(boq["by_finding_category"]),
    ]
    lines += [
        "",
        "## By check and kind",
        "",
        caption,
        "",
        "Every check that flagged a planted error, expected or not.",
        "",
    ]
    pairs = [
        (check, kind, entry["planted"], counts)
        for kind, entry in boq["by_kind"].items()
        for check, counts in sorted(entry["by_check"].items())
    ]
    if pairs:
        lines += [
            "| Check | Kind | Planted | Flagged | Recall | Cell localized |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for check, kind, planted, counts in sorted(pairs):
            lines.append(
                f"| `{check}` | `{kind}` | {planted} | {counts['flagged']} | "
                f"{fmt(counts['recall'])} | {fmt(counts['cell_localization'])} |"
            )
    else:
        lines.append("None.")
    lines += [
        "",
        "## Signals on unplanted rows",
        "",
        caption,
        "",
        "Signals are findings of statistical, machine-learning, semantic and research checks. On "
        "rows where nothing was planted they are counted here, apart from rule findings, and not "
        "called false positives: a generated bill can hold a genuinely odd price by chance.",
        "",
    ]
    if boq["signals_on_unplanted_rows"]:
        lines += [
            "| Check | Signals on unplanted rows | Per 1,000 item rows |",
            "| --- | --- | --- |",
        ]
        for check, counts in boq["signals_on_unplanted_rows"].items():
            lines.append(f"| `{check}` | {counts['count']} | {fmt(counts['per_1000_item_rows'])} |")
    else:
        lines.append(NO_SIGNAL_CHECK)
    lines += ["", f"### The {STRONGEST} strongest, for inspection", ""]
    if boq["strongest_signals"]:
        lines += [
            "| Bill | Check | Rule | Severity | Rows | Title |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for f in boq["strongest_signals"]:
            rows = ", ".join(map(str, f["rows"])) or "table"
            lines.append(
                f"| {f['document']} | `{f['detector_id']}` | `{f['rule_id']}` | {f['severity']} | "
                f"{rows} | {f['title']} |"
            )
    else:
        lines.append("None.")
    lines += [
        "",
        "## Rule findings on unplanted rows (false positives)",
        "",
        caption,
        "",
        f"{RISK_NOTES_LINE}: {notes}. A list of the bill's contingency and hourly positions "
        "(`domain.boq_position_types`) is a correct note when every row it names is such a "
        "position of the generated bill (the generator's own item types); it claims no error, "
        "so it is counted here and not as a false positive. A list that names any other row is "
        "a false positive below.",
        "",
    ]
    if unplanted["listed"]:
        lines += ["| Bill | Check | Rule | Rows | Title |", "| --- | --- | --- | --- | --- |"]
        for f in unplanted["listed"]:
            rows = ", ".join(map(str, f["rows"])) or "table"
            lines.append(
                f"| {f['document']} | `{f['detector_id']}` | `{f['rule_id']}` | {rows} | "
                f"{f['title']} |"
            )
    else:
        lines.append("None.")
    lines += ["", "## Missed by an available expected check", "", caption, ""]
    if boq["missed"]:
        lines += [
            "| Bill | Kind | Row | Change | Rules found |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in boq["missed"][:LISTED]:
            found = ", ".join(e["rules_found"]) or "none"
            lines.append(
                f"| {e['document']} | `{e['kind']}` | {e['row']} | {e['change']} | {found} |"
            )
    else:
        lines.append("None.")
    lines += [
        "",
        "## Definitions",
        "",
        "F2 at 50, the main score, weighs recall four times as much as precision (F-beta, "
        "beta = 2) over the first 50 findings of each bill in the issue register's order, every "
        "finding counted, signals included, averaged over the bills with planted errors "
        "(`f_beta` and the metric definitions in "
        "`backend/app/evaluation/scoring.py`). "
        "A planted error is found by a check when a finding of that check highlights a row where "
        "reporting the error is correct: its own row, the totals it throws off, and for a "
        "changed price or quantity the position's identical copies (a comparison of two copies "
        "cannot tell which one is wrong). Recall is found errors over planted errors of the "
        "kind; cell localization is found errors whose wrong cell the check highlights over "
        "found errors. The expected checks are in `backend/app/evaluation/expectations.py`; a "
        f'kind shows "{NOT_AVAILABLE}" instead of a recall when none of its expected checks is '
        "available in this run: not built yet, or built while the profile lacks a setting the "
        "check needs (the `setting` of its entry in that file); every run plans every "
        "registered check. The expected "
        "finding category of each kind (`EXPECTED_CATEGORY`, same file) "
        "is the category its expected check gives its findings; a finding's category is "
        "computed from its check and rule (`backend/app/models/finding_category.py`), and "
        'findings about reading the file have none ("Reading the file"). See '
        "`backend/app/evaluation/boq_report.py`.",
        "",
    ]
    return "\n".join(lines)
