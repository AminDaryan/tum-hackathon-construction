"""The risk report end to end: upload a bill, validate it, ask for its risks.

The bill below is synthetic (written for these tests, not taken from a project). Each scenario
the risk report must handle has its own position:

* 01.01.0020: a real arithmetic error (2.600,00 instead of 10 x 250,00) -> confirmed, exact money
* 01.01.00x0: reinforcement included by the section's preliminary note -> no reminder
* 01.02.0010 / 0020: "Stahlbetondecke D3" and "Betonstahl ... Decke D3": different words, the
  same component -> covered
* 01.02.0030: rebar is offered only for Decke D3 and D4, not for D5 -> asked, not covered
* 02.0010 / 0020: waterproofing exists for Kellerwand Haus A only; Haus B is another building
* 02.0040: "gemäß Plan" without a drawing number -> the drawing is asked for (cannot_tell)
* 01.02.0050: no concrete class and "o. glw." -> one reminder found by two methods
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.test_api import (
    API,
    _csv,
    _edit_first_description,
    _error,
    _upload,
    _workbench,
)

ROWS: list[list[Any]] = [
    ["LV Rohbau Wohnanlage"],
    [],
    ["OZ", "Kurztext", "Menge", "ME", "EP (EUR)", "GP (EUR)"],
    ["01", "Titel 01 Rohbau"],
    ["01.01", "Untertitel Wände Haus A"],
    [None, "Vorbemerkung: Die Bewehrung der Wände ist in die Einheitspreise einzurechnen."],
    ["01.01.0010", "Stahlbetonwand W12, C30/37 XC1", "20", "m3", "250,00", "5.000,00"],
    ["01.01.0020", "Stahlbetonwand W14, C30/37 XC1", "10", "m3", "250,00", "2.600,00"],
    ["01.02", "Untertitel Decken Haus B"],
    ["01.02.0010", "Stahlbetondecke D3, C25/30 XC1", "30", "m3", "220,00", "6.600,00"],
    [
        "01.02.0020",
        "Betonstahl B500B liefern und verlegen, Decke D3",
        "2",
        "t",
        "1.400,00",
        "2.800,00",
    ],
    ["01.02.0030", "Stahlbetondecke D5, C25/30 XC1", "12", "m3", "220,00", "2.640,00"],
    ["01.02.0040", "Bewehrung B500B für Decke D4", "1", "t", "1.400,00", "1.400,00"],
    ["01.02.0050", "Stahlbetonstütze S1 o. glw.", "3", "m3", "300,00", "900,00"],
    ["02", "Titel 02 Keller"],
    ["02.0010", "Kellerwand Haus A, Beton C25/30 XC2", "40", "m2", "90,00", "3.600,00"],
    ["02.0020", "Kellerwand Haus B, Beton C25/30 XC2", "40", "m2", "90,00", "3.600,00"],
    ["02.0030", "Abdichtung Kellerwand Haus A mit KMB", "40", "m2", "35,00", "1.400,00"],
    ["02.0040", "Schalung gemäß Plan", "60", "m2", "30,00", "1.800,00"],
]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(
        create_app(workbench=_workbench(tmp_path)), base_url="http://localhost"
    ) as test_client:
        yield test_client


def _run(client: TestClient) -> str:
    dataset = _upload(client, _csv(ROWS), "Rohbau.csv").json()["dataset"]
    return client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()["run_id"]  # type: ignore[no-any-return]


def _report(client: TestClient, run_id: str | None = None, query: str = "") -> dict[str, Any]:
    response = client.get(f"{API}/validation-runs/{run_id or _run(client)}/risks{query}")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _about(report: dict[str, Any], label: str) -> list[dict[str, Any]]:
    """Reminders on a position, in the main list or the check record."""
    every = [*report["risks"], *report["record"]]
    return [r for r in every if label in {p["label"] for p in r["positions"]}]


def test_a_real_arithmetic_error_is_confirmed_with_its_exact_difference(client: TestClient) -> None:
    [risk] = [r for r in _about(_report(client), "01.01.0020") if r["risk_type"] == "R076"]
    assert risk["state"] == "risk" and risk["evidence_class"] == "confirmed_rule_violation"
    assert risk["money"]["kind"] == "exact" and risk["money"]["currency"] == "EUR"
    assert risk["money"]["amount"] == "100.00" and risk["money"]["basis"]
    assert any(q["text"] == "2.600,00" for q in risk["quotes"])  # the cell as the bill states it
    # Preserve pricing privacy while asking to confirm the check's rule.
    assert risk["question"] and risk["source_issue_ids"]
    assert "unit price" in risk["question"].lower() and "confirm" in risk["question"].lower()
    assert not any(
        value in risk["question"] for value in ("250", "2500", "2600", "2,500", "2.600", "VOB", "§")
    )


def test_the_same_component_under_other_words_is_covered(client: TestClient) -> None:
    report = _report(client)
    assert not [r for r in _about(report, "01.02.0010") if r["risk_type"] == "R002"]
    [rebar] = [r for r in report["record"] if r["risk_type"] == "R002"]
    # D4's rebar names another component: no cover for D5, and no cover for the column S1.
    assert {p["label"] for p in rebar["positions"]} == {"01.02.0030", "01.02.0050"}
    assert rebar["state"] == "cannot_tell" and rebar["question"].startswith("Which position")


def test_a_similar_position_of_another_building_does_not_cover(client: TestClient) -> None:
    report = _report(client)
    assert not [r for r in _about(report, "02.0010") if r["risk_type"] == "R001"]
    [haus_b] = [r for r in _about(report, "02.0020") if r["risk_type"] == "R001"]
    assert haus_b["state"] == "risk" and haus_b["evidence_class"] == "semantic_warning"
    assert "other trades" in " ".join(haus_b["missing_information"])  # project scope
    assert haus_b["checked"] and haus_b["suggested_action"]


def test_supporting_work_in_the_preliminary_notes_is_covered(client: TestClient) -> None:
    report = _report(client)
    for label in ("01.01.0010", "01.01.0020"):
        assert not [r for r in _about(report, label) if r["risk_type"] == "R002"]
    assert next(row for row in report["coverage"] if row["risk_type"] == "R002")["state"] == (
        "cannot_tell"  # D5 and S1 are still open
    )


def test_a_missing_drawing_is_asked_for(client: TestClient) -> None:
    # Since 2026-11-21 the register's check asks it (domain.boq_clauses, document_reference;
    # rule V03 is gone): its question names the position, the quotes name the words.
    [risk] = _about(_report(client), "02.0040")
    assert risk["state"] == "cannot_tell" and risk["evidence_class"] == "needs_external_context"
    assert risk["rules"] == ["domain.boq_clauses:document_reference"]
    assert "drawing or document" in risk["question"] and "02.0040" in risk["question"]
    assert risk["missing_information"]
    assert any("gemäß Plan" in q["text"] for q in risk["quotes"])


def test_unknown_money_is_shown_as_unknown_and_still_asks(client: TestClient) -> None:
    report = _report(client)
    unknown = [r for r in report["risks"] if r["money"]["kind"] == "unknown"]
    assert unknown and all(r["money"]["amount"] is None and r["money"]["basis"] for r in unknown)
    assert all(r["tier"] in {"medium", "high", "critical"} and r["question"] for r in unknown)


def test_one_issue_found_by_two_methods_is_one_reminder(client: TestClient) -> None:
    [risk] = [r for r in _about(_report(client), "01.02.0050") if r["risk_type"] == "R031"]
    assert set(risk["methods"]) == {"attribute_consistency", "vagueness"}
    assert {"A01", "V04"} <= set(risk["rules"])
    # Keyword clues stay clues: raised for being independent, but not above high.
    assert risk["tier"] == "high" and risk["factors"]["independent_signals"] >= 2


def test_the_report_is_honest_about_coverage_and_the_model(client: TestClient) -> None:
    report = _report(client)
    assert report["model_review"]["status"] == "not_requested"
    rows = report["coverage"]
    assert len(rows) >= 135 and any(r["state"] == "not_checkable" for r in rows)
    assert report["counts"]["risk_types_checked"] < len(rows)
    # The catch-all "other" is not one of the catalogue's risk types.
    assert report["counts"]["risk_types"] == 135
    assert any("first guesses, not measured" in note for note in report["notes"])
    assert [r["rank"] for r in report["risks"]] == list(range(1, len(report["risks"]) + 1))
    assert not any("The reader cut" in note for note in report["notes"])


def test_a_long_text_the_reader_cut_is_named_in_the_notes(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "gaeb" / "small.x83"
    # Its long text has 35 characters, every other value fewer than 30.
    workbench = _workbench(tmp_path, ingestion={"max_cell_chars": 30})
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        upload = client.post(
            f"{API}/documents",
            files={"file": ("small.x83", fixture.read_bytes(), "application/octet-stream")},
        )
        assert upload.status_code == 201, upload.text
        warnings = upload.json()["dataset"]["extraction"]["warnings"]
        assert "gaeb_long_text_clipped" in {w["code"] for w in warnings}
        dataset_id = upload.json()["dataset"]["dataset_id"]
        run_id = client.post(f"{API}/datasets/{dataset_id}/validation-runs").json()["run_id"]
        notes = _report(client, run_id)["notes"]
    [note] = [n for n in notes if n.startswith("The reader cut")]
    assert "1 long text " in note and "'not found' there may be wrong" in note


def test_the_old_model_review_switch_is_refused_and_the_review_stays_for_explicit_callers(
    client: TestClient,
) -> None:
    """Reading a report never calls a model: ``model_review=true`` is refused with a migration
    note, not ignored. The review of open reminders stays a service call of its own."""
    from app.risk.service import risk_report

    run_id = _run(client)
    plain = _report(client, run_id)
    assert _report(client, run_id, "?model_review=false") == plain
    refused = client.get(f"{API}/validation-runs/{run_id}/risks?model_review=true")
    message = _error(refused, 422, "invalid_input")["message"]
    assert "never calls a model" in message and "Leave the parameter out" in message
    assert "not discovery" in message and "discovery-runs" in message
    wb = client.app.state.workbench  # type: ignore[attr-defined]
    asked = risk_report(wb, run_id, model_review=True)  # explicit, in process; no model here
    assert asked.model_review.status == "not_configured"
    unasked = risk_report(wb, run_id)
    assert asked.risks == unasked.risks and asked.coverage == unasked.coverage


def test_an_unknown_run_is_not_found(client: TestClient) -> None:
    _error(client.get(f"{API}/validation-runs/run_nope/risks"), 404, "not_found")


def test_open_questions_stay_in_the_record_grouped_by_cause(client: TestClient) -> None:
    report = _report(client)
    main, record = report["risks"], report["record"]
    # An open question is no to-do of its own; only concrete risks of some weight are shown.
    assert all(r["state"] == "risk" or r["factors"]["harm"] == "safety" for r in main)
    assert all(r["tier"] in {"medium", "high", "critical"} for r in main)
    assert {r["state"] for r in record} <= {"risk", "cannot_tell"}  # never "covered"
    kinds = {q["kind"]: q for q in report["open_questions"]}
    assert "drawings" in kinds["missing_document"]["topic"]
    assert kinds["not_found"]["rules"] and kinds["not_found"]["question"]
    asked = {i for q in report["open_questions"] for i in q["reminder_ids"]}
    assert asked == {r["risk_id"] for r in record if r["state"] == "cannot_tell"}
    funnel = report["funnel"]
    assert funnel["raw_doubts"] == (
        funnel["explained_automatically"]
        + funnel["below_size_threshold"]
        + funnel["open_after_search"]
    )
    assert (
        funnel["explained_automatically"] > 0
        and funnel["after_merging"] < funnel["open_after_search"]
    )
    assert funnel["after_merging"] == funnel["main_list"] + funnel["kept_in_record"]
    missing = funnel["checks_missing_information"]
    assert any("drawings" in line for line in missing)
    assert any("no check in this version" in line for line in missing)


# One position per condition that a risk rule and a check of the issue register both raised
# until 2026-11-21 (D05, D08, D30, A01, A04, V05, V08); the owner then chose "findings first".
TWIN_ROWS: list[list[Any]] = [
    ["LV Zwillinge"],
    [],
    ["OZ", "Kurztext", "Langtext", "Menge", "ME", "EP (EUR)", "GP (EUR)"],
    ["01", "Titel 01 Erdarbeiten und Leitungen"],
    [
        "01.0010",
        "Rohrgraben ausheben",
        "Tiefe bis 1,0 m, Boden seitlich lagern",
        "100",
        "m3",
        "20,00",
        "2.000,00",
    ],
    [
        "01.0020",
        "Trinkwasserleitung verlegen",
        "PE 100 DN 150 liefern und verlegen",
        "100",
        "m",
        "50,00",
        "5.000,00",
    ],
    [
        "01.0030",
        "Ortbeton fuer Fundament einbauen",
        "Streifenfundament, XC2",
        "10",
        "m3",
        "200,00",
        "2.000,00",
    ],
    [
        "01.0040",
        "Boden entsorgen",
        "Aushub laden, abfahren und entsorgen",
        "50",
        "m3",
        "30,00",
        "1.500,00",
    ],
    ["01.0050", "Wasserhaltung", "Abrechnung nach Aufwand", "1", "psch", "3.000,00", "3.000,00"],
    [
        "01.0060",
        "Bedarfsposition: Pumpe vorhalten",
        "Pumpe vorhalten, nur auf Anordnung des AG",
        "10",
        "d",
        "45,00",
        "450,00",
    ],
    ["01.0070", "PVC-Rohr verlegen", "PVC-Rohr liefern und verlegen", "30", "m", "20,00", "600,00"],
]
TWINS = {  # position: (risk type, the register's check that now raises it alone)
    "01.0010": ("R005", "domain.boq_companion_work:trench_without_backfill"),
    "01.0020": ("R010", "domain.boq_companion_work:pipe_without_pressure_test"),
    "01.0030": ("R038", "domain.boq_required_attributes:concrete_strength_class"),
    "01.0040": ("R088", "domain.boq_required_attributes:disposal_waste_class"),
    "01.0050": ("R090", "domain.boq_clauses:open_lump_sum"),
    "01.0060": ("R089", "domain.boq_position_types:contingency_and_hourly"),
    "01.0070": ("R033", "domain.boq_required_attributes:pipe_dimension"),
}
TWIN_RULES = {"D05", "D08", "D30", "A01", "A04", "V05", "V08"}


def test_an_issue_the_register_finds_is_one_reminder_that_asks_the_client(
    client: TestClient,
) -> None:
    dataset = _upload(client, _csv(TWIN_ROWS), "Zwillinge.csv").json()["dataset"]
    run_id = client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()["run_id"]
    report = _report(client, run_id)
    for label, (risk_type, rule) in TWINS.items():
        about = _about(report, label)
        assert not [r for r in about if TWIN_RULES & set(r["rules"])], label
        [risk] = [r for r in about if rule in r["rules"]]
        assert risk["risk_type"] == risk_type and risk["rules"] == [rule], label
        assert risk["factors"]["independent_signals"] == 1, label
        # The register's finding is evidence the bill shows (risk, main list), not an open
        # question the run cannot decide; its reminder still carries the client question.
        assert risk["state"] == "risk" and risk["question"] and label in risk["question"], label
    rows = {r["risk_type"]: r for r in report["coverage"]}
    assert rows["R005"]["state"] == "risk" and "domain.boq_companion_work" in rows["R005"]["rules"]
    assert rows["R118"]["state"] == "covered"  # the numbering hierarchy was checked


TOTAL_ROWS: list[list[Any]] = [
    ["LV Ausbau"],
    [],
    ["OZ", "Kurztext", "Menge", "ME", "EP (EUR)", "GP (EUR)"],
    ["01", "Titel 01 Ausbau"],
    ["01.0010", "Innenputz Wand", "10", "m2", "10,00", "100,00"],
    ["01.0020", "Innenputz Decke", "10", "m2", "20,00", "200,00"],
    ["Summe Titel 01", None, None, None, None, "350,00"],
]


def test_a_wrong_total_links_the_rows_it_sums(client: TestClient) -> None:
    dataset = _upload(client, _csv(TOTAL_ROWS), "Ausbau.csv").json()["dataset"]
    run_id = client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()["run_id"]
    report = _report(client, run_id)
    totals = [r for r in [*report["risks"], *report["record"]] if "total" in r["rules"][0]]
    assert totals, [r["rules"] for r in [*report["risks"], *report["record"]]]
    [risk] = totals
    links = {link["label"]: link for link in risk["evidence_links"]}
    # The total row is the reminder's position; the rows it sums are evidence, by their role.
    assert [p["label"] for p in links["Rows summed"]["positions"]] == ["01.0010", "01.0020"]
    assert links["Rows summed"]["positions_total"] == 2
    assert {p["label"] for p in risk["positions"]}.isdisjoint({"01.0010", "01.0020"})


PEER_ROWS: list[list[Any]] = [
    ["LV Putz"],
    [],
    ["OZ", "Kurztext", "Menge", "ME", "EP (EUR)", "GP (EUR)"],
    ["01", "Titel 01 Putz"],
    ["01.0010", "Innenputz Wand Kalkzement Q2 Haus A", "100", "m2", "20,00", "2.000,00"],
    ["01.0020", "Innenputz Wand Kalkzement Q2 Haus B", "100", "m2", "21,00", "2.100,00"],
    ["01.0030", "Innenputz Wand Kalkzement Q2 Haus C", "100", "m2", "20,50", "2.050,00"],
    ["01.0040", "Innenputz Wand Kalkzement Q2 Haus D", "100", "m2", "19,50", "1.950,00"],
    ["01.0050", "Innenputz Wand Kalkzement Q2 Haus E", "100", "m2", "200,00", "20.000,00"],
]


def test_a_price_comparison_keeps_its_reference_amount_but_not_as_a_loss(
    client: TestClient,
) -> None:
    dataset = _upload(client, _csv(PEER_ROWS), "Putz.csv").json()["dataset"]
    # The price comparison is not in the default plan: the test names it (the detector's own
    # defaults, nothing tuned here).
    plan = {"steps": [{"detector_id": "statistical.peer_price"}]}
    response = client.post(
        f"{API}/datasets/{dataset['dataset_id']}/validation-runs", json={"plan": plan}
    )
    assert response.status_code in (200, 201), response.text
    run_id = response.json()["run_id"]
    report = _report(client, run_id)
    every = [*report["risks"], *report["record"]]
    peers = [r for r in every if r["rules"][0].startswith("statistical.peer_price")]
    assert peers, [r["rules"] for r in every]
    risk = peers[0]
    money = risk["money"]
    assert money["kind"] == "unknown" and money["amount"] is None  # the loss stays unknown
    # The reference amount is the detector's own, when it gave one, and never made up here.
    [issue_id] = risk["source_issue_ids"]
    response = client.get(f"{API}/issues/{issue_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    impact = (body.get("issue") or body).get("estimated_financial_impact")
    if impact is None:
        assert money["reference"] is None
    else:
        reference = money["reference"]
        given = (impact["amount"], impact["currency"])
        assert (reference["amount"], reference["currency"]) == given
        assert reference["source_issue_id"] == issue_id
        assert reference["detector_id"] == "statistical.peer_price"
    # Its coverage is recorded with the detector's own counts.
    [row] = [r for r in report["coverage"] if r["risk_type"] == "R081"]
    [check] = [c for c in row["checks"] if c["rule_id"] == "statistical.peer_price"]
    assert check["state"] == "risk" and "rows_compared" in check["reason"]


def _without(report: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in report.items() if k not in keys}


def test_synthetic_history_runs_on_a_bill_and_abstains_on_incompatible_prices(
    client: TestClient,
) -> None:
    panel = Path(__file__).resolve().parents[3] / "samples/history/panel/p25.csv"
    uploaded = _upload(client, panel.read_bytes(), "synthetic-p25.csv")
    assert uploaded.status_code == 201, uploaded.text
    dataset = uploaded.json()["dataset"]
    response = client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs")
    assert response.status_code == 201, response.text
    run = response.json()
    [check] = [
        r for r in run["detector_reports"] if r["detector_id"] == "statistical.historical_price"
    ]
    assert check["status"] == "completed", check
    # Require eight earlier projects with matching numerical specifications, not merely
    # similar wording. P25's one planted price error (position 01) is still the only finding.
    assert check["coverage"]["rows_compared"] == 6
    assert check["issues_found"] == 1
    risks = _report(client, run["run_id"])
    [risk] = [
        r
        for r in [*risks["risks"], *risks["record"]]
        if r["rules"][0].startswith("statistical.historical_price")
    ]
    assert risk["evidence_class"] == "suspected_anomaly"
    assert risk["money"]["kind"] == "unknown" and risk["money"]["reference"] is None
    assert {p["label"] for p in risk["positions"]} == {"01"}
    issue = client.get(f"{API}/issues/{risk['source_issue_ids'][0]}").json()
    issue = issue.get("issue", issue)
    [evidence] = [e for e in issue["evidence"] if e["kind"] == "comparison"]
    data = evidence["data"]
    assert data["evidence_kind"] == "synthetic_example"
    # Matching is by wording: the eight projects that describe the pipe the same way.
    assert data["peer_projects"] == 8
    assert set(data["reference_projects"].split(", ")) <= {f"P{i:02}" for i in range(1, 25)}
    assert data["date_source"] == "price date column"
    assert data["latest_reference"] < "2025-02-15"
    # Price basis must be normalized: the uploaded rate is per 100 m, the evidence per m.
    assert 70 < float(issue["observed_value"]) < 130
    assert 35 < float(data["median"]) < 65

    pipe = "PE100-RC d110 SDR11 liefern/verlegen; ohne Erdarbeiten, Bettung und Formteile"
    header = [
        "OZ",
        "Beschreibung",
        "Menge",
        "Einheit",
        "EP (EUR)",
        "Betrag (EUR)",
        "Preisstand",
        "Preisart",
    ]
    rows = [
        header,
        ["01", pipe, "1", "100 m", "5000", "5000", "2025-02-15", "net"],
        ["02", pipe, "1", "m3", "150", "150", "2025-02-15", "net"],
        ["03", pipe + "; inkl. Aushub", "1", "m", "150", "150", "2025-02-15", "net"],
        ["04", pipe, "1", "m", "150", "150", "", "net"],
        ["05", pipe, "1", "m", "150", "150", "2025-02-15", "gross"],
        ["06", pipe, "1", "m", "150", "150", "2021-02-15", "net"],
    ]
    # _csv deliberately has no quoting; csv.writer is needed for descriptions with semicolons.
    stream = io.StringIO()
    csv.writer(stream).writerows(rows)
    other = _upload(client, stream.getvalue().encode(), "scope-controls.csv").json()["dataset"]
    checked = client.post(f"{API}/datasets/{other['dataset_id']}/validation-runs").json()
    [report] = [
        r for r in checked["detector_reports"] if r["detector_id"] == "statistical.historical_price"
    ]
    assert report["status"] == "completed", report
    # 01 per 100 m is compared and ordinary; 02 has no pipe history in m3; 05 is gross; 06
    # predates every reference project. 03 (a bundled scope worded like the pipe) and 04 (no
    # price date and no bill date: compared undated, with a wider interval) are compared and
    # flagged at EUR 150/m, each with its 1 m quantity, hundreds of times below the projects'.
    assert report["coverage"] == {
        "rows_compared": 3,
        "rows_compared_undated": 1,
        "rows_without_comparable_history": 1,
        "rows_without_price_context": 1,
        "rows_without_enough_projects": 1,
    }
    flagged = client.get(f"{API}/validation-runs/{checked['run_id']}/issues").json()["items"]
    assert sorted(
        (i["rule_id"].rsplit(".", 1)[-1], i["observed_value"])
        for i in flagged
        if i["detector_id"] == "statistical.historical_price"
    ) == [
        ("historical_price_outlier", "150"),
        ("historical_price_outlier", "150"),
        ("historical_quantity_outlier", "1"),
        ("historical_quantity_outlier", "1"),
    ]


def test_discovery_runs_only_when_started_and_reading_never_builds_a_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.risk import discovery

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no model client may be built")

    monkeypatch.setattr(discovery, "OllamaGenerator", refuse)
    run_id = _run(client)
    default = _report(client, run_id)
    assert default["discovery"]["status"] == "not_enabled"
    assert _report(client, run_id, "?discovery=off") == default
    old = client.get(f"{API}/validation-runs/{run_id}/risks?discovery=paths")
    assert old.status_code == 422 and "discovery-runs" in old.text  # removed, said so
    # Started without a configured model: stored as not processed, nothing sent.
    started = client.post(f"{API}/validation-runs/{run_id}/risks/discovery-runs", json={})
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "finished" and run["discovery"]["status"] == "not_processed"
    applied = _report(client, run_id, f"?discovery_run_id={run['discovery_run_id']}")
    assert applied["discovery"]["status"] == "not_processed"
    assert _without(applied, "discovery", "notes") == _without(default, "discovery", "notes")
    missing = client.get(f"{API}/validation-runs/{run_id}/risks?discovery_run_id=disc_nope")
    assert missing.status_code == 404


def _finding(item: str, quote: str, hypothesis: str, verification: str) -> dict[str, Any]:
    return {
        "item": item,
        "quote": quote,
        "stated_facts": "What the position says, in the model's words.",
        "hypothesis": hypothesis,
        "affects": "formwork, material and labour assumptions",
        "missing_documents": [],
        "verification": verification,
    }


class Spy:
    """Stands in for the local model client: counts requests and answers from the prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.last_usage = (1000, 50)
        self.last_stop = "stop"

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        ids = dict(re.findall(r"^\[(P\d+)\] position (\S+)", prompt, re.MULTILINE))
        by_label = {label: pid for pid, label in ids.items()}
        found = []
        if "02.0040" in by_label:  # the register already asks about "gemäß Plan"
            found.append(
                _finding(
                    by_label["02.0040"],
                    "Schalung gemäß Plan",
                    "The formwork plan is not named; its number is unknown.",
                    "Ask which Plan the Schalung of 02.0040 follows.",
                )
            )
        if "02.0030" in by_label:  # no rule reports anything on this position
            found.append(
                _finding(
                    by_label["02.0030"],
                    "Abdichtung Kellerwand Haus A mit KMB",
                    "The layer thickness of the KMB is not stated; the material quantity depends "
                    "on it.",
                    "Ask which layer thickness the KMB Abdichtung needs.",
                )
            )
        return json.dumps({"findings": found})


@pytest.fixture
def model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Spy]]:
    from app.core.config import LLMSettings
    from app.risk import discovery

    spy = Spy()
    monkeypatch.setattr(discovery, "OllamaGenerator", lambda settings: spy)
    llm = LLMSettings(provider="ollama", model="qwen2.5:7b-instruct")
    with TestClient(
        create_app(workbench=_workbench(tmp_path, llm=llm)), base_url="http://localhost"
    ) as test_client:
        yield test_client, spy


def test_a_stored_run_is_read_and_sorted_without_calling_the_model_again(
    model: tuple[TestClient, Spy],
) -> None:
    """Interface check with a stand-in model (no real model): one explicit run, then reads."""
    client, spy = model
    run_id = _run(client)
    before = _report(client, run_id)
    path = f"{API}/validation-runs/{run_id}/risks/discovery-runs"
    started = client.post(path, json={"strategy": "paths"})
    assert started.status_code == 201, started.text
    run = started.json()
    assert started.headers["location"].endswith(run["discovery_run_id"])
    asked = len(spy.prompts)
    assert asked >= 1 and run["discovery"]["status"] == "completed"
    assert all(call["stop_reason"] == "stop" for call in run["discovery"]["calls"])
    assert run["seconds_total"] is not None and run["seconds_model"] is not None
    assert [e["prompt"] for e in run["exchanges"]] == spy.prompts  # as sent, with raw answers
    again = client.post(path, json={})  # a double click: the stored run, nothing new
    assert again.status_code == 200 and again.json()["discovery_run_id"] == run["discovery_run_id"]
    query = f"?discovery_run_id={run['discovery_run_id']}"
    reports = {
        (by, order): _report(client, run_id, f"{query}&sort_by={by}&sort_order={order}")
        for by in ("priority", "price_impact", "confidence")
        for order in ("desc", "asc")
    }
    assert len(spy.prompts) == asked  # reading and sorting asked the model nothing
    stored = client.get(f"{path}/{run['discovery_run_id']}").json()
    assert stored["discovery"]["budget"] == run["discovery"]["budget"] and stored == run
    applied = reports[("priority", "desc")]
    assert applied == _report(client, run_id, query)  # the default order
    found = applied["discovery"]
    assert found["discovery_run_id"] == run["discovery_run_id"] and found["kept"] == 2
    assert applied["risks"] == before["risks"]  # the main list holds checked evidence only
    assert applied["counts"]["open_questions_from_discovery"] == 2
    ours = [q for q in applied["open_questions"] if q["source"] == "discovery"]
    assert {q["positions"][0] for q in ours} == {"02.0030", "02.0040"}  # same quote, new cause
    for (by, order), report in reports.items():
        assert report["display"]["sort_by"] == by and report["display"]["sort_order"] == order
        for name in ("risks", "record"):
            assert [r["rank"] for r in report[name]] == list(range(1, len(report[name]) + 1))
            same = {r["risk_id"]: _without(r, "rank", "sort_note") for r in report[name]}
            default = {r["risk_id"]: _without(r, "rank", "sort_note") for r in applied[name]}
            assert same == default  # content, ids and priority_rank unchanged
        assert _without(report, "risks", "record", "display") == _without(
            applied, "risks", "record", "display"
        )

    # asc reverses the checks' reminders and, after them, the experimental supplements: the
    # model's hypotheses never move into the base queue.
    def ids(rows: list[dict[str, Any]], model: bool) -> list[str]:
        return [r["risk_id"] for r in rows if (r["methods"] == ["guided_llm"]) is model]

    reverse = reports[("priority", "asc")]["record"]
    assert [r["risk_id"] for r in reverse] == (
        ids(applied["record"], False)[::-1] + ids(applied["record"], True)[::-1]
    )
    assert ids(applied["record"], True) and all(q["experimental"] for q in ours)
    assert [r["risk_id"] for r in applied["record"]] == (
        ids(applied["record"], False) + ids(applied["record"], True)
    )
    rerun = client.post(path, json={"rerun": True})
    assert rerun.status_code == 201 and rerun.json()["discovery_run_id"] != run["discovery_run_id"]
    assert len(spy.prompts) == 2 * asked
    listed = client.get(path).json()["items"]
    assert [r["discovery_run_id"] for r in listed][1] == run["discovery_run_id"]


def test_a_run_made_for_other_inputs_is_shown_as_outdated_not_applied(
    model: tuple[TestClient, Spy], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.risk import service

    client, _ = model
    run_id = _run(client)
    run = client.post(f"{API}/validation-runs/{run_id}/risks/discovery-runs", json={}).json()
    query = f"?discovery_run_id={run['discovery_run_id']}"
    assert _report(client, run_id, query)["discovery"]["kept"] == 2
    monkeypatch.setattr(service, "_digest", lambda bill: "another bill text")
    outdated = _report(client, run_id, query)
    assert outdated["discovery"]["status"] == "outdated"
    assert "bill_text" in outdated["discovery"]["detail"]
    assert not [q for q in outdated["open_questions"] if q["source"] != "checks"]
    monkeypatch.setattr(service, "PROMPT_VERSION", "discovery-99")
    assert "prompt_and_checks" in _report(client, run_id, query)["discovery"]["detail"]


def test_with_a_model_configured_no_read_sort_or_poll_calls_either_model_client(
    model: tuple[TestClient, Spy], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both model clients are spies, discovery's and the model review's: only the explicit
    start asks a model; every read, sort and poll asks none, old switches included."""
    from app.risk import model_review

    client, spy = model
    reviewer = Spy()
    monkeypatch.setattr(model_review, "OllamaGenerator", lambda settings: reviewer)
    run_id = _run(client)
    path = f"{API}/validation-runs/{run_id}/risks"
    started = client.post(f"{path}/discovery-runs", json={})
    assert started.status_code == 201 and spy.prompts, started.text
    asked = len(spy.prompts)
    stored = {"discovery_run_id": started.json()["discovery_run_id"]}
    for applied in ({}, stored):
        for by in ("priority", "price_impact", "confidence"):
            for order in ("desc", "asc"):
                params = {**applied, "sort_by": by, "sort_order": order}
                assert client.get(path, params=params).status_code == 200
                old = {**params, "model_review": "false"}
                assert client.get(path, params=old).status_code == 200
                for switch in ({"model_review": "true"}, {"discovery": "paths"}):
                    refused = client.get(path, params={**params, **switch})
                    assert refused.status_code == 422, (switch, refused.text)
    one = f"{path}/discovery-runs/{stored['discovery_run_id']}"
    for _ in range(3):  # polling a finished run
        assert client.get(one).json()["status"] == "finished"
    assert client.get(f"{path}/discovery-runs").status_code == 200
    again = client.post(f"{path}/discovery-runs", json={})
    assert (
        again.status_code == 200 and again.json()["discovery_run_id"] == stored["discovery_run_id"]
    )
    assert len(spy.prompts) == asked and reviewer.prompts == []


def _issue_of_a_reminder(client: TestClient, run_id: str) -> dict[str, Any]:
    """A stored finding that a reminder of the report is made of, open for review."""
    report = _report(client, run_id)
    used = {i for r in [*report["risks"], *report["record"]] for i in r["source_issue_ids"]}
    issues = client.get(f"{API}/validation-runs/{run_id}/issues").json()["items"]
    return next(
        i
        for i in issues
        if i["issue_id"] in used and "false_positive" in i["allowed_review_actions"]
    )


def _review(client: TestClient, issue: dict[str, Any], status: str) -> None:
    response = client.post(
        f"{API}/issues/{issue['issue_id']}/review",
        json={"status": status, "expected_version": issue["version"]},
    )
    assert response.status_code == 200, response.text


def _ids(report: dict[str, Any]) -> set[str]:
    return {r["risk_id"] for r in [*report["risks"], *report["record"]]}


def test_a_review_that_changes_what_discovery_would_send_outdates_the_stored_run(
    model: tuple[TestClient, Spy],
) -> None:
    """Through the real review API, no version mocked: a reviewer rejects a finding, its
    reminder stops counting, and the reminders shown to the model (and the positions chosen)
    change. The old run stays readable but is not applied; an explicit start makes a new one."""
    client, spy = model
    run_id = _run(client)
    path = f"{API}/validation-runs/{run_id}/risks/discovery-runs"
    first = client.post(path, json={}).json()
    query = f"?discovery_run_id={first['discovery_run_id']}"
    assert _report(client, run_id, query)["discovery"]["status"] == "completed"
    before = _report(client, run_id)
    rejected = _issue_of_a_reminder(client, run_id)
    _review(client, rejected, "false_positive")
    after = _report(client, run_id)
    # The rejected finding's reminder no longer counts, but stays listed (last) to be undone.
    shown = before["counts"]["reminders"] + before["counts"]["in_record"]
    assert after["counts"]["reminders"] + after["counts"]["in_record"] == shown - 1
    assert _ids(after) == _ids(before)
    listed = [*after["risks"], *after["record"]]
    assert any(rejected["issue_id"] in r["source_issue_ids"] for r in listed)
    asked = len(spy.prompts)
    outdated = _report(client, run_id, query)
    assert outdated["discovery"]["status"] == "outdated"
    assert "selection_and_context" in outdated["discovery"]["detail"]
    assert _without(outdated, "discovery", "notes") == _without(after, "discovery", "notes")
    stored = client.get(f"{path}/{first['discovery_run_id']}")
    assert stored.status_code == 200 and stored.json() == first  # kept, unchanged
    assert len(spy.prompts) == asked  # reading the old run asked the model nothing
    second = client.post(path, json={})
    assert second.status_code == 201, second.text
    assert second.json()["discovery_run_id"] != first["discovery_run_id"]
    assert len(spy.prompts) > asked  # only the explicit start asked
    newer = f"?discovery_run_id={second.json()['discovery_run_id']}"
    assert _report(client, run_id, newer)["discovery"]["status"] == "completed"
    again = client.post(path, json={})  # unchanged since: the new run is reused
    assert again.status_code == 200
    assert again.json()["discovery_run_id"] == second.json()["discovery_run_id"]


def test_a_review_that_changes_nothing_discovery_would_send_keeps_the_stored_run(
    model: tuple[TestClient, Spy],
) -> None:
    """Through the real review API: "needs more information" leaves the finding in and its
    check's track record as it was, so the same positions and reminders would be sent."""
    client, spy = model
    run_id = _run(client)
    path = f"{API}/validation-runs/{run_id}/risks/discovery-runs"
    first = client.post(path, json={}).json()
    before = _report(client, run_id)
    _review(client, _issue_of_a_reminder(client, run_id), "needs_more_information")
    assert _ids(_report(client, run_id)) == _ids(before)
    asked = len(spy.prompts)
    query = f"?discovery_run_id={first['discovery_run_id']}"
    assert _report(client, run_id, query)["discovery"]["status"] == "completed"
    again = client.post(path, json={})
    assert (
        again.status_code == 200 and again.json()["discovery_run_id"] == first["discovery_run_id"]
    )
    assert len(spy.prompts) == asked


def test_a_background_run_is_polled_and_a_second_start_reuses_it(
    model: tuple[TestClient, Spy],
) -> None:
    client, spy = model
    run_id = _run(client)
    path = f"{API}/validation-runs/{run_id}/risks/discovery-runs"
    queued = client.post(path, json={}, headers={"Prefer": "respond-async"})
    assert queued.status_code == 202 and queued.headers["preference-applied"] == "respond-async"
    first = queued.json()["discovery_run_id"]
    second = client.post(path, json={}, headers={"Prefer": "respond-async"})
    assert second.status_code == 200 and second.json()["discovery_run_id"] == first
    for _ in range(200):
        polled = client.get(f"{path}/{first}").json()
        if polled["status"] in ("finished", "failed"):
            break
        time.sleep(0.02)
    assert polled["status"] == "finished" and polled["discovery"]["status"] == "completed"
    assert len(spy.prompts) == len(polled["exchanges"])  # one run's requests only


def test_two_starts_at_once_run_the_model_once(model: tuple[TestClient, Spy]) -> None:
    from app.risk.service import start_discovery

    client, spy = model
    run_id = _run(client)
    wb = client.app.state.workbench  # type: ignore[attr-defined]

    def slow(prompt: str) -> str:
        time.sleep(0.05)
        return spy(prompt)

    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(
            pool.map(lambda _: start_discovery(wb, run_id, "paths", generator=slow), [1, 2])
        )
    assert runs[0][0].discovery_run_id == runs[1][0].discovery_run_id
    assert sorted(started for _, started in runs) == [False, True]
    assert len(spy.prompts) == len(runs[0][0].exchanges or runs[1][0].exchanges)


def test_a_run_left_running_by_a_stopped_server_is_failed_when_read(
    model: tuple[TestClient, Spy],
) -> None:
    from app.risk import service

    client, _ = model
    run_id = _run(client)
    wb = client.app.state.workbench  # type: ignore[attr-defined]
    run = client.post(f"{API}/validation-runs/{run_id}/risks/discovery-runs", json={}).json()
    store = service._store(wb)
    stuck = store.get(run["discovery_run_id"])
    assert stuck is not None
    store.save(stuck.model_copy(update={"status": "running", "discovery": None}))
    read = client.get(
        f"{API}/validation-runs/{run_id}/risks/discovery-runs/{run['discovery_run_id']}"
    )
    assert read.json()["status"] == "failed" and "interrupted" in read.json()["error"]
    shown = _report(client, run_id, f"?discovery_run_id={run['discovery_run_id']}")
    assert shown["discovery"]["status"] == "failed"


def test_illegal_sort_values_are_refused(client: TestClient) -> None:
    run_id = _run(client)
    for query in ("?sort_by=price", "?sort_order=up", "?sort_by=confidence&sort_order=ASC"):
        response = client.get(f"{API}/validation-runs/{run_id}/risks{query}")
        assert response.status_code == 422, query


def test_stated_source_coverage_is_kept_and_unknown_coverage_is_said(client: TestClient) -> None:
    from app.risk.models import SourceCoverage
    from app.risk.service import risk_report

    run_id = _run(client)
    wb = client.app.state.workbench  # type: ignore[attr-defined]
    unknown = risk_report(wb, run_id)
    assert unknown.sources is None and any(
        "It is not known which pages" in n for n in unknown.notes
    )
    assert any("DIN 276" in n and "none is assigned" in n for n in unknown.notes)
    given = SourceCoverage(
        stated_by="a test", not_read=["pages 3-5"], not_provided=["Anlage 2"], preface_read=False
    )
    report = risk_report(wb, run_id, sources=given)
    assert report.sources == given
    [note] = [n for n in report.notes if n.startswith("Source coverage")]
    assert "preliminary text not read" in note and "not read: pages 3-5" in note
    assert "not provided: Anlage 2" in note
    assert report.risks == unknown.risks  # coverage is stated, checks are unchanged


# ----------------------------------------------------------------------------- risk reviews
def test_a_decision_on_a_reminder_without_a_finding_is_kept_and_carried_to_the_next_run(
    client: TestClient,
) -> None:
    run_id = _run(client)
    question = next(r for r in _report(client, run_id)["risks"] if not r["source_issue_ids"])
    path = f"{API}/validation-runs/{run_id}/risk-reviews"
    assert client.get(path).json() == {"run_id": run_id, "items": []}

    saved = client.put(f"{path}/{question['risk_id']}", json={"status": "in_review"})
    assert saved.status_code == 200, saved.text
    approved = client.put(
        f"{path}/{question['risk_id']}", json={"status": "approved", "comment": "Asked the client."}
    ).json()
    assert approved["status"] == "approved" and approved["comment"] == "Asked the client."
    [item] = client.get(path).json()["items"]
    assert item["risk_id"] == question["risk_id"] and item["status"] == "approved"
    assert item["run_id"] == run_id and item["reviewed_at"]

    # A new run of the same document sees the decision: the reminder id is stable.
    dataset_id = client.get(f"{API}/validation-runs/{run_id}").json()["dataset_id"]
    _edit_first_description(client, dataset_id)
    second = client.post(f"{API}/datasets/{dataset_id}/validation-runs").json()["run_id"]
    assert second != run_id
    assert question["risk_id"] in {r["risk_id"] for r in _report(client, second)["risks"]}
    [carried] = client.get(f"{API}/validation-runs/{second}/risk-reviews").json()["items"]
    assert carried["status"] == "approved"

    back = client.put(f"{path}/{question['risk_id']}", json={"status": "open"}).json()
    assert back["status"] == "open"


def test_a_decision_on_an_unknown_run_or_with_a_bad_id_or_status_is_refused(
    client: TestClient,
) -> None:
    run_id = _run(client)
    path = f"{API}/validation-runs/{run_id}/risk-reviews"
    assert client.get(f"{API}/validation-runs/run_missing/risk-reviews").status_code == 404
    missing = client.put(
        f"{API}/validation-runs/run_missing/risk-reviews/risk_0123456789abcdef",
        json={"status": "approved"},
    )
    assert missing.status_code == 404
    assert client.put(f"{path}/not-a-risk", json={"status": "approved"}).status_code == 422
    assert client.put(f"{path}/risk_0123456789abcdef", json={"status": "done"}).status_code == 422


# ----------------------------------------------------------------------------- same cause
# Real detectors on an uploaded bill: the tender detectors (findings) and the risk text rules
# can report one cause on one position; they are one reminder only when position, cause (risk
# type) and kind of check agree.
SAME_CAUSE_ROWS: list[list[Any]] = [
    ["OZ", "Kurztext", "Langtext", "Menge", "ME", "EP (EUR)", "GP (EUR)"],
    ["01", "Titel 01 Leitungen"],
    [
        "01.0010",
        "PE-Rohr DN 150 liefern",
        "PE-Rohr DN 300 liefern und verlegen. Abrechnung nach m2.",
        "20",
        "m",
        "50,00",
        "1.000,00",
    ],
    [
        "01.0020",
        "Kunststoffrohr DN 200 verlegen",
        "Rohr DN 400 aus PE verlegen.",
        "10",
        "m",
        "60,00",
        "600,00",
    ],
    [
        "01.0030",
        "Wasserhaltung nach Bedarf pauschal",
        "Wasserhaltung der Baugrube nach Bedarf, seperat vorhalten.",
        "1",
        "psch",
        "900,00",
        "900,00",
    ],
    [
        "01.0040",
        "Schachtabdeckung liefern",
        "Schachtabdeckung Klasse D 400 nach Absprache liefern und einbauen.",
        "2",
        "St",
        "300,00",
        "600,00",
    ],
]


def _same_cause_run(client: TestClient) -> str:
    dataset = _upload(client, _csv(SAME_CAUSE_ROWS), "Leitungen.csv").json()["dataset"]
    return client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()["run_id"]  # type: ignore[no-any-return]


def test_different_causes_in_one_text_stay_apart_and_one_cause_merges(client: TestClient) -> None:
    on_it = _about(_report(client, _same_cause_run(client)), "01.0030")
    # "nach Bedarf" in a lump sum: read once (wording.yaml 0.7 left it to domain.boq_clauses).
    [scope] = [r for r in on_it if r["risk_type"] == "R090"]
    assert "domain.boq_clauses:open_lump_sum" in scope["rules"] and "V05" not in scope["rules"]
    assert scope["factors"]["independent_signals"] == 1
    # The misspelling is in the same text cell, but it is another cause.
    [typo] = [r for r in on_it if any(x.startswith("domain.boq_typos") for x in r["rules"])]
    assert typo["risk_id"] != scope["risk_id"] and not set(typo["rules"]) & set(scope["rules"])


def test_a_decision_left_open_is_one_reminder(client: TestClient) -> None:
    [risk] = [
        r
        for r in _about(_report(client, _same_cause_run(client)), "01.0040")
        if r["risk_type"] == "R036"
    ]  # "nach Absprache": the detector's open_decision; V01 no longer reads it (wording 0.7)
    assert risk["rules"] == ["domain.boq_description_clarity:open_decision"]
    assert risk["factors"]["independent_signals"] == 1


def test_model_hypotheses_never_change_the_base_queue(model: tuple[TestClient, Spy]) -> None:
    """Base report A against the same run with a stored discovery run applied: the checks'
    tasks (main list, their questions, their record entries) keep order, tier, evidence and
    money; the model's own hypotheses come after them as experimental supplements, all listed
    and counted; a hypothesis the model named the same cause is a hint, not a confirmation."""
    client, spy = model
    run_id = _run(client)
    before = _report(client, run_id)
    started = client.post(f"{API}/validation-runs/{run_id}/risks/discovery-runs", json={})
    assert started.status_code == 201, started.text
    asked = len(spy.prompts)
    applied = _report(client, run_id, f"?discovery_run_id={started.json()['discovery_run_id']}")
    assert len(spy.prompts) == asked  # reading applies the stored run, it asks nothing
    assert applied["risks"] == before["risks"]
    experimental = [q for q in applied["open_questions"] if q["experimental"]]
    base = [q for q in applied["open_questions"] if not q["experimental"]]
    assert experimental and all(q["source"] == "discovery" for q in experimental)
    assert base == before["open_questions"] and applied["open_questions"] == base + experimental
    assert applied["counts"]["open_questions_from_discovery"] == len(experimental)

    def facts(r: dict[str, Any]) -> tuple[Any, ...]:
        return (
            r["risk_id"],
            r["rank"],
            r["tier"],
            r["state"],
            r["evidence_class"],
            r["money"],
            r["factors"],
            r["rules"],
            r["methods"],
        )

    ours = [r for r in applied["record"] if r["methods"] == ["guided_llm"]]
    theirs = [r for r in applied["record"] if r["methods"] != ["guided_llm"]]
    assert [facts(r) for r in theirs] == [facts(r) for r in before["record"]]
    assert applied["record"] == theirs + ours  # supplements last, every one still listed
    assert all(r["state"] == "cannot_tell" and r["money"]["kind"] == "unknown" for r in ours)
