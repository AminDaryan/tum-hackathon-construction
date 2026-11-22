"""Project contracts through the real upload, persistence and background validation APIs."""

import json
import time
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import JobSettings
from app.core.ids import RandomIdFactory
from app.main import create_app
from app.models.project import Project, ProjectFile
from app.services import projects
from tests.integration.test_api import _csv, _upload, _workbench
from tests.integration.test_risk_api import ROWS

# Priorities, the most severe first.
SEVERITIES = ["critical", "high", "medium", "low", "info"]


@pytest.mark.parametrize("sqlite", [False, True])
def test_project_files_references_validation_and_shared_membership(
    tmp_path: Path, sqlite: bool
) -> None:
    wb = _workbench(tmp_path, sqlite=sqlite)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post("/api/v1/projects", json={"name": "Tender A"}).json()
        other = client.post("/api/v1/projects", json={"name": "Tender B"}).json()
        project_url = f"/api/v1/projects/{project['project_id']}"
        docs = []
        # Same position, but a different trade and mere decimal precision must not conflict.
        for name, rows in [
            ("bill.csv", "1;Pipe;10;m;7;75\n2;Valve;2;St;8;16\n"),
            ("reference.csv", "1;Pipe;12;m;7.00;84\n2;Valve;2.0;St;8.0;16\n"),
            ("other-trade.csv", "1;Paint;999;m;5;4995\n"),
        ]:
            response = client.post(
                "/api/v1/documents",
                files={"file": (name, "Item;Description;Quantity;Unit;Unit price;Total\n" + rows)},
            )
            assert response.status_code == 201, response.text
            doc = response.json()["document"]
            assert doc["dataset_id"] is not None
            docs.append(doc["document_id"])
            response = client.put(
                project_url + "/documents",
                json={
                    "document_id": docs[-1],
                    "role": "reference" if name == "reference.csv" else "bill",
                },
            )
            assert response.status_code == 200
        # Sharing never re-uploads or moves an original; repeated membership is idempotent.
        for _ in range(2):
            client.put(
                f"/api/v1/projects/{other['project_id']}/documents", json={"document_id": docs[0]}
            )
        assert len(client.get(project_url).json()["documents"]) == 3
        assert len(client.get(f"/api/v1/projects/{other['project_id']}").json()["documents"]) == 1
        # Bills get the table view; a person can move a file to the supporting documents, which
        # validation skips instead of validating it as a bill.
        assert client.get(project_url).json()["groups"] == dict.fromkeys(docs, "bill")
        moved = client.patch(project_url + f"/documents/{docs[2]}", json={"group": "support"})
        assert moved.status_code == 200, moved.text
        assert client.post(project_url + "/validation").status_code == 202
        wb.jobs.shutdown()  # wait for this small real validation, not a mocked pipeline
        result = client.get(project_url).json()["project"]["validation"]
        assert result["status"] == "completed", result
        assert set(result["runs"]) == {docs[0]}
        assert docs[1] in result["skipped"]
        assert result["skipped"][docs[2]] == "Supporting document"
        assert len(result["comparisons"]) == 1, result["comparisons"]
        difference = result["comparisons"][0]
        assert difference["field"] == "quantity" and difference["item_code"] == "1"
        assert difference["documents"] == docs[:2]
        assert difference["values"] == ["10", "12"]
        # Dashboard counts reflect actual pending decisions, not the immutable run total.
        run_id = result["runs"][docs[0]]
        issues = client.get(f"/api/v1/validation-runs/{run_id}/issues?limit=500").json()["items"]
        pending = [issue for issue in issues if issue["review_status"] == "pending_review"]
        assert pending
        counts = client.get(project_url).json()["review_counts"]
        assert docs[1] not in counts  # reference documents are not bill-validated
        assert counts[docs[0]] == {
            "to_review": len(pending),
            "high_priority": sum(issue["severity"] in {"high", "critical"} for issue in pending),
            "findings": len(issues),
            "by_severity": dict(Counter(issue["severity"] for issue in issues)),
        }
        issue = pending[0]
        decision = client.post(
            f"/api/v1/issues/{issue['issue_id']}/review",
            json={"status": "false_positive", "expected_version": issue["version"]},
        )
        assert decision.status_code == 200, decision.text
        updated = client.get(project_url).json()["review_counts"][docs[0]]
        assert updated["to_review"] == len(pending) - 1
        assert updated["findings"] == len(issues)  # a decision does not remove the finding
        assert updated["high_priority"] == counts[docs[0]]["high_priority"] - (
            issue["severity"] in {"high", "critical"}
        )
        for run_id in result["runs"].values():
            assert client.get(f"/api/v1/validation-runs/{run_id}").status_code == 200
        # A file moved out of the bills leaves the last validation's results.
        moved = client.patch(project_url + f"/documents/{docs[0]}", json={"group": "support"})
        assert moved.status_code == 200, moved.text
        assert docs[0] not in moved.json()["validation"]["runs"]
        assert client.get(project_url).json()["groups"][docs[0]] == "support"
        assert (
            client.patch(project_url + "/documents/missing", json={"group": "bill"}).status_code
            == 404
        )
        assert client.delete(project_url + f"/documents/{docs[0]}").status_code == 200
        assert client.get(f"/api/v1/documents/{docs[0]}").status_code == 200
        assert client.get(project_url).json()["project"]["validation"] is None
        assert (
            client.put(project_url + "/documents", json={"document_id": "missing"}).status_code
            == 404
        )
        assert client.post("/api/v1/projects", json={"name": "   "}).status_code == 422
    wb.close()
    if sqlite:
        # Membership survives a fresh process and schema preparation.
        reopened = _workbench(tmp_path, sqlite=True)
        with TestClient(create_app(workbench=reopened), base_url="http://localhost") as client:
            assert len(client.get(project_url).json()["documents"]) == 2
        reopened.close()


def test_a_bid_is_checked_again_against_the_tender_added_to_or_removed_from_its_project(
    tmp_path: Path,
) -> None:
    """The bid is validated on upload, before its tender is in the project; adding the tender,
    removing it again, and taking the bid out of the project re-check the bid without being
    asked."""
    wb = _workbench(tmp_path, jobs=JobSettings(auto_validate=True))
    header = "Item;Description;Quantity;Unit;Unit price;Total\n"
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project_url = (
            "/api/v1/projects/"
            + (client.post("/api/v1/projects", json={"name": "Ringschluss"}).json()["project_id"])
        )

        def add(name: str, rows: str) -> str:
            upload = client.post("/api/v1/documents", files={"file": (name, header + rows)})
            assert upload.status_code == 201, upload.text
            document_id: str = upload.json()["document"]["document_id"]
            added = client.put(project_url + "/documents", json={"document_id": document_id})
            assert added.status_code == 200, added.text
            return document_id

        def comparison(document_id: str, status: str) -> list[str]:
            """The rules the tender comparison reported in the bid's latest run, once that run
            finished with the comparison in ``status``."""
            for _ in range(500):
                last = client.get(f"/api/v1/documents/{document_id}").json()["document"]
                run = last["last_run"]
                if run is not None and run["status"] not in {"queued", "running"}:
                    detail = client.get(f"/api/v1/validation-runs/{run['run_id']}").json()
                    [report] = [
                        r
                        for r in detail["detector_reports"]
                        if r["detector_id"] == "domain.boq_tender_comparison"
                    ]
                    if report["status"] == status:
                        issues = client.get(
                            f"/api/v1/validation-runs/{run['run_id']}/issues?limit=500"
                        ).json()["items"]
                        return sorted(
                            i["rule_id"]
                            for i in issues
                            if i["detector_id"] == "domain.boq_tender_comparison"
                        )
                time.sleep(0.01)
            raise AssertionError(f"no finished run with the comparison {status}")

        bid = add("Angebot.csv", "1.1;Rohr DN 250;30;m;100;3000\n1.2;Bogen 90;3;St;50;150\n")
        assert comparison(bid, "skipped") == []
        tender = add("Ausschreibung.csv", "1.1;Rohr DN 250;25;m;;\n1.2;Bogen 90;3;St;;\n")
        assert comparison(bid, "completed") == ["tender_quantity_changed"]
        assert client.delete(project_url + f"/documents/{tender}").status_code == 200
        assert comparison(bid, "skipped") == []
        assert client.put(project_url + "/documents", json={"document_id": tender}).is_success
        assert comparison(bid, "completed") == ["tender_quantity_changed"]
        assert client.delete(project_url + f"/documents/{bid}").status_code == 200
        assert comparison(bid, "skipped") == []
    wb.close()


def test_pdf_and_word_files_without_a_bill_table_are_supporting_documents() -> None:
    file = ProjectFile(document_id="doc_1")
    assert projects.group_of(file, "pdf", has_table=False) == "support"
    assert projects.group_of(file, "docx", has_table=False) == "support"
    assert projects.group_of(file, "pdf", has_table=True) == "bill"
    # A GAEB or Excel bill stays a bill even when reading it failed: its error matters.
    assert projects.group_of(file, "gaeb_x83", has_table=False) == "bill"
    assert projects.group_of(file, "xlsx", has_table=False) == "bill"
    assert projects.group_of(file.evolve(group="support"), "xlsx", has_table=True) == "support"
    assert projects.group_of(file.evolve(group="bill"), "pdf", has_table=False) == "bill"


@pytest.mark.parametrize("sqlite", [False, True])
def test_project_details_assignees_and_status(tmp_path: Path, sqlite: bool) -> None:
    wb = _workbench(tmp_path, sqlite=sqlite)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        created = client.post(
            "/api/v1/projects",
            json={
                "name": " Riverside tender ",
                "description": " Bridge works, 3 bills. ",
                "assignees": ["Amin", " Larissa_S ", "amin"],
            },
        )
        assert created.status_code == 201, created.text
        project = created.json()
        assert project["name"] == "Riverside tender"
        assert project["description"] == "Bridge works, 3 bills."
        # The same reviewer in another case is kept once, with the first spelling.
        assert project["assignees"] == ["Amin", "Larissa_S"]
        assert project["status"] == "in_progress"
        url = f"/api/v1/projects/{project['project_id']}"
        for bad in (["Larissa Stoll"], ["1st"], ["x" * 33], [f"N{i}" for i in range(21)]):
            response = client.post("/api/v1/projects", json={"name": "B", "assignees": bad})
            assert response.status_code == 422, bad

        finished = client.patch(url, json={"status": "finished"})
        assert finished.status_code == 200, finished.text
        assert finished.json()["status"] == "finished"
        assert finished.json()["assignees"] == ["Amin", "Larissa_S"]  # left out, left as is
        changed = client.patch(url, json={"assignees": ["Larissa_S"], "description": ""}).json()
        assert changed["assignees"] == ["Larissa_S"] and changed["description"] == ""
        assert changed["name"] == "Riverside tender" and changed["status"] == "finished"
        reopened = client.patch(url, json={"status": "in_progress", "name": "Riverside 2"}).json()
        assert (reopened["status"], reopened["name"]) == ("in_progress", "Riverside 2")
        listed = {p["project_id"]: p for p in client.get("/api/v1/projects").json()}
        assert listed[project["project_id"]]["assignees"] == ["Larissa_S"]
        assert client.get(url).json()["project"]["name"] == "Riverside 2"

        assert client.patch(url, json={"status": "done"}).status_code == 422
        assert client.patch(url, json={"name": "  "}).status_code == 422
        assert client.patch(url, json={"files": []}).status_code == 422
        assert client.patch(url, json={"assignees": ["no spaces"]}).status_code == 422
        assert client.patch("/api/v1/projects/prj_missing", json={"name": "X"}).status_code == 404
    wb.close()
    if sqlite:
        reopened_wb = _workbench(tmp_path, sqlite=True)
        with TestClient(create_app(workbench=reopened_wb), base_url="http://localhost") as client:
            stored = client.get(url).json()["project"]
            assert (stored["status"], stored["assignees"]) == ("in_progress", ["Larissa_S"])
        reopened_wb.close()


def test_projects_stored_before_status_and_assignees_load_with_defaults() -> None:
    stored = {
        "project_id": "prj_old",
        "name": "Old tender",
        "description": "",
        "created_at": "2026-11-21T10:00:00Z",
        "files": [],
        "demo_key": None,
        "preparation": "ready",
        "preparation_error": None,
        "validation": None,
    }
    project = Project.model_validate(stored)
    assert (project.status, project.assignees) == ("in_progress", [])


def test_project_exports_cover_every_bill_of_the_last_validation(tmp_path: Path) -> None:
    import csv
    import io

    from openpyxl import load_workbook

    wb = _workbench(tmp_path, sqlite=False)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post("/api/v1/projects", json={"name": "Brücke Nord"}).json()
        url = f"/api/v1/projects/{project['project_id']}"
        names = ["first.csv", "second.csv"]
        for name in names:
            doc = client.post(
                "/api/v1/documents",
                files={
                    "file": (
                        name,
                        "Item;Description;Quantity;Unit;Unit price;Total\n1;Pipe;10;m;7;75\n",
                    )
                },
            ).json()["document"]
            client.put(url + "/documents", json={"document_id": doc["document_id"]})
        # Nothing to report before the project is validated.
        assert client.get(url + "/export/pdf").status_code == 409
        assert client.post(url + "/validation").status_code == 202
        wb.jobs.shutdown()
        validation = client.get(url).json()["project"]["validation"]
        assert validation["status"] == "completed"
        assert client.get(url + "/export/docx").status_code == 404

        pdf = client.get(url + "/export/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert "Nord report.pdf" in pdf.headers["content-disposition"]
        assert pdf.content.startswith(b"%PDF-")

        sheet = client.get(url + "/export/xlsx")
        assert sheet.status_code == 200
        rows = list(load_workbook(io.BytesIO(sheet.content))["Issues"].iter_rows(values_only=True))
        assert rows[0][:2] == ("File", "Severity")
        assert {row[0] for row in rows[1:]} == set(names)

        table = client.get(url + "/export/issues.csv")
        assert table.status_code == 200
        records = list(csv.reader(io.StringIO(table.content.decode("utf-8-sig"))))
        assert records[0][:2] == ["file", "validation_run_id"]
        assert {record[0] for record in records[1:]} == set(names)
        assert len(records) - 1 == len(rows) - 1  # the same findings in both

        # One bill's report through the run export.
        run_id = validation["runs"][next(iter(validation["runs"]))]
        report = client.get(f"/api/v1/validation-runs/{run_id}/export/pdf")
        assert report.status_code == 200 and report.content.startswith(b"%PDF-")
    wb.close()


@pytest.mark.parametrize("sqlite", [False, True])
def test_top_issues_and_kept_reports_of_a_validated_project(tmp_path: Path, sqlite: bool) -> None:
    wb = _workbench(tmp_path, sqlite=sqlite)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        project = client.post("/api/v1/projects", json={"name": "Tender"}).json()
        url = f"/api/v1/projects/{project['project_id']}"
        bill = _upload(client, _csv(ROWS), "Rohbau.csv").json()["document"]["document_id"]
        client.put(url + "/documents", json={"document_id": bill})
        # Nothing to rank or report before the project is validated.
        assert client.get(url + "/top-issues").status_code == 409
        assert client.post(url + "/reports", json={"format": "pdf"}).status_code == 409
        assert client.get(url + "/reports").json() == {"items": []}
        assert client.post(url + "/validation").status_code == 202
        wb.jobs.shutdown()
        run_id = client.get(url).json()["project"]["validation"]["runs"][bill]

        # The open findings, the most severe first, then the largest financial impact.
        assert client.get(url + "/top-issues?limit=0").status_code == 422
        assert client.get(url + "/top-issues?limit=101").status_code == 422
        assert client.get(url + "/top-issues?offset=-1").status_code == 422
        page = client.get(
            f"/api/v1/validation-runs/{run_id}/issues?review_status=pending_review&limit=500"
        ).json()
        listed = client.get(url + "/top-issues?limit=100").json()
        top = listed["items"]
        assert listed["total"] == page["total"] and len(top) == min(100, page["total"]) and top
        assert {issue["validation_run_id"] for issue in top} == {run_id}
        ranks = [SEVERITIES.index(issue["severity"]) for issue in top]
        assert ranks == sorted(ranks)
        for severity in {issue["severity"] for issue in top}:
            same = [issue for issue in top if issue["severity"] == severity]
            # A comparison with reference prices is not money lost: it ranks with the findings
            # without an impact.
            costs = [
                issue["estimated_financial_impact"]
                if issue["estimated_financial_impact"]
                and issue["estimated_financial_impact"]["kind"] != "reference_deviation"
                else None
                for issue in same
            ]
            amounts = [abs(Decimal(cost["amount"])) for cost in costs if cost]
            assert amounts == sorted(amounts, reverse=True)
            assert all(costs[: len(amounts)])
        assert len(client.get(url + "/top-issues").json()["items"]) == min(5, page["total"])
        # Pages follow on from each other.
        second = client.get(url + "/top-issues?limit=2&offset=2").json()
        assert second["total"] == page["total"]
        assert [issue["issue_id"] for issue in second["items"]] == [
            issue["issue_id"] for issue in top[2:4]
        ]

        # Reports are kept, newest first, and their files download again.
        assert client.post(url + "/reports", json={"format": "docx"}).status_code == 422
        missing = client.post(url + "/reports", json={"format": "pdf", "document_id": "doc_x"})
        assert missing.status_code == 404
        whole = client.post(url + "/reports", json={"format": "pdf"})
        assert whole.status_code == 201, whole.text
        one = client.post(url + "/reports", json={"format": "issues.csv", "document_id": bill})
        assert one.status_code == 201, one.text
        # The bid risk report covers the whole project only.
        bid_of_bill = {"format": "bid-risk.pdf", "document_id": bill}
        assert client.post(url + "/reports", json=bid_of_bill).status_code == 422
        bid = client.post(url + "/reports", json={"format": "bid-risk.pdf"})
        assert bid.status_code == 201, bid.text
        listed = client.get(url + "/reports").json()["items"]
        assert [r["report_id"] for r in listed] == [
            bid.json()["report_id"],
            one.json()["report_id"],
            whole.json()["report_id"],
        ]
        assert (listed[0]["format"], listed[0]["document_id"]) == ("bid-risk.pdf", None)
        assert listed[0]["filename"].endswith("-bid-risk-report.pdf")
        bid_pdf = client.get(f"{url}/reports/{bid.json()['report_id']}/file")
        assert bid_pdf.status_code == 200 and bid_pdf.content.startswith(b"%PDF-")
        assert bid_pdf.headers["content-type"] == "application/pdf"
        listed = listed[1:]
        assert (listed[0]["format"], listed[0]["document_id"]) == ("issues.csv", bill)
        assert (listed[1]["format"], listed[1]["document_id"]) == ("pdf", None)
        assert "storage_key" in listed[1] and listed[1]["filename"].endswith(" report.pdf")
        pdf = client.get(f"{url}/reports/{whole.json()['report_id']}/file")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        assert pdf.headers["content-type"] == "application/pdf"
        assert listed[1]["filename"] in pdf.headers["content-disposition"]
        assert len(pdf.content) == listed[1]["size_bytes"]
        csv_file = client.get(f"{url}/reports/{one.json()['report_id']}/file")
        assert csv_file.status_code == 200 and csv_file.headers["content-type"].startswith(
            "text/csv"
        )
        assert client.get(f"{url}/reports/rpt_missing/file").status_code == 404
    wb.close()
