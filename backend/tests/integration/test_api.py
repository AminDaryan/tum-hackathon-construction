"""The REST API end to end (``docs/api/rest-api.md``) through httpx, on in-memory storage."""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Iterator
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient

from app.api.routes._deps import content_disposition
from app.core.clock import FixedClock
from app.core.config import IngestionLimits, Settings
from app.core.ids import SequentialIdFactory
from app.main import create_app
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.schemas.exports import JsonExport
from app.services.workbench import Workbench, build_workbench
from app.storage.file_store import LocalFileStore
from tests.unit.normalization.raw_builders import GERMAN_LV
from tests.unit.repositories.postgres import POSTGRESQL, backends, fresh_postgres_url

pytestmark = pytest.mark.integration
API = "/api/v1"


def _csv(rows: list[list[Any]]) -> bytes:
    """A semicolon CSV as a German spreadsheet exports it: every record padded to full width."""
    width = max(len(row) for row in rows)
    cells = [["" if value is None else str(value) for value in row] for row in rows]
    lines = [";".join(row + [""] * (width - len(row))) for row in cells]
    return ("\n".join(lines) + "\n").encode("utf-8")


GERMAN_CSV = _csv(GERMAN_LV)
_DEFECTIVE = deepcopy(GERMAN_LV)
[_TAX] = [row for row in _DEFECTIVE if len(row) > 1 and row[1] == "zzgl. 19 % MwSt."]
_TAX[5] = "3.036,20"  # digits swapped: 19 % of 16.122,10 is 3.063,20
DEFECTIVE_CSV = _csv(_DEFECTIVE)


def _workbench(
    tmp_path: Path, *, sqlite: bool = False, postgresql: bool = False, **settings: Any
) -> Workbench:
    """In-memory repositories, or (``sqlite``) the real SQLite database under ``tmp_path``, or
    (``postgresql``) the emptied PostgreSQL test database (``TWB_TEST_DATABASE_URL``)."""
    if postgresql:
        settings["database_url"] = fresh_postgres_url()
    return build_workbench(
        Settings(data_dir=tmp_path, environment="test", **settings),
        uow=None if sqlite or postgresql else InMemoryUnitOfWorkFactory(InMemoryDatabase()),
        files=LocalFileStore(tmp_path),
        ids=SequentialIdFactory(),
        clock=FixedClock(),
    )


@pytest.fixture(params=backends("memory", "sqlite"))
def client(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TestClient]:
    workbench = _workbench(
        tmp_path, sqlite=request.param == "sqlite", postgresql=request.param == POSTGRESQL
    )
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as test_client:
        yield test_client
    workbench.close()


def _upload(client: TestClient, content: bytes, name: str = "Angebot März.csv") -> Any:
    return client.post(f"{API}/documents", files={"file": (name, content, "text/csv")})


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error  # type: ignore[no-any-return]


def test_system_and_catalogue(client: TestClient) -> None:
    health = client.get(f"{API}/health").json()
    assert health["status"] == "ok"
    assert set(health["profiles"]) >= {"boq", "generic"}
    assert health["unavailable_detectors"] == []
    assert health["ai_planner"] == {
        "configured": False,
        "note": "Adaptive AI planning is not available in this version; every registered "
        "check runs.",
    }
    assert health["default_profile_id"] == "boq" and health["auth_required"] is False
    ocr = health["ocr"]  # text recognition for scanned PDFs: reported, whether or not installed
    assert ocr["languages"] == "deu+eng" and isinstance(ocr["available"], bool)
    assert ocr["available"] or ocr["reason"]
    [boq] = [p for p in client.get(f"{API}/profiles").json()["items"] if p["profile_id"] == "boq"]
    assert boq["unit_count"] > 0 and any(f["field_id"] == "line_total" for f in boq["fields"])
    detectors = client.get(f"{API}/detectors").json()["items"]
    assert health["detector_count"] == len(detectors)
    one = client.get(f"{API}/detectors/deterministic.grand_total").json()
    assert one["spec"]["detector_id"] == "deterministic.grand_total"
    assert set(one["plannable_parameters"]) == {"total_field", "severity", "max_reference_cells"}
    assert one["default_config"]["check_tax_lines"] is True
    _error(client.get(f"{API}/detectors/nope"), 404, "not_found")
    _error(client.get(f"{API}/no-such-route"), 404, "not_found")


def test_upload_inspect_and_validate_a_clean_bill(client: TestClient) -> None:
    created = _upload(client, GERMAN_CSV)
    assert created.status_code == 201, created.text
    document, dataset = created.json()["document"], created.json()["dataset"]
    assert document["processing_status"] == "processed" and document["format"] == "csv"
    assert document["original_filename"] == "Angebot März.csv" and document["last_run"] is None
    assert document["dataset_id"] == dataset["dataset_id"] and document["table_count"] == 1
    [table] = dataset["tables"]
    assert table["row_kind_counts"]["item"] == 5 and table["row_kind_counts"]["tax"] == 1
    assert dataset["required_fields_missing"] == {}

    later = _upload(client, DEFECTIVE_CSV, "Angebot April.csv").json()["document"]
    listed = client.get(f"{API}/documents").json()
    assert listed["total"] == 2 and listed["offset"] == 0 and listed["limit"] == 50
    assert [item["document_id"] for item in listed["items"]] == [
        later["document_id"],
        document["document_id"],
    ]  # newest first
    detail = client.get(f"{API}/documents/{document['document_id']}").json()
    assert detail["dataset"]["dataset_id"] == dataset["dataset_id"]

    ds = dataset["dataset_id"]
    assert client.get(f"{API}/datasets/{ds}").json() == dataset
    rows = client.get(f"{API}/datasets/{ds}/tables/{table['table_id']}/rows?limit=5").json()
    assert rows["total"] == table["row_count"] and len(rows["items"]) == 5
    assert rows["items"][0]["classification"]["kind"]
    assert all("section_row_id" in row and "section_path" in row for row in rows["items"])
    _error(client.get(f"{API}/datasets/{ds}/tables/tbl_nope/rows"), 404, "not_found")
    before = client.get(f"{API}/datasets/{ds}/summary").json()
    assert before["run"] is None and before["counts"]["total"] == 0

    run = client.post(f"{API}/datasets/{ds}/validation-runs")
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["status"] == "completed" and body["plan"]["planner"] == "baseline"
    # The bill has no error; its one finding lists its contingency position ("Bedarfsposition
    # Wasserhaltung") for the bidder to price at a rate that covers cost. The tender review
    # checks find nothing in it.
    assert body["issue_count"] == 1 and body["issue_counts"]["total"] == 1
    listed = client.get(f"{API}/validation-runs/{body['run_id']}/issues").json()["items"]
    assert [(i["detector_id"], i["severity"]) for i in listed] == [
        ("domain.boq_position_types", "low")
    ]
    # Every registered check runs and reports (ADR 0010).
    registered = [d["spec"]["detector_id"] for d in client.get(f"{API}/detectors").json()["items"]]
    assert sorted(r["detector_id"] for r in body["detector_reports"]) == sorted(registered)
    assert client.get(f"{API}/validation-runs/{body['run_id']}").json() == body
    _error(client.get(f"{API}/validation-runs/run_nope"), 404, "not_found")
    grand = [r for r in body["detector_reports"] if r["detector_id"] == "deterministic.grand_total"]
    assert grand[0]["coverage"]["tax_rows_consistent"] == 1
    after = client.get(f"{API}/datasets/{ds}/summary").json()
    assert after["run"]["run_id"] == body["run_id"] and after["run"]["planner"] == "baseline"
    document = client.get(f"{API}/documents/{document['document_id']}").json()["document"]
    assert document["last_run"]["run_id"] == body["run_id"]


def test_the_document_list_reads_stored_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing documents never decodes a dataset snapshot (a 20,000-row bill takes seconds and
    about 0.5 GB); only opening, validating or exporting one document loads its dataset."""
    workbench = _workbench(tmp_path, sqlite=True, persistence={"dataset_cache_entries": 0})
    app = create_app(workbench=workbench)
    with closing(workbench), TestClient(app, base_url="http://localhost") as client:
        dataset = _upload(client, GERMAN_CSV).json()["dataset"]

        def refuse(*_: object, **__: object) -> NoReturn:
            raise AssertionError("a dataset snapshot was decoded")

        monkeypatch.setattr("app.repositories.sql.datasets.decode_dataset", refuse)
        listed = client.get(f"{API}/documents")
    assert listed.status_code == 200, listed.text
    [item] = listed.json()["items"]
    assert item["table_count"] == len(dataset["tables"]) == 1
    assert item["row_count"] == sum(table["row_count"] for table in dataset["tables"]) > 0


def _edit_first_description(client: TestClient, ds: str) -> None:
    """Store the next revision with a changed description on the first position."""
    dataset = client.get(f"{API}/datasets/{ds}").json()
    [table] = dataset["tables"]
    column = next(c for c in table["columns"] if c["mapped_semantic_field"] == "description")
    rows = client.get(f"{API}/datasets/{ds}/tables/{table['table_id']}/rows").json()["items"]
    row = next(r for r in rows if r["cells"][column["column_id"]]["raw_value"])
    fix = {
        "table_id": table["table_id"],
        "row_id": row["row_id"],
        "column_id": column["column_id"],
        "raw_value": row["cells"][column["column_id"]]["raw_value"] + " (geprüft)",
    }
    edited = client.post(
        f"{API}/datasets/{ds}/corrections",
        json={"expected_revision": dataset["revision"], "corrections": [fix]},
    )
    assert edited.status_code == 200, edited.text


def test_review_findings_and_carry_decisions_forward(client: TestClient) -> None:
    ds = _upload(client, DEFECTIVE_CSV).json()["dataset"]["dataset_id"]
    run = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    assert run["issue_count"] == 3  # the two total errors and the list of contingency positions
    issues = client.get(f"{API}/validation-runs/{run['run_id']}/issues").json()
    assert issues["total"] == 3
    rules = {issue["rule_id"]: issue for issue in issues["items"]}
    assert set(rules) == {"tax_mismatch", "gross_total_mismatch", "contingency_and_hourly"}
    tax = rules["tax_mismatch"]
    assert tax["expected_value"] == "3063.20" and tax["version"] == 1
    undecided = ["confirmed_error", "dismissed", "false_positive", "needs_more_information"]
    assert tax["allowed_review_actions"] == undecided
    calculation = tax["evidence"][0]["calculation"]
    assert calculation["operation"] == "percentage" and calculation["exact_result"] == "3063.1990"
    filtered = client.get(
        f"{API}/validation-runs/{run['run_id']}/issues",
        params={"severity": ["high", "critical"], "detector_id": "deterministic.grand_total"},
    ).json()
    assert filtered["total"] == 2
    _error(client.get(f"{API}/validation-runs/run_nope/issues"), 404, "not_found")

    url = f"{API}/issues/{tax['issue_id']}/review"
    error = _error(client.post(url, json={"status": "pending_review", "expected_version": 1}),
                   409, "invalid_review_transition")  # fmt: skip
    assert error["details"]["current"] == "pending_review"
    _error(client.post(url, json={"status": "corrected", "expected_version": 1}),
           422, "invalid_input")  # fmt: skip
    confirmed = client.post(
        url, json={"status": "confirmed_error", "comment": "Zahlendreher", "expected_version": 1}
    )
    assert confirmed.status_code == 200, confirmed.text
    issue = confirmed.json()["issue"]
    assert issue["version"] == 2 and issue["effective_evidence_class"] == "human_confirmed_error"
    assert issue["allowed_review_actions"] == ["pending_review"]
    assert [event["action"] for event in confirmed.json()["history"]] == ["issue_reviewed"]
    shown = client.get(f"{API}/issues/{tax['issue_id']}").json()["issue"]
    assert shown["allowed_review_actions"] == ["pending_review"]
    error = _error(client.post(url, json={"status": "dismissed", "expected_version": 1}),
                   409, "conflict")  # fmt: skip
    assert error["details"]["current_version"] == 2

    # Nothing changed: the same run comes back, no run is created.
    again = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    assert again["run_id"] == run["run_id"]
    _edit_first_description(client, ds)
    second = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    assert second["dataset_revision"] == 2
    carried = client.get(
        f"{API}/validation-runs/{second['run_id']}/issues",
        params={"review_status": "confirmed_error"},
    ).json()["items"]
    assert len(carried) == 1 and carried[0]["reviewer_comment"] == "Zahlendreher"
    history = client.get(f"{API}/issues/{carried[0]['issue_id']}").json()["history"]
    assert history[0]["context"]["carried_from_issue_id"] == tax["issue_id"]
    runs = client.get(f"{API}/datasets/{ds}/validation-runs").json()["items"]
    assert [r["run_id"] for r in runs] == [second["run_id"], run["run_id"]]
    assert runs[0]["detectors"]["completed"] >= 10
    counts = client.get(f"{API}/datasets/{ds}/summary").json()["counts"]
    assert counts["total"] == 3 and counts["human_confirmed_error"] == 1
    assert counts["confirmed_rule_violation"] == 1 and counts["pending_review"] == 2


def test_findings_carry_and_filter_by_their_finding_category(client: TestClient) -> None:
    ds = _upload(client, DEFECTIVE_CSV).json()["dataset"]["dataset_id"]
    run = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    # The two wrong totals, and the list of the bill's contingency positions.
    assert run["issue_counts"]["by_finding_category"] == {"error": 2, "risk": 1}
    url = f"{API}/validation-runs/{run['run_id']}/issues"
    items = client.get(url).json()["items"]
    assert [issue["finding_category"] for issue in items] == ["error", "error", "risk"]

    def total(*categories: str) -> int:
        page = client.get(url, params={"finding_category": list(categories)})
        assert page.status_code == 200, page.text
        return int(page.json()["total"])

    assert total("error") == 2
    assert total("none") == 0  # findings about reading the file
    assert (total("risk", "inconsistency"), total("error", "none")) == (1, 2)
    combined = client.get(url, params={"finding_category": "error", "severity": "critical"})
    assert combined.json()["total"] == sum(issue["severity"] == "critical" for issue in items)
    _error(
        client.get(url, params={"finding_category": "mistake"}), 422, "request_validation_failed"
    )
    detail = client.get(f"{API}/validation-runs/{run['run_id']}").json()
    assert detail["issue_counts"]["by_finding_category"] == {"error": 2, "risk": 1}

    reviewed = client.post(
        f"{API}/issues/{items[0]['issue_id']}/review",
        json={"status": "false_positive", "expected_version": 1},
    )
    assert reviewed.json()["issue"]["finding_category"] == "error"  # a review does not change it


def test_exports(client: TestClient) -> None:
    ds = _upload(client, DEFECTIVE_CSV).json()["dataset"]["dataset_id"]
    run_id = client.post(f"{API}/datasets/{ds}/validation-runs").json()["run_id"]
    issues = client.get(f"{API}/validation-runs/{run_id}/issues").json()["items"]
    first = issues[0]
    reviewed = client.post(
        f"{API}/issues/{first['issue_id']}/review",
        json={
            "status": "needs_more_information",
            "comment": "Please confirm this value in the source bill.",
            "expected_version": first["version"],
        },
    ).json()["issue"]
    assert reviewed["review_status"] == "needs_more_information"
    csv_response = client.get(f"{API}/validation-runs/{run_id}/export/issues.csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    disposition = csv_response.headers["content-disposition"]
    assert (
        'filename="Angebot Marz ' in disposition
        and "filename*=UTF-8''Angebot%20M%C3%A4rz%20" in disposition
    )
    assert csv_response.content.count(b"\r\n") == 4  # header + three findings
    archive = zipfile.ZipFile(
        io.BytesIO(client.get(f"{API}/validation-runs/{run_id}/export/tables.zip").content)
    )
    assert "manifest.json" in archive.namelist() and "issues.csv" in archive.namelist()
    exported = json.loads(client.get(f"{API}/validation-runs/{run_id}/export/json").content)
    assert exported["export"]["validation_run_id"] == run_id and len(exported["issues"]) == 3
    JsonExport.model_validate(exported)  # the OpenAPI description of the export is accurate
    questions = client.get(f"{API}/validation-runs/{run_id}/export/questions.md")
    assert questions.status_code == 200
    assert questions.headers["content-type"].startswith("text/markdown")
    text = questions.content.decode("utf-8")
    assert "# Questions for client" in text
    assert reviewed["issue_id"] in text
    _error(client.get(f"{API}/validation-runs/{run_id}/export/docx"), 404, "not_found")


def test_run_review_finish_and_reopen(client: TestClient) -> None:
    ds = _upload(client, DEFECTIVE_CSV).json()["dataset"]["dataset_id"]
    run = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    run_id = run["run_id"]
    blocked = _error(
        client.post(f"{API}/validation-runs/{run_id}/review-finish"),
        422,
        "invalid_input",
    )
    assert blocked["details"]["pending_review"] == run["issue_count"]
    issues = client.get(f"{API}/validation-runs/{run_id}/issues").json()["items"]
    for issue in issues:
        decided = client.post(
            f"{API}/issues/{issue['issue_id']}/review",
            json={"status": "dismissed", "expected_version": issue["version"]},
        )
        assert decided.status_code == 200, decided.text
    finished = client.post(f"{API}/validation-runs/{run_id}/review-finish")
    assert finished.status_code == 200, finished.text
    assert finished.json()["review_status"] == "finished"
    assert finished.json()["review_finished_at"]
    reopened = client.delete(f"{API}/validation-runs/{run_id}/review-finish")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["review_status"] == "in_progress"
    assert reopened.json()["review_finished_at"] is None


def test_issue_correction_creates_a_new_dataset_revision_and_rerun(client: TestClient) -> None:
    ds = _upload(client, DEFECTIVE_CSV).json()["dataset"]["dataset_id"]
    run = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    issues = client.get(f"{API}/validation-runs/{run['run_id']}/issues").json()["items"]
    issue = next(item for item in issues if item["affected_cells"])
    reviewed = client.post(
        f"{API}/issues/{issue['issue_id']}/review",
        json={"status": "confirmed_error", "expected_version": issue["version"]},
    ).json()["issue"]
    [cell] = reviewed["affected_cells"][:1]
    corrected = client.post(
        f"{API}/issues/{reviewed['issue_id']}/corrections",
        json={
            "cells": [
                {
                    "table_id": cell["table_id"],
                    "row_id": cell["row_id"],
                    "column_id": cell["column_id"],
                    "value": None,
                }
            ],
            "expected_version": reviewed["version"],
            "rerun_validation": True,
        },
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["issue"]["review_status"] == "corrected"
    assert body["dataset"]["dataset_id"] == ds and body["dataset"]["revision"] == 2
    assert body["validation_run"] is not None
    assert body["validation_run"]["dataset_revision"] == 2
    assert body["corrected_cells"][0]["corrected_raw_value"] == ""
    latest = client.get(f"{API}/datasets/{ds}").json()
    assert latest["revision"] == 2
    runs = client.get(f"{API}/datasets/{ds}/validation-runs").json()["items"]
    assert runs[0]["dataset_revision"] == 2


def test_rejected_uploads(client: TestClient) -> None:
    error = _error(_upload(client, b"\x89PNG\r\n\x1a\n", "scan.png"), 415, "unsupported_format")
    assert error["message"]
    assert client.get(f"{API}/documents").json()["total"] == 0  # nothing was stored
    failed = _upload(client, b";;;\n;;;\n", "leer.csv")
    assert failed.status_code == 201, failed.text
    assert failed.json()["document"]["processing_status"] == "failed"
    assert failed.json()["document"]["failure_reason"] and failed.json()["dataset"] is None
    _error(client.get(f"{API}/documents?limit=0"), 422, "request_validation_failed")
    _error(client.post(f"{API}/datasets/ds_nope/validation-runs"), 404, "not_found")


def test_an_offset_no_database_can_bind_is_a_client_error(client: TestClient) -> None:
    """Offsets are bound as signed 64-bit integers (SQLite INTEGER, PostgreSQL bigint): the
    largest one is an empty page, a larger one is malformed (422), not a failed query (500)."""
    dataset = _upload(client, GERMAN_CSV).json()["dataset"]
    run = client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()
    table_id = dataset["tables"][0]["table_id"]
    for page in (
        f"{API}/documents",
        f"{API}/validation-runs/{run['run_id']}/issues",
        f"{API}/datasets/{dataset['dataset_id']}/tables/{table_id}/rows",
    ):
        last = client.get(page, params={"offset": 2**63 - 1})
        assert last.status_code == 200, last.text
        assert last.json()["items"] == [] and last.json()["offset"] == 2**63 - 1
        error = _error(client.get(page, params={"offset": 2**63}), 422, "request_validation_failed")
        assert error["details"]["errors"][0]["loc"] == ["query", "offset"]


def _multipart(*parts: tuple[str, str | None, bytes], close: bool = True) -> dict[str, Any]:
    """A hand-built multipart body (httpx always puts fields before files)."""
    body = b""
    for name, filename, content in parts:
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        body += f"--XyZ\r\nContent-Disposition: {disposition}\r\n\r\n".encode() + content
        body += b"\r\n"
    if close:
        body += b"--XyZ--\r\n"
    else:
        body = body[:-2]  # the file never ends
    return {"content": body, "headers": {"Content-Type": "multipart/form-data; boundary=XyZ"}}


def test_streamed_upload_form(client: TestClient, tmp_path: Path) -> None:
    for parts in (
        [("profile_id", None, b"generic"), ("file", "vorher.csv", GERMAN_CSV)],
        [("file", "nachher.csv", GERMAN_CSV), ("profile_id", None, b"generic")],
    ):
        created = client.post(f"{API}/documents", **_multipart(*parts))
        assert created.status_code == 201, created.text
        assert created.json()["document"]["profile_id"] == "generic"

    unknown = _multipart(("file", "a.csv", GERMAN_CSV), ("profile_id", None, b"nope"))
    error = _error(client.post(f"{API}/documents", **unknown), 422, "invalid_input")
    assert error["details"] == {"profile_id": "nope", "available": ["boq", "generic"]}
    malformed = {
        "no file part": _multipart(("profile_id", None, b"boq")),
        "two files": _multipart(("file", "a.csv", GERMAN_CSV), ("file", "b.csv", GERMAN_CSV)),
        "another file field": _multipart(("attachment", "a.csv", GERMAN_CSV)),
        "long field": _multipart(("profile_id", None, b"x" * 2000), ("file", "a.csv", b"1;2")),
        "file never ends": _multipart(("file", "a.csv", GERMAN_CSV), close=False),
        "not multipart": {"content": b"--nope", "headers": {"Content-Type": "text/csv"}},
        "garbage": _multipart() | {"content": b"no boundary here"},
    }
    for case, request in malformed.items():
        response = client.post(f"{API}/documents", **request)
        assert response.status_code == 422, (case, response.text)
        assert response.json()["error"]["code"] == "request_validation_failed", case
    assert client.get(f"{API}/documents").json()["total"] == 2
    assert list((tmp_path / "tmp").iterdir()) == []  # every rejected spool was deleted
    upload = client.get("/openapi.json").json()["paths"]["/api/v1/documents"]["post"]
    assert "multipart/form-data" in upload["requestBody"]["content"]


def test_local_api_security(client: TestClient) -> None:
    echoed = client.get(f"{API}/health", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"
    fresh = client.get(f"{API}/health", headers={"X-Request-ID": "not a token!"})
    assert fresh.headers["X-Request-ID"] != "not a token!"
    _error(client.get(f"{API}/health", headers={"Host": "evil.example"}), 400, "host_not_allowed")
    evil = client.post(
        f"{API}/datasets/ds_x/validation-runs", headers={"Origin": "http://evil.example"}
    )
    _error(evil, 403, "origin_not_allowed")
    cross = client.post(
        f"{API}/datasets/ds_x/validation-runs", headers={"Sec-Fetch-Site": "cross-site"}
    )
    _error(cross, 403, "origin_not_allowed")
    own = Settings().cors_origins[0]
    allowed = client.post(f"{API}/datasets/ds_x/validation-runs", headers={"Origin": own})
    _error(allowed, 404, "not_found")  # passed the origin check
    assert allowed.headers["access-control-allow-origin"] == own


def test_body_limits(tmp_path: Path) -> None:
    wb = _workbench(
        tmp_path, max_json_body_bytes=200, ingestion=IngestionLimits(max_upload_bytes=1024)
    )
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        big = {"status": "accepted", "comment": "x" * 500}
        error = _error(client.post(f"{API}/issues/iss_x/review", json=big),
                       413, "request_too_large")  # fmt: skip
        assert error["details"]["limit"] == 200
        _error(_upload(client, b"a;b\n" * 20000), 413, "file_too_large")  # declared length
        error = _error(_upload(client, b"a;b\n" * 500), 413, "file_too_large")  # while spooling
        assert error["details"]["max_bytes"] == 1024
        assert client.get(f"{API}/documents").json()["total"] == 0


def test_body_limits_behind_a_root_path(tmp_path: Path) -> None:
    """Behind a proxy (``uvicorn --root-path /twb``) the path still carries the root path; an
    upload must get the upload limit, not the much smaller limit for JSON bodies."""
    wb = _workbench(
        tmp_path, max_json_body_bytes=200, ingestion=IngestionLimits(max_upload_bytes=4096)
    )
    app = create_app(workbench=wb)
    with TestClient(app, base_url="http://localhost", root_path="/twb") as client:
        content = b"Pos;Text\n" + b"1;Beton\n" * 100  # 909 bytes: above 200, below 4096
        response = client.post(
            f"/twb{API}/documents", files={"file": ("Angebot.csv", content, "text/csv")}
        )
        assert response.status_code == 201, response.text
        big = {"status": "accepted", "comment": "x" * 500}
        response = client.post(f"/twb{API}/issues/iss_x/review", json=big)
        _error(response, 413, "request_too_large")


def test_adversarial_requests(tmp_path: Path) -> None:
    wb = _workbench(tmp_path, max_json_body_bytes=200)
    with TestClient(create_app(workbench=wb), base_url="http://localhost") as client:
        for origin in ("null", "http://localhost:3000", "http://127.0.0.1:5173.evil.example"):
            response = client.post(f"{API}/documents", headers={"Origin": origin})
            _error(response, 403, "origin_not_allowed")

        def chunked() -> Iterator[bytes]:  # no Content-Length: the limit applies while streaming
            yield b'{"status": "accepted", "comment": "'
            for _ in range(50):
                yield b"x" * 20
            yield b'"}'

        response = client.post(
            f"{API}/issues/iss_x/review",
            content=chunked(),
            headers={"Content-Type": "application/json"},
        )
        _error(response, 413, "request_too_large")


@pytest.mark.parametrize(
    "name", ['a"b.csv', "x\r\nSet-Cookie: s=1.csv", "..\\..\\etc\\passwd", "Angebot März.csv", ""]
)
def test_download_names_cannot_break_the_header(name: str) -> None:
    header = content_disposition(name)
    assert "\r" not in header and "\n" not in header
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert re.fullmatch(r"[A-Za-z0-9._ -]+", fallback)
    assert header.count('"') == 2


def test_upload_and_validate_a_gaeb_bid(client: TestClient) -> None:
    fixtures = Path(__file__).parents[1] / "fixtures" / "gaeb"
    created = _upload(client, (fixtures / "small.x84").read_bytes(), "Angebot.x84")
    assert created.status_code == 201, created.text
    document, dataset = created.json()["document"], created.json()["dataset"]
    assert document["format"] == "gaeb_x84" and document["processing_status"] == "processed"
    [table] = dataset["tables"]
    assert table["row_kind_counts"]["item"] == 1
    run = client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()
    assert run["status"] == "completed" and run["issue_count"] == 0
    wrong = _upload(client, (fixtures / "small.x84").read_bytes(), "Angebot.x83")
    assert wrong.status_code == 201  # stored and recorded as failed, like any unreadable file
    failed = wrong.json()["document"]
    assert failed["processing_status"] == "failed" and "GAEB X84" in failed["failure_reason"]


def test_cell_corrections_create_the_next_revision(client: TestClient) -> None:
    dataset = _upload(client, DEFECTIVE_CSV).json()["dataset"]
    ds, [table] = dataset["dataset_id"], dataset["tables"]
    rows_path = f"{API}/datasets/{ds}/tables/{table['table_id']}/rows"
    first = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    assert first["issue_count"] >= 1 and first["dataset_revision"] == 1
    columns = {c["mapped_semantic_field"]: c["column_id"] for c in table["columns"]}
    rows = client.get(rows_path, params={"limit": 1000}).json()["items"]
    [tax] = [
        r for r in rows if r["cells"][columns["description"]]["raw_value"] == "zzgl. 19 % MwSt."
    ]
    fix = {
        "table_id": table["table_id"],
        "row_id": tax["row_id"],
        "column_id": columns["line_total"],
        "raw_value": "3.063,20",
    }

    _error(
        client.post(
            f"{API}/datasets/{ds}/corrections", json={"expected_revision": 2, "corrections": [fix]}
        ),
        409,
        "conflict",
    )
    _error(
        client.post(
            f"{API}/datasets/ds_nope/corrections",
            json={"expected_revision": 1, "corrections": [fix]},
        ),
        404,
        "not_found",
    )
    _error(
        client.post(
            f"{API}/datasets/{ds}/corrections",
            json={"expected_revision": 1, "corrections": [{**fix, "row_id": "row_nope"}]},
        ),
        404,
        "not_found",
    )
    _error(
        client.post(
            f"{API}/datasets/{ds}/corrections", json={"expected_revision": 1, "corrections": []}
        ),
        422,
        "request_validation_failed",
    )
    _error(
        client.post(
            f"{API}/datasets/{ds}/corrections",
            json={"expected_revision": 1, "corrections": [fix, fix]},
        ),
        422,
        "invalid_input",
    )

    corrected = client.post(
        f"{API}/datasets/{ds}/corrections", json={"expected_revision": 1, "corrections": [fix]}
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert (body["revision"], body["parent_revision"], body["changed"]) == (2, 1, 1)
    [row] = body["rows"]
    assert row["row_id"] == tax["row_id"]
    assert row["cells"][columns["line_total"]]["parsed_value"]["value"] == "3063.20"
    assert client.get(f"{API}/datasets/{ds}").json()["revision"] == 2
    again = client.post(
        f"{API}/datasets/{ds}/corrections", json={"expected_revision": 2, "corrections": [fix]}
    ).json()
    assert (again["revision"], again["changed"], again["rows"]) == (2, 0, [])

    page = client.get(rows_path, params={"limit": 5, "row_id": tax["row_id"]}).json()
    index = next(i for i, r in enumerate(rows) if r["row_id"] == tax["row_id"])
    assert page["offset"] == (index // 5) * 5 and tax["row_id"] in [
        r["row_id"] for r in page["items"]
    ]
    assert page["items"][index % 5]["cells"][columns["line_total"]]["raw_value"] == "3.063,20"
    _error(client.get(rows_path, params={"row_id": "row_nope"}), 404, "not_found")

    second = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    assert second["dataset_revision"] == 2
    assert second["issue_count"] < first["issue_count"]


def test_a_correction_that_loses_the_race_for_its_revision_is_a_conflict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two corrections read revision 1 at once; the second to write must not fail with a 500."""
    from app.services import datasets as service

    dataset = _upload(client, DEFECTIVE_CSV).json()["dataset"]
    ds, [table] = dataset["dataset_id"], dataset["tables"]
    rows = client.get(
        f"{API}/datasets/{ds}/tables/{table['table_id']}/rows", params={"limit": 1000}
    ).json()["items"]
    column = next(c["column_id"] for c in table["columns"] if c["mapped_semantic_field"])
    fix = {"table_id": table["table_id"], "row_id": rows[0]["row_id"], "column_id": column}
    body = {"expected_revision": 1, "corrections": [{**fix, "raw_value": "first"}]}
    assert client.post(f"{API}/datasets/{ds}/corrections", json=body).status_code == 200

    stale = service.load  # the other request still sees revision 1 when it reads
    monkeypatch.setattr(
        service,
        "load",
        lambda uow, dataset_id: stale(uow, dataset_id).evolve(revision=1, parent_revision=None),
    )
    body = {"expected_revision": 1, "corrections": [{**fix, "raw_value": "second"}]}
    error = _error(client.post(f"{API}/datasets/{ds}/corrections", json=body), 409, "conflict")
    assert error["details"]["current_revision"] == 2
    monkeypatch.undo()
    assert client.get(f"{API}/datasets/{ds}").json()["revision"] == 2


# A design model for GERMAN_CSV: the pit as one element (300 m³, the bill says 380) and gravel
# work 01.02.0040 that the bill does not price.
DESIGN_MODEL = b"""ISO-10303-21;
HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));ENDSEC;
DATA;
#1=IFCPROJECT('p',$,'Halle 3',$,$,$,$,$,$);
#2=IFCBUILDINGELEMENTPROXY('pit',$,'Baugrube',$,$,$,$,$,$);
#3=IFCBUILDINGELEMENTPROXY('gravel',$,'Kies',$,$,$,$,$,$);
#4=IFCQUANTITYVOLUME('NetVolume',$,$,300.,$);
#5=IFCELEMENTQUANTITY('q',$,'Qto',$,$,(#4));
#6=IFCRELDEFINESBYPROPERTIES('r',$,$,$,(#2,#3),#5);
#7=IFCCLASSIFICATIONREFERENCE($,'01.01.0020','Baugrube ausheben',$);
#8=IFCCLASSIFICATIONREFERENCE($,'01.02.0040','Kiesfilter',$);
#9=IFCRELASSOCIATESCLASSIFICATION('c1',$,$,$,(#2),#7);
#10=IFCRELASSOCIATESCLASSIFICATION('c2',$,$,$,(#3),#8);
ENDSEC;
END-ISO-10303-21;
"""


def test_a_bill_is_checked_against_its_attached_model(client: TestClient) -> None:
    created = _upload(client, GERMAN_CSV).json()
    doc_id, ds = created["document"]["document_id"], created["dataset"]["dataset_id"]
    model_url = f"{API}/documents/{doc_id}/model"
    refused = client.put(model_url, files={"file": ("plan.ifc", b"not a model", "text/plain")})
    _error(refused, 422, "invalid_input")
    assert client.get(f"{API}/documents/{doc_id}").json()["document"]["model"] is None

    attached = client.put(model_url, files={"file": ("Halle 3.ifc", DESIGN_MODEL, "")})
    assert attached.status_code == 200, attached.text
    model = attached.json()["document"]["model"]
    assert model["filename"] == "Halle 3.ifc" and model["schema_name"] == "IFC4"
    assert (model["elements"], model["linked_positions"]) == (2, 2)

    run = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    issues = client.get(f"{API}/validation-runs/{run['run_id']}/issues").json()
    found = {
        (i["rule_id"], i["finding_category"], i["title"])
        for i in issues["items"]
        if i["detector_id"] == "domain.model_quantities"
    }
    assert found == {
        (
            "model_quantity_mismatch",
            "inconsistency",
            "Bill says 380 m3, model gives 300 m3: 01.01.0020",
        ),
        (
            "model_position_missing",
            "omission",
            "Model has work for 01.02.0040 that the bill lacks",
        ),
    }

    detached = client.delete(model_url).json()
    assert detached["document"]["model"] is None
    again = client.post(f"{API}/datasets/{ds}/validation-runs").json()
    [report] = [
        r for r in again["detector_reports"] if r["detector_id"] == "domain.model_quantities"
    ]
    assert report["status"] == "skipped"
    assert report["skipped_reasons"] == ["No model (IFC) is attached to this bill."]
