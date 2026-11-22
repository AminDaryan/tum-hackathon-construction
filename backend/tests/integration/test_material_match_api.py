"""Model-suggested material matches end to end, with a stand-in for the local model.

The bill is synthetic. 1.1 names ribbed steel in words the keywords do not know, supply only;
1.2 is matched by the keywords (the rule path, unchanged); 1.3 is a pipe, not in the
catalogue. Only a run that asks for it calls the model, and only about 1.1 and 1.3; every
other run and every read uses the stored answers. A reviewer rejects the suggestion with the
usual review, and the rejection survives a reload and a new run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import LLMSettings
from app.main import create_app
from app.services import material_matches
from tests.integration.test_api import API, _csv, _upload, _workbench

DETECTOR = "statistical.open_price_reference"
ROWS: list[list[Any]] = [
    ["OZ", "Kurztext", "Menge", "ME", "EP (EUR)", "GP (EUR)"],
    ["1.1", "Rippenstahl BSt 500 S, nur Lieferung frei Baustelle", "12", "t", "300,00", "3.600,00"],
    ["1.2", "Betonstahl B500B liefern und verlegen", "12", "t", "300,00", "3.600,00"],
    ["1.3", "PE-HD Druckrohr DA 110 liefern und verlegen", "100", "m", "12,00", "1.200,00"],
]


class StandIn:
    """Answers like the local model would; records every prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.fail: type[Exception] | None = None

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail is not None:
            raise self.fail("stand-in failure")
        if "Rippenstahl" in prompt:
            return json.dumps(
                {
                    "product_code": "24106210",
                    "abstain_reason": None,
                    "scope": "supply_only",
                    "material_attributes": [{"name": "grade", "text": "BSt 500 S"}],
                    "reason": "Ribbed reinforcing steel bars, delivered only.",
                    "evidence_quotes": ["Rippenstahl BSt 500 S", "nur Lieferung"],
                }
            )
        return json.dumps(
            {
                "product_code": None,
                "abstain_reason": "no_catalogue_product",
                "scope": "supply_and_install",
                "material_attributes": [],
                "reason": "A plastic pipe is not in the catalogue.",
                "evidence_quotes": [],
            }
        )


@pytest.fixture
def model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, StandIn]]:
    stand_in = StandIn()
    monkeypatch.setattr(material_matches, "OllamaGenerator", lambda settings: stand_in)
    llm = LLMSettings(provider="ollama", model="qwen2.5:7b-instruct")
    workbench = _workbench(tmp_path, sqlite=True, llm=llm)  # the real database: reloads persist
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        yield client, stand_in
    workbench.close()


def _validate(client: TestClient, dataset_id: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"{API}/datasets/{dataset_id}/validation-runs", json=body or None)
    assert response.status_code == 201, response.text
    run: dict[str, Any] = response.json()
    assert run["status"] == "completed", run
    return run


def _issues(client: TestClient, run_id: str) -> list[dict[str, Any]]:
    page = client.get(f"{API}/validation-runs/{run_id}/issues?page_size=500").json()
    return [i for i in page["items"] if i["detector_id"] == DETECTOR]


def _report(run: dict[str, Any]) -> dict[str, Any]:
    return next(r for r in run["detector_reports"] if r["detector_id"] == DETECTOR)  # type: ignore[no-any-return]


def test_a_suggestion_is_shown_rejected_and_kept_without_asking_the_model_again(
    model: tuple[TestClient, StandIn],
) -> None:
    client, stand_in = model
    dataset_id = _upload(client, _csv(ROWS), "Stahl.csv").json()["dataset"]["dataset_id"]

    plain = _validate(client, dataset_id)  # no request: no model
    assert stand_in.prompts == []
    assert _report(plain)["coverage"]["model_rows_not_processed"] == 2

    run = _validate(client, dataset_id, match_materials=True)
    assert len(stand_in.prompts) == 2  # 1.1 and 1.3; 1.2 is the keywords' row
    assert not any("Betonstahl B500B" in p for p in stand_in.prompts)
    coverage = _report(run)["coverage"]
    assert coverage["model_rows_suggested"] == 1 and coverage["model_rows_compared"] == 1
    assert coverage["model_rows_abstained"] == 1
    by_rule = {i["rule_id"]: i for i in _issues(client, run["run_id"])}
    suggested = by_rule["model_matched_below_published_material_value"]
    assert "below_published_material_value" in by_rule  # 1.2 by the keywords, unchanged
    assert suggested["title"].startswith("Model-suggested match:")
    assert suggested["severity"] == "low"
    assert suggested["evidence_class"] == "needs_external_context"
    assert suggested["estimated_financial_impact"] is None
    assert suggested["evidence"][0]["data"]["origin"] == "model_suggestion"

    # The risk list keeps it as context: low, needs external context, no exact money.
    risks = client.get(f"{API}/validation-runs/{run['run_id']}/risks").json()
    [risk] = [
        r
        for r in [*risks["risks"], *risks["record"]]
        if suggested["issue_id"] in r["source_issue_ids"]
    ]
    assert risk["evidence_class"] == "needs_external_context" and risk["state"] != "risk"
    assert risk["money"]["kind"] != "exact"
    # findings.yaml 0.5: an unusually low price, compared with published statistics.
    assert risk["risk_type"] == "R080" and risk["methods"] == ["peer_comparison"]
    assert risk["tier"] == "medium"  # T08: an open question; R080 is not critical (T06)

    # Reading, opening and reordering never call the model.
    for query in ("", "?sort_by=price_impact", "?sort_by=confidence&sort_order=asc"):
        assert client.get(f"{API}/validation-runs/{run['run_id']}/risks{query}").status_code == 200
    detail = client.get(f"{API}/issues/{suggested['issue_id']}").json()
    assert len(stand_in.prompts) == 2

    rejected = client.post(
        f"{API}/issues/{suggested['issue_id']}/review",
        json={
            "status": "false_positive",
            "comment": "Not reinforcing steel for this bill.",
            "expected_version": detail["issue"]["version"],
        },
    )
    assert rejected.status_code == 200, rejected.text
    reloaded = client.get(f"{API}/issues/{suggested['issue_id']}").json()["issue"]
    assert reloaded["review_status"] == "false_positive"

    # A new run uses the stored answer and carries the rejection; no model call.
    again = _validate(client, dataset_id)
    [carried] = [
        i
        for i in _issues(client, again["run_id"])
        if i["rule_id"] == "model_matched_below_published_material_value"
    ]
    assert carried["review_status"] == "false_positive"
    _validate(client, dataset_id, match_materials=True)  # the same answers are reused
    assert len(stand_in.prompts) == 2


def test_a_model_that_is_not_configured_leaves_the_keywords_and_says_so(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        dataset_id = _upload(client, _csv(ROWS), "Stahl.csv").json()["dataset"]["dataset_id"]
        run = _validate(client, dataset_id, match_materials=True)
        report = _report(run)
        issues = _issues(client, run["run_id"])
    workbench.close()
    assert report["coverage"]["model_rows_not_processed"] == 2
    assert any("No local model is configured" in n for n in report["notes"])
    assert [i["rule_id"] for i in issues] == ["below_published_material_value"]


@pytest.mark.parametrize(
    ("failure", "sent", "stop"),
    [(ConnectionRefusedError, 1, "could not be reached"), (TimeoutError, 2, None)],
)
def test_a_failing_model_is_recorded_and_the_rows_stay_unmatched(
    model: tuple[TestClient, StandIn], failure: type[Exception], sent: int, stop: str | None
) -> None:
    client, stand_in = model
    stand_in.fail = failure
    dataset_id = _upload(client, _csv(ROWS), "Stahl.csv").json()["dataset"]["dataset_id"]
    run = _validate(client, dataset_id, match_materials=True)
    assert len(stand_in.prompts) == sent  # unreachable: nothing more is sent
    coverage = _report(run)["coverage"]
    assert coverage["model_rows_request_failed"] == sent
    assert coverage.get("model_rows_not_processed", 0) == 2 - sent
    assert "model_rows_suggested" not in coverage
    notes = " ".join(_report(run)["notes"])
    assert "(unavailable)" in notes and (stop is None or stop in notes)


def test_the_request_budget_leaves_the_rest_not_sent(
    model: tuple[TestClient, StandIn], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, stand_in = model
    monkeypatch.setattr(material_matches, "MAX_ROWS", 1)
    dataset_id = _upload(client, _csv(ROWS), "Stahl.csv").json()["dataset"]["dataset_id"]
    run = _validate(client, dataset_id, match_materials=True)
    assert len(stand_in.prompts) == 1
    assert _report(run)["coverage"]["model_rows_not_processed"] == 1
    assert "budget of 1 requests used" in " ".join(_report(run)["notes"])
