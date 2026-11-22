"""The bid risk report of a project end to end (issue #112): upload a bill and a reference, add
them to a project, validate it, ask for the report and its PDF, reject a reminder.

The bill is the synthetic one of test_risk_api; its line totals add up to 32,340.00 EUR and its
five largest to 21,600.00 EUR (6,600 + 5,000 + 3,600 + 3,600 + 2,800).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.integration.test_api import API, _csv, _upload, _workbench
from tests.integration.test_risk_api import ROWS
from tests.unit.risk.test_bid_report_pdf import pdf_text


def test_the_bid_report_ranks_the_positions_of_a_validated_project(tmp_path: Path) -> None:
    wb = _workbench(tmp_path)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(f"{API}/projects", json={"name": "Tender"}).json()
        project_url = f"{API}/projects/{project['project_id']}"
        url = f"{project_url}/risk-report"
        assert client.get(f"{API}/projects/prj_missing/risk-report").status_code == 404
        assert client.get(url).status_code == 409  # not validated yet
        assert client.get(f"{url}/pdf").status_code == 409
        assert client.get(f"{url}?limit=0").status_code == 422
        ids = {}
        for name, rows, role in (
            ("Rohbau.csv", ROWS, "bill"),
            ("Referenz.csv", ROWS[:7], "reference"),
        ):
            document = _upload(client, _csv(rows), name).json()["document"]
            ids[role] = document["document_id"]
            client.put(f"{project_url}/documents", json={"document_id": ids[role], "role": role})
        assert client.post(f"{project_url}/validation").status_code == 202
        wb.jobs.shutdown()  # wait for the real validation

        response = client.get(f"{url}?limit=5")
        assert response.status_code == 200, response.text
        report = response.json()
        rows = report["positions"]
        assert report["limit"] == 5 and len(rows) == 5
        assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5]
        named = min(report["positions_with_reminders"], 5)
        assert [r["kind"] for r in rows] == ["reminders"] * named + ["largest"] * (5 - named)
        # The arithmetic error keeps its exact money apart from the position's line total.
        arithmetic = next(r for r in rows if r["label"] == "01.01.0020")
        assert arithmetic["document_name"] == "Rohbau.csv"
        assert arithmetic["line_total"] == "2600.00"
        # Reports and their PDF reuse the risk question.
        arithmetic_question = next(
            m["question"]
            for m in arithmetic["reminders"]
            if "unit price" in (m["question"] or "").lower()
        )
        assert arithmetic_question and "confirm" in arithmetic_question.lower()
        risk_report = client.get(f"{API}/validation-runs/{arithmetic['run_id']}/risks").json()
        original = next(
            r for r in [*risk_report["risks"], *risk_report["record"]] if r["risk_type"] == "R076"
        )
        assert arithmetic_question == original["question"]
        assert {(m["money"]["kind"], m["money"]["amount"]) for m in arithmetic["reminders"]} >= {
            ("exact", "100.00")
        }
        added = [Decimal(r["line_total"]) for r in rows if r["kind"] == "largest"]
        assert added == sorted(added, reverse=True)
        assert Decimal(report["largest_share"]).quantize(Decimal("0.0001")) == Decimal("0.6679")
        (bill,) = report["bills"]
        assert (bill["document_name"], bill["priced"], bill["counted_total"]) == (
            "Rohbau.csv",
            True,
            "32340.00",
        )
        (skipped,) = report["skipped"]
        assert (skipped["document_id"], skipped["document_name"]) == (
            ids["reference"],
            "Referenz.csv",
        )
        assert skipped["reason"].startswith("Reference")

        # The same report as a PDF attachment, its positions in the same order.
        pdf = client.get(f"{url}/pdf?limit=5")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert "Tender-bid-risk-report.pdf" in pdf.headers["content-disposition"]
        text = " ".join(pdf_text(pdf.content).split())
        assert "Bid risk report: Tender" in text
        assert arithmetic_question in text
        places = [text.index(f"{r['rank']} {r['label']}") for r in rows]  # rank, then position
        assert places == sorted(places)

        # A reminder reviewers rejected leaves the report.
        rejected = rows[0]["reminders"][0]["risk_id"]
        decided = client.put(
            f"{API}/validation-runs/{bill['run_id']}/risk-reviews/{rejected}",
            json={"status": "rejected"},
        )
        assert decided.status_code == 200, decided.text
        after = client.get(url).json()
        shown = {m["risk_id"] for r in after["positions"] for m in r["reminders"]}
        shown |= {o["reminder"]["risk_id"] for o in after["other_reminders"]}
        assert rejected not in shown
        assert after["bills"][0]["rejected"] == 1
        assert "1 reminder that reviewers rejected is left out." in after["notes"]

        # A validation that stopped part-way still gives the bid risk report of the bills it
        # validated, as a kept report too; the other report types wait for a whole validation.
        with wb.uow() as uow:
            stored = uow.projects.get(project["project_id"])
            assert stored is not None and stored.validation is not None
            failed = stored.validation.evolve(status="failed", error="The server stopped.")
            uow.projects.update(stored.evolve(validation=failed))
        reports = f"{project_url}/reports"
        assert client.post(reports, json={"format": "pdf"}).status_code == 409
        kept = client.post(reports, json={"format": "bid-risk.pdf"})
        assert kept.status_code == 201, kept.text
        assert kept.json()["filename"].endswith("-bid-risk-report.pdf")
        notes = client.get(url).json()["notes"]
        assert any(note.startswith("The project's last validation failed") for note in notes)


def test_the_bid_report_shows_units_as_the_bill_writes_them(tmp_path: Path) -> None:
    # The unit vocabulary reads "St" as "pcs" and "psch" as "ls"; the report showed those ids.
    written = {"01.01.0020": "St", "02.0040": "psch"}
    rows = [
        [*row[:3], written[row[0]], *row[4:]] if row and row[0] in written else row for row in ROWS
    ]
    wb = _workbench(tmp_path)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post(f"{API}/projects", json={"name": "Tender"}).json()
        project_url = f"{API}/projects/{project['project_id']}"
        document = _upload(client, _csv(rows), "Rohbau.csv").json()["document"]
        client.put(
            f"{project_url}/documents",
            json={"document_id": document["document_id"], "role": "bill"},
        )
        assert client.post(f"{project_url}/validation").status_code == 202
        wb.jobs.shutdown()
        report = client.get(f"{project_url}/risk-report?limit=20").json()
        units = {row["label"]: row["unit"] for row in report["positions"]}
        assert {label: units[label] for label in written} == written
