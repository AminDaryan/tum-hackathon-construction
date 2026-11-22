"""The boq report: expected checks, availability, recall per kind and check, signals."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.__main__ import main
from app.evaluation.boq_report import (
    CATEGORY_KEYS,
    LABEL,
    NO_SIGNAL_CHECK,
    NOT_AVAILABLE,
    build,
    category_table,
)
from app.evaluation.expectations import (
    ANOMALY_TYPE,
    ANOMALY_TYPES,
    EXPECTED_CATEGORY,
    EXPECTED_CHECKS,
    Check,
)
from app.evaluation.runner import (
    BenchmarkConfig,
    render_markdown,
    run_benchmark,
)
from app.evaluation.scoring import RISK_NOTES_LINE, DocumentResult, Finding, score_document
from app.evaluation.synthetic import (
    BoqSettings,
    CorpusConfig,
    ErrorKind,
    GroundTruth,
    SyntheticDocument,
)
from app.models.finding_category import (
    CATEGORY_BY_DETECTOR,
    FINDING_CATEGORY_ORDER,
    FindingCategory,
    finding_category_of,
)

pytestmark = pytest.mark.evaluation

PEER = "statistical.peer_price"
LINE = "deterministic.line_total"


def test_every_kind_has_expected_checks_and_one_of_the_seven_anomaly_types() -> None:
    assert set(EXPECTED_CHECKS) == set(ErrorKind) == set(ANOMALY_TYPE)
    assert set(ANOMALY_TYPE.values()) == set(ANOMALY_TYPES)
    assert all(EXPECTED_CHECKS[kind] for kind in ErrorKind)
    steps = {check.step for checks in EXPECTED_CHECKS.values() for check in checks}
    assert steps == {"available", "B3"}  # every B2 check is built


def test_every_kind_has_an_expected_finding_category() -> None:
    assert set(EXPECTED_CATEGORY) == set(ErrorKind)
    assert set(EXPECTED_CATEGORY.values()) <= {*FindingCategory, None}


def test_expected_categories_agree_with_the_categories_of_todays_checks() -> None:
    """A kind whose expected check exists today expects the category that check's findings
    carry, for each of its expected rules."""
    compared = []
    for kind, checks in EXPECTED_CHECKS.items():
        check = next((c for c in checks if c.detector_id in CATEGORY_BY_DETECTOR), None)
        if check is None:
            continue
        compared.append(kind)
        for rule_id in check.rule_ids or ("default",):
            category = finding_category_of(detector_id=check.detector_id, rule_id=rule_id)
            assert category is EXPECTED_CATEGORY[kind], (kind, rule_id)
    # Every kind: the checks of B2 and B3 have entries, and the price kinds expect S1
    # (statistical.peer_price, which also does M1's comparison).
    assert len(compared) == len(ErrorKind) == 24
    assert EXPECTED_CATEGORY[ErrorKind.UNKNOWN_UNIT] is None  # reading the file


def test_kinds_expected_from_one_planned_check_share_its_category() -> None:
    """The kinds whose first expected check is the same expect one category: that check's."""
    by_check: dict[str, set[FindingCategory | None]] = {}
    for kind, checks in EXPECTED_CHECKS.items():
        by_check.setdefault(checks[0].detector_id, set()).add(EXPECTED_CATEGORY[kind])
    assert all(len(categories) == 1 for categories in by_check.values()), by_check
    assert by_check["statistical.peer_price"] == {FindingCategory.RISK}
    for check in ("statistical.rate_consistency", "statistical.quantity_factor"):
        assert by_check[check] == {FindingCategory.INCONSISTENCY}
    for check in ("semantic.unit_fit", "semantic.section_fit"):
        assert by_check[check] == {FindingCategory.INCONSISTENCY}
    assert by_check["machine_learning.near_duplicates"] == {FindingCategory.INCONSISTENCY}
    for check in (
        "domain.boq_bid_prices",
        "deterministic.hierarchy",
        "deterministic.unit_price_components",
    ):
        assert by_check[check] == {FindingCategory.ERROR}


def test_a_check_is_available_when_registered_and_its_setting_is_in_the_profile() -> None:
    check = Check(
        "deterministic.exact_duplicates", "B2", ("exact_duplicate",), ("ignore_fields", "item_code")
    )
    assert not check.available(set(), {})
    assert not check.available({"deterministic.exact_duplicates"}, {})
    defaults = {"deterministic.exact_duplicates": {"ignore_fields": ["item_code"]}}
    assert check.available({"deterministic.exact_duplicates"}, defaults)
    assert check.matches("deterministic.exact_duplicates", "exact_duplicate")
    assert not check.matches("deterministic.exact_duplicates", "unique")
    assert Check(PEER, "B3").matches(PEER, "any_rule")


def _truth(error_id: str, kind: ErrorKind, row: int, field: str) -> GroundTruth:
    return GroundTruth(error_id, kind, row, field, (row,), (), "")


def _finding(
    detector: str, rule: str, row: int, field: str, severity: str, score: float
) -> Finding:
    return Finding(
        issue_id=f"{detector}-{row}",
        detector_id=detector,
        rule_id=rule,
        severity=severity,
        title="t",
        rows=frozenset({row}),
        cells=frozenset({(row, field)}),
        score=score,
        impact=Decimal(1),
    )


def _result(slip_finder: str = PEER) -> DocumentResult:
    """A bill with three planted errors; ``slip_finder`` is the check that finds the first."""
    truths = (
        _truth("e1", ErrorKind.PRICE_DECIMAL_SLIP, 2, "unit_price"),
        _truth("e2", ErrorKind.LINE_TOTAL_SLIP, 3, "line_total"),
        _truth("e3", ErrorKind.WRONG_UNIT, 4, "unit"),
    )
    findings = [
        _finding(slip_finder, "peer_price", 2, "unit_price", "medium", 3.0),  # finds e1 in its cell
        _finding(LINE, "line_total_mismatch", 3, "line_total", "high", 0.0),  # finds e2
        _finding(PEER, "peer_price", 5, "unit_price", "info", 9.0),  # a signal, nothing planted
        _finding(PEER, "peer_price", 6, "unit_price", "medium", 2.0),  # a stronger one
        _finding(LINE, "line_total_mismatch", 7, "line_total", "high", 0.0),  # false positive
    ]
    doc = SyntheticDocument(
        name="bill.xlsx",
        language="de",
        format="xlsx",
        content=b"",
        row_kinds=dict.fromkeys(range(2, 9), "item") | {9: "subtotal"},
        truths=truths,
        features={"buildings": True, "components": 3},
    )
    return DocumentResult(doc, score_document(findings, truths, k=5), (8, 8), (), 0.1, "processed")


def test_recall_per_kind_and_check_with_a_signal_check_registered() -> None:
    kinds = [ErrorKind.PRICE_DECIMAL_SLIP, ErrorKind.LINE_TOTAL_SLIP, ErrorKind.WRONG_UNIT]
    report = build([_result()], kinds, registered={PEER, LINE}, signal_checks={PEER}, defaults={})
    assert report["label"] == LABEL
    slip = report["by_kind"]["price_decimal_slip"]
    assert slip["status"] == "measured" and slip["anomaly_type"] == "price"
    assert (slip["planted"], slip["recall"], slip["cell_localization"]) == (1, 1.0, 1.0)
    assert slip["by_check"] == {
        PEER: {"flagged": 1, "localized": 1, "recall": 1.0, "cell_localization": 1.0}
    }
    assert report["by_kind"]["line_total_slip"]["recall"] == 1.0
    unit = report["by_kind"]["wrong_unit"]
    assert unit["status"] == NOT_AVAILABLE and unit["recall"] is None and unit["planted"] == 1
    assert report["missed"] == []  # wrong_unit is not missed: its check does not exist yet
    assert report["item_rows"] == 7 and report["rows"] == 8
    assert report["bills"]["buildings"] == 1 and report["bills"]["components"] == 1
    signals = report["signals_on_unplanted_rows"][PEER]
    assert signals == {"count": 2, "per_1000_item_rows": pytest.approx(2000 / 7)}
    assert [s["rows"] for s in report["strongest_signals"]] == [[6], [5]]  # medium before info
    rules = report["rule_findings_on_unplanted_rows"]
    assert rules["count"] == 1 and rules["listed"][0]["rows"] == [7]
    assert (report["rule_findings"], report["signals"]) == (2, 3)
    assert report["findings_per_planted_error"] == pytest.approx(2 / 3)


def test_planted_and_found_per_finding_category() -> None:
    kinds = [ErrorKind.PRICE_DECIMAL_SLIP, ErrorKind.LINE_TOTAL_SLIP, ErrorKind.WRONG_UNIT]
    report = build([_result()], kinds, registered={PEER, LINE}, signal_checks={PEER}, defaults={})
    by_category = report["by_finding_category"]
    order = (*(category.value for category in FINDING_CATEGORY_ORDER), "none")
    assert tuple(by_category) == CATEGORY_KEYS == order  # the risk report's order
    assert by_category["error"] == _category(measured=(["line_total_slip"], 1, 1))
    # wrong_unit's expected check (U1) is not registered: planted, not measured.
    assert by_category["inconsistency"] == _category(not_available=(["wrong_unit"], 1))
    # Found by the peer-price check, a risk check: found with its category.
    assert by_category["risk"] == _category(measured=(["price_decimal_slip"], 1, 1))
    assert by_category["none"] == _category()
    assert sum(entry["planted"] for entry in by_category.values()) == report["planted_errors"]
    # Found by a check the category tables do not know: no category, so not found as a risk.
    unknown = build(
        [_result(slip_finder="statistical.not_in_the_tables")],
        kinds,
        registered={PEER, LINE},
        signal_checks={PEER},
        defaults={},
    )
    risk = unknown["by_finding_category"]["risk"]
    assert risk == _category(measured=(["price_decimal_slip"], 1, 0))


def _category(
    measured: tuple[list[str], int, int] = ([], 0, 0),
    not_available: tuple[list[str], int] = ([], 0),
) -> dict[str, Any]:
    """A ``by_finding_category`` entry: (kinds, planted, found) of the kinds with an available
    expected check, (kinds, planted) of the others."""
    return {
        "kinds": measured[0] + not_available[0],
        "planted": measured[1] + not_available[1],
        "measured": {"kinds": measured[0], "planted": measured[1], "found": measured[2]},
        "not_available": {"kinds": not_available[0], "planted": not_available[1]},
    }


def test_kinds_without_an_available_check_are_planted_but_not_measured() -> None:
    kinds = [
        ErrorKind.PRICE_DECIMAL_SLIP,
        ErrorKind.LINE_TOTAL_SLIP,
        ErrorKind.PLACEHOLDER_PRICE,
        ErrorKind.WRONG_UNIT,
    ]
    report = build([_result()], kinds, registered={LINE}, signal_checks=set(), defaults={})
    by_category = report["by_finding_category"]
    # The price check (S1) is not registered, although PEER found the slip.
    assert by_category["risk"] == _category(not_available=(["price_decimal_slip"], 1))
    assert by_category["error"] == _category(
        measured=(["line_total_slip"], 1, 1), not_available=(["placeholder_price"], 0)
    )
    assert category_table(by_category) == [
        "| Category | Kinds | Planted | Found with this category |",
        "| --- | --- | --- | --- |",
        "| Error | `line_total_slip` | 1 | 1 |",
        f"| Error | `placeholder_price` | 0 | {NOT_AVAILABLE} |",
        f"| Inconsistency | `wrong_unit` | 1 | {NOT_AVAILABLE} |",
        "| Omission | none planted | 0 |  |",
        "| Ambiguity | none planted | 0 |  |",
        f"| Risk | `price_decimal_slip` | 1 | {NOT_AVAILABLE} |",
        "| Change order opportunity | none planted | 0 |  |",
        "| Reading the file | none planted | 0 |  |",
    ]


def test_a_finding_about_reading_the_file_is_not_found_with_the_error_category() -> None:
    truth = _truth("e1", ErrorKind.LINE_TOTAL_SLIP, 3, "line_total")
    finding = _finding(LINE, "line_total_mismatch", 3, "line_total", "high", 0.0)
    # A total that differs only by the rounding of displayed values: about reading the file.
    reading = _finding(
        "deterministic.subtotal", "subtotal_display_rounding", 3, "line_total", "info", 0.0
    )
    [outcome] = score_document([reading], [truth], k=5).outcomes
    assert outcome.detected and outcome.categories == ("none",)
    [both] = score_document([finding, reading], [truth], k=5).outcomes
    assert both.categories == ("error", "none")
    doc = SyntheticDocument("bill.csv", "de", "csv", b"", {3: "item"}, (truth,), features={})
    result = DocumentResult(
        doc, score_document([reading], [truth], k=5), (1, 1), (), 0.1, "processed"
    )
    report = build(
        [result], [ErrorKind.LINE_TOTAL_SLIP], registered={LINE}, signal_checks=set(), defaults={}
    )
    assert report["by_finding_category"]["error"] == _category(measured=(["line_total_slip"], 1, 0))
    slip = report["by_kind"]["line_total_slip"]
    assert slip["found_by_any_check"] == 1 and slip["found_by_expected_check"] == 0


def test_without_its_check_a_kind_is_not_available_and_not_missed() -> None:
    kinds = [ErrorKind.PRICE_DECIMAL_SLIP, ErrorKind.LINE_TOTAL_SLIP, ErrorKind.WRONG_UNIT]
    report = build([_result()], kinds, registered={LINE}, signal_checks=set(), defaults={})
    slip = report["by_kind"]["price_decimal_slip"]
    assert slip["status"] == NOT_AVAILABLE and slip["found_by_any_check"] == 1
    assert report["signals_on_unplanted_rows"] == {}
    assert report["rule_findings_on_unplanted_rows"]["count"] == 3  # PEER counted as a rule


def _small_boq(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    corpus = CorpusConfig(
        seed=5,
        documents_per_variant=3,
        max_errors=8,
        variant="boq",
        boq=BoqSettings(positions=(80, 100)),
    )
    return run_benchmark(BenchmarkConfig(corpus=corpus, **changes), tmp_path)


def test_a_boq_run_writes_the_boq_report(tmp_path: Path) -> None:
    report = _small_boq(tmp_path)
    assert report["variant"] == "boq" and report["label"] == LABEL
    boq = report["boq"]
    assert boq["bills"]["bills"] == 3 and boq["planted_errors"] > 0
    # The list of contingency positions (domain.boq_position_types) of a bill that has them is
    # a correct risk note, checked against the generated bill, not a false positive.
    assert boq["rule_findings_on_unplanted_rows"]["count"] == 0
    assert report["risk_notes"]["false"] == 0
    assert report["risk_notes"]["correct"] <= boq["bills"]["bills"]
    # Every check runs, so every kind planted in these bills is measured by its expected check.
    assert {entry["status"] for entry in boq["by_kind"].values() if entry["planted"]} == {
        "measured"
    }
    assert report["timing"]["total_seconds"] >= 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["corpus"]["variant"] == "boq" and "languages" not in manifest["corpus"]
    assert all("features" in entry for entry in manifest["documents"])
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert markdown.startswith("# Synthetic benchmark report: BoQ variant")
    line = f"| {RISK_NOTES_LINE} | {report['risk_notes']['correct']}, all correct |"
    assert line in markdown and f"{RISK_NOTES_LINE}: " in markdown
    assert f"| {NOT_AVAILABLE} |" not in markdown
    assert "Signals on unplanted rows" in markdown
    by_category = boq["by_finding_category"]
    assert sum(entry["planted"] for entry in by_category.values()) == boq["planted_errors"]
    for entry in by_category.values():
        measured, unavailable = entry["measured"], entry["not_available"]
        assert measured["found"] <= measured["planted"]
        assert measured["planted"] + unavailable["planted"] == entry["planted"]
        assert sorted(measured["kinds"] + unavailable["kinds"]) == sorted(entry["kinds"])
    assert "## By finding category" in markdown and "| Reading the file | `unknown_unit` |" in (
        markdown
    )
    tables = markdown.count("\n| --- |")
    assert markdown.count(f"{LABEL}.") >= tables  # a caption above every table


def test_the_standard_report_is_labelled_and_keeps_its_shape(tmp_path: Path) -> None:
    corpus = CorpusConfig(documents_per_variant=1, sections=(1, 2), items_per_section=(3, 6))
    report = run_benchmark(BenchmarkConfig(corpus=corpus), tmp_path)
    assert "boq" not in report and set(report["by_error_kind"]) == {
        kind.value for kind in corpus.kinds
    }
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "variant" not in manifest["corpus"] and "features" not in manifest["documents"][0]
    assert f"\n{LABEL}.\n" in render_markdown(report)


def test_command_line_boq(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "--variant", "boq", "--documents", "2", "--positions", "80", "90",
            "--out", str(tmp_path / "out"),
        ]
    )  # fmt: skip
    output = capsys.readouterr().out
    assert "# Synthetic benchmark report: BoQ variant" in output and LABEL in output
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["seed"] == 20261120 and report["corpus"]["max_errors"] == 8
    assert report["corpus"]["boq"]["positions"] == [80, 90]


def _missed() -> DocumentResult:
    truths = (_truth("m1", ErrorKind.LINE_TOTAL_SLIP, 3, "line_total"),)
    doc = SyntheticDocument("other.xlsx", "en", "xlsx", b"", {3: "item"}, truths)
    return DocumentResult(doc, score_document([], truths, k=5), (1, 1), (), 0.1, "processed")


def test_the_boq_markdown_lists_checks_signals_and_missed_errors(tmp_path: Path) -> None:
    report = _small_boq(tmp_path)
    kinds = [ErrorKind.PRICE_DECIMAL_SLIP, ErrorKind.LINE_TOTAL_SLIP, ErrorKind.WRONG_UNIT]
    report["boq"] = build(
        [_result(), _missed()], kinds, registered={PEER, LINE}, signal_checks={PEER}, defaults={}
    )
    markdown = render_markdown(report)
    assert f"| `{PEER}` | `price_decimal_slip` | 1 | 1 | 1.000 | 1.000 |" in markdown
    assert f"| `{PEER}` | 2 | {2000 / 8:.3f} |" in markdown  # per 1,000 item rows
    assert f"| bill.xlsx | `{PEER}` | `peer_price` | medium | 6 | t |" in markdown
    assert f"| bill.xlsx | `{LINE}` | `line_total_mismatch` | 7 | t |" in markdown
    assert "| other.xlsx | `line_total_slip` | 3 |  | none |" in markdown
    assert NO_SIGNAL_CHECK not in markdown
