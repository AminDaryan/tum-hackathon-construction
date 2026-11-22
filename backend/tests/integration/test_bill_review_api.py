"""The Claude bill review end to end, with a stand-in for Claude: no request leaves the machine.

The bill is the German sample (five positions under two Titel). A run that asks for the review
sends the bill once per pass; the claims the model rates as certain become findings of
``llm.bill_review``, marked as suspicions, and reach the risk list. Every other run lists the
stored claims without asking again. Without a key on the server nothing is sent.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.agents import claude
from app.core.config import BillReviewSettings
from app.main import create_app
from app.services import bill_reviews
from app.validation.pipeline import ValidationPipeline
from tests.integration.test_api import API, GERMAN_CSV, _error, _upload, _workbench

DETECTOR = "llm.bill_review"
FILE_NAME = "Angebot März.csv"
KEY = "test-key-not-real"
ASYNC = {"Prefer": "respond-async"}


class StandIn:
    """Answers each pass like Claude would; records every prompt. ``fail`` makes every
    request fail, ``fail_pass`` the requests of one pass."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.made_with: list[dict[str, Any]] = []
        self.fail: str | None = None
        self.fail_pass: str | None = None

    def make(self, **settings: Any) -> StandIn:
        self.made_with.append(settings)
        return self

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        name = _pass_of(prompt)
        if self.fail is not None or name == self.fail_pass:
            raise RuntimeError(self.fail or "status 529 (overloaded_error)")
        issues: list[dict[str, Any]] = []
        if name == "numbers":
            issues = [
                _claim("01.02.0010", "081", "high", "32.00", "Gravel fill at 32.00 per m3."),
                _claim("01.01.0010", "080", "medium", "4.20", "Topsoil at 4.20 looks cheap."),
            ]
        elif name == "text":
            issues = [_claim("01.01.0020", "031", "high", "Baugrube ausheben", "No soil class.")]
        return json.dumps({"issues": issues})


def _pass_of(prompt: str) -> str:
    for name, marker in (
        ("numbers", "081 Unusually high unit price"),
        ("basis", "085 Inconsistent price basis"),
        ("text", "031 Vague material description"),
    ):
        if f"- {marker}" in prompt:
            return name
    raise AssertionError("a prompt of no known pass")


def _claim(oz: str, issue_type: str, certainty: str, quote: str, why: str) -> dict[str, Any]:
    return {
        "oz": oz,
        "issue_type": issue_type,
        "category": "risk",
        "certainty": certainty,
        "quote": quote,
        "why": why,
        "related_oz": [],
    }


@pytest.fixture
def reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, StandIn]]:
    stand_in = StandIn()
    monkeypatch.setattr(bill_reviews, "ClaudeGenerator", stand_in.make)
    monkeypatch.setattr(claude, "installed", lambda: True)  # the SDK is an optional extra
    settings = BillReviewSettings(anthropic_api_key=SecretStr(KEY))
    workbench = _workbench(tmp_path, sqlite=True, bill_review=settings)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        yield client, stand_in
    workbench.close()


def _validate(client: TestClient, dataset_id: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"{API}/datasets/{dataset_id}/validation-runs", json=body or None)
    assert response.status_code == 201, response.text
    run: dict[str, Any] = response.json()
    assert run["status"] == "completed", run
    return run


def _report(run: dict[str, Any]) -> dict[str, Any]:
    return next(r for r in run["detector_reports"] if r["detector_id"] == DETECTOR)  # type: ignore[no-any-return]


def _issues(client: TestClient, run_id: str) -> dict[str, dict[str, Any]]:
    page = client.get(f"{API}/validation-runs/{run_id}/issues?page_size=500").json()
    return {i["rule_id"]: i for i in page["items"] if i["detector_id"] == DETECTOR}


def _row(client: TestClient, dataset_id: str, oz: str) -> tuple[str, dict[str, Any]]:
    dataset = client.get(f"{API}/datasets/{dataset_id}").json()
    [table] = dataset["tables"]
    rows = client.get(f"{API}/datasets/{dataset_id}/tables/{table['table_id']}/rows").json()
    code = next(c for c in table["columns"] if c["mapped_semantic_field"] == "item_code")
    row = next(r for r in rows["items"] if r["cells"][code["column_id"]]["raw_value"] == oz)
    return table, row


def test_the_review_is_sent_once_and_its_certain_claims_join_the_findings(
    reviewed: tuple[TestClient, StandIn],
) -> None:
    client, stand_in = reviewed
    assert client.get(f"{API}/health").json()["bill_review_available"] is True
    dataset_id = _upload(client, GERMAN_CSV, FILE_NAME).json()["dataset"]["dataset_id"]

    plain = _validate(client, dataset_id)  # no request: nothing is sent
    assert stand_in.prompts == []
    assert _report(plain)["status"] == "skipped"
    assert _report(plain)["skipped_reasons"] == ["No Claude review was started for this bill."]

    stand_in.fail_pass = "basis"
    run = _validate(client, dataset_id, bill_review=True)
    assert len(stand_in.prompts) == 3  # one request per pass, the whole bill in each
    assert [made["api_key"] for made in stand_in.made_with] == [KEY]
    assert stand_in.made_with[0]["model"] == "claude-haiku-5-5"
    assert all(FILE_NAME not in prompt for prompt in stand_in.prompts)  # the bill text only
    # what the app's checks found stands in the prompt, so the model does not repeat it
    assert all("Already found by the app's checks: 1 contingency" in p for p in stand_in.prompts)

    report = _report(run)
    assert report["status"] == "completed"
    assert report["coverage"] == {
        "positions_checked": 5,
        "passes_failed": 1,
        "claims_less_certain": 1,
    }
    [note] = report["notes"]
    assert "2 of 3 passes answered on 5 positions: 3 claims." in note
    assert "Failed: basis: status 529 (overloaded_error)." in note

    found = _issues(client, run["run_id"])
    assert set(found) == {"r081", "r031"}  # the medium claim is counted, not listed
    price = found["r081"]
    assert price["title"] == "Suspected by Claude: Unusually high unit price"
    assert price["evidence_class"] == "semantic_warning"
    assert price["finding_category"] == "risk"
    assert price["severity"] == "medium"
    assert price["estimated_financial_impact"] is None
    assert "says of 01.02.0010: Gravel fill at 32.00 per m3." in price["explanation"]
    assert "not a confirmed error" in price["explanation"]
    [quote] = price["evidence"]
    assert quote["detail"] == "32.00"
    assert quote["label"] == "Quoted by the model from the position"
    assert quote["data"]["model"] == "claude-haiku-5-5"
    assert price["affected_cells"][0]["source"]["row_number"] == 12  # its unit price
    assert found["r031"]["finding_category"] == "ambiguity"

    risks = client.get(f"{API}/validation-runs/{run['run_id']}/risks").json()
    listed = [
        r for r in [*risks["risks"], *risks["record"]] if price["issue_id"] in r["source_issue_ids"]
    ]
    [risk] = listed
    assert risk["risk_type"] == "R081"
    assert risk["methods"] == ["guided_llm"]

    again = _validate(client, dataset_id)  # the stored review, nothing sent
    assert again["run_id"] == run["run_id"]  # nothing changed since
    assert len(stand_in.prompts) == 3


def test_a_corrected_position_loses_its_claims_and_the_others_stay(
    reviewed: tuple[TestClient, StandIn],
) -> None:
    client, stand_in = reviewed
    dataset_id = _upload(client, GERMAN_CSV).json()["dataset"]["dataset_id"]
    _validate(client, dataset_id, bill_review=True)
    table, row = _row(client, dataset_id, "01.01.0020")
    column = next(c for c in table["columns"] if c["mapped_semantic_field"] == "description")
    fix = {
        "table_id": table["table_id"],
        "row_id": row["row_id"],
        "column_id": column["column_id"],
        "raw_value": "Baugrube ausheben, Bodenklasse 3-5",
    }
    edited = client.post(
        f"{API}/datasets/{dataset_id}/corrections",
        json={"expected_revision": 1, "corrections": [fix]},
    )
    assert edited.status_code == 200, edited.text

    run = _validate(client, dataset_id)
    assert run["dataset_revision"] == 2
    assert len(stand_in.prompts) == 3  # not asked again
    assert set(_issues(client, run["run_id"])) == {"r081"}
    report = _report(run)
    assert report["coverage"]["claims_on_changed_positions"] == 1
    assert report["coverage"]["positions_read_on_earlier_revision"] == 5
    assert "positions_checked" not in report["coverage"]  # the model has not read revision 2
    assert any("read revision 1 of the bill" in note for note in report["notes"])


def test_a_review_that_got_no_answer_is_named_and_the_run_completes(
    reviewed: tuple[TestClient, StandIn],
) -> None:
    client, stand_in = reviewed
    dataset_id = _upload(client, GERMAN_CSV).json()["dataset"]["dataset_id"]
    stand_in.fail = "status 401 (authentication_error)"
    run = _validate(client, dataset_id, bill_review=True)
    report = _report(run)
    assert report["status"] == "skipped"
    assert report["skipped_reasons"] == ["No pass answered: status 401 (authentication_error)."]
    assert _issues(client, run["run_id"]) == {}


def test_a_review_asked_while_a_run_is_unfinished_gets_its_own_run(
    reviewed: tuple[TestClient, StandIn], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, stand_in = reviewed
    dataset_id = _upload(client, GERMAN_CSV).json()["dataset"]["dataset_id"]
    started, release = threading.Event(), threading.Event()
    original = ValidationPipeline.execute
    calls: list[str] = []

    def held(self: ValidationPipeline, **kwargs: Any) -> Any:
        calls.append(kwargs["run_id"])
        if len(calls) == 1:  # the plain run waits until the review is queued
            started.set()
            assert release.wait(30)
        return original(self, **kwargs)

    monkeypatch.setattr(ValidationPipeline, "execute", held)
    url = f"{API}/datasets/{dataset_id}/validation-runs"
    plain = client.post(url, headers=ASYNC).json()["run_id"]
    assert started.wait(30)
    asked = client.post(url, json={"bill_review": True}, headers=ASYNC)
    assert asked.status_code == 202, asked.text
    assert asked.json()["run_id"] != plain  # not the unfinished plain run
    release.set()
    _until(
        lambda: (
            client.get(f"{API}/validation-runs/{asked.json()['run_id']}").json()["status"]
            == "completed"
        )
    )
    assert len(stand_in.prompts) == 3


def _until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 30
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def test_without_a_key_nothing_is_sent_and_the_request_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stand_in = StandIn()
    monkeypatch.setattr(bill_reviews, "ClaudeGenerator", stand_in.make)
    monkeypatch.setattr(claude, "installed", lambda: True)
    monkeypatch.delenv("DECIVIO_BOT_ANTHROPIC_API_KEY", raising=False)
    workbench = _workbench(tmp_path)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        assert client.get(f"{API}/health").json()["bill_review_available"] is False
        # The review assistant's key serves the bill review when it has none of its own.
        monkeypatch.setenv("DECIVIO_BOT_ANTHROPIC_API_KEY", KEY)
        assert client.get(f"{API}/health").json()["bill_review_available"] is True
        monkeypatch.delenv("DECIVIO_BOT_ANTHROPIC_API_KEY")
        dataset_id = _upload(client, GERMAN_CSV).json()["dataset"]["dataset_id"]
        refused = client.post(
            f"{API}/datasets/{dataset_id}/validation-runs", json={"bill_review": True}
        )
        _error(refused, 409, "conflict")
        background = client.post(
            f"{API}/datasets/{dataset_id}/validation-runs",
            json={"bill_review": True},
            headers={"Prefer": "respond-async"},
        )
        _error(background, 409, "conflict")
        runs = client.get(f"{API}/datasets/{dataset_id}/validation-runs").json()["items"]
    workbench.close()
    assert stand_in.prompts == [] and stand_in.made_with == []
    assert runs == []  # refused before a run was stored
