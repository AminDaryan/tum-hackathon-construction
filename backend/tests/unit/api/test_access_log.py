"""Log lines of the API: one access line per request (with the error code of a rejection),
uploads, review decisions and exports. Never file contents, file names or comments."""

from __future__ import annotations

import logging

import pytest

from app.core.logging import RequestIdFilter
from tests.unit.api.conftest import MakeClient

API = "/api/v1"
NAME = "Angebot Müller.csv"
CONTENT = b"Pos;Text;Menge;Einheit;EP;GP\n1;Geheimbeton;2;m3;10,00;25,00\n"


def _access(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.api.middleware"]


@pytest.fixture
def capture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="app")
    caplog.handler.addFilter(RequestIdFilter())  # what the configured handler adds
    return caplog


def test_one_access_line_per_request(
    make_client: MakeClient, capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    response = client.get(f"{API}/documents?limit=5&secret=x")
    [line] = _access(capture)
    assert line.levelno == logging.INFO
    assert line.getMessage().startswith("GET /api/v1/documents 200 ")
    assert (line.method, line.path, line.status) == ("GET", "/api/v1/documents", 200)  # type: ignore[attr-defined]
    assert line.request_id == response.headers["X-Request-ID"]  # type: ignore[attr-defined]
    assert isinstance(line.duration_ms, float) and line.error_code is None  # type: ignore[attr-defined]
    assert "secret" not in capture.text  # no query string


@pytest.mark.parametrize(
    ("request_args", "status", "code"),
    [
        ({"url": f"{API}/no-such-route"}, 404, "not_found"),
        ({"url": f"{API}/documents?limit=0"}, 422, "request_validation_failed"),
        ({"url": f"{API}/health", "headers": {"Host": "evil.example"}}, 400, "host_not_allowed"),
    ],
    ids=["not found", "malformed", "wrong host"],
)
def test_rejected_requests_are_logged_with_their_code(
    make_client: MakeClient,
    capture: pytest.LogCaptureFixture,
    request_args: dict[str, object],
    status: int,
    code: str,
) -> None:
    make_client().request("GET", **request_args)  # type: ignore[arg-type]
    [line] = _access(capture)
    assert line.levelno == logging.WARNING and line.status == status  # type: ignore[attr-defined]
    assert line.error_code == code and line.getMessage().endswith(f" {code}")  # type: ignore[attr-defined]


def test_control_characters_in_the_path_cannot_forge_log_lines(
    make_client: MakeClient, capture: pytest.LogCaptureFixture
) -> None:
    make_client().get(f"{API}/x%0AGET%20/forged%20200")
    [line] = _access(capture)
    assert "\n" not in line.getMessage() and "%0A" in line.path  # type: ignore[attr-defined]


def test_uploads_reviews_and_exports_are_logged(
    make_client: MakeClient, capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    created = client.post(f"{API}/documents", files={"file": (NAME, CONTENT, "text/csv")})
    document = created.json()["document"]
    [stored] = [r for r in capture.records if r.name == "app.services.documents"]
    assert stored.document_id == document["document_id"]  # type: ignore[attr-defined]
    assert stored.size_bytes == len(CONTENT) and stored.format == "csv"  # type: ignore[attr-defined]
    assert stored.outcome == document["processing_status"]  # type: ignore[attr-defined]
    assert stored.request_id == created.headers["X-Request-ID"]  # type: ignore[attr-defined]

    client.post(f"{API}/documents", files={"file": ("x.png", b"\x89PNG\r\n", "image/png")})
    rejected = [r for r in capture.records if getattr(r, "outcome", None) == "rejected"]
    assert [r.error_code for r in rejected] == ["unsupported_format"]  # type: ignore[attr-defined]

    plan = {"plan": {"steps": [{"detector_id": "deterministic.line_total", "config": {}}]}}
    ds = created.json()["dataset"]["dataset_id"]
    run = client.post(f"{API}/datasets/{ds}/validation-runs", json=plan).json()
    [issue] = client.get(f"{API}/validation-runs/{run['run_id']}/issues").json()["items"]
    decision = {"status": "dismissed", "comment": "Kunde Müller", "expected_version": 1}
    client.post(f"{API}/issues/{issue['issue_id']}/review", json=decision)
    [reviewed] = [r for r in capture.records if r.name == "app.services.issues"]
    assert reviewed.issue_id == issue["issue_id"] and reviewed.version == 2  # type: ignore[attr-defined]
    assert "pending_review -> dismissed" in reviewed.getMessage()

    client.get(f"{API}/validation-runs/{run['run_id']}/export/issues.csv")
    [exported] = [r for r in capture.records if r.name == "app.services.exports"]
    assert exported.run_id == run["run_id"] and exported.export_format == "issues.csv"  # type: ignore[attr-defined]

    for secret in ("Müller", "Geheimbeton", NAME):
        assert secret not in capture.text
