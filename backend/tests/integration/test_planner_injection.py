"""The planner of every run is the workbench's (``Workbench.planner``; clients cannot send a
plan): an injected planner is used for foreground and background runs, and its ``kind``, not the
label on the plan it returns, is the source the plan validator trusts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.ids import SequentialIdFactory
from app.main import create_app
from app.models.dataset import Dataset
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.models.profile import DomainProfile
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services.workbench import Workbench, build_workbench
from app.storage.file_store import LocalFileStore
from app.validation.planner import BaselinePlanner
from tests.integration.test_api import DEFECTIVE_CSV
from tests.integration.test_background_runs import ASYNC, _finished
from tests.support.builders import DatasetBuilder

pytestmark = pytest.mark.integration
API = "/api/v1"
STEP = PlanStep(detector_id="deterministic.line_total", rationale="Chosen by the test planner.")
NOTE = "Planned by the planner the test injected."


class RecordingPlanner:
    """Plans one check and records the datasets it was asked about."""

    def __init__(self, kind: PlannerKind, declared: PlannerKind | None = None) -> None:
        self.kind = kind
        self._declared = declared or kind
        self.calls: list[tuple[str, int, str]] = []

    def plan(self, dataset: Dataset, profile: DomainProfile) -> ValidationPlan:
        self.calls.append((dataset.dataset_id, dataset.revision, profile.profile_id))
        return ValidationPlan(planner=self._declared, steps=[STEP], notes=[NOTE])


def _workbench(tmp_path: Path, planner: RecordingPlanner | None) -> Workbench:
    return build_workbench(
        Settings(data_dir=tmp_path, environment="test"),
        uow=InMemoryUnitOfWorkFactory(InMemoryDatabase()),
        files=LocalFileStore(tmp_path),
        ids=SequentialIdFactory(),
        clock=FixedClock(),
        planner=planner,
    )


@pytest.fixture
def planner() -> RecordingPlanner:
    return RecordingPlanner(PlannerKind.BASELINE)


@pytest.fixture
def client(tmp_path: Path, planner: RecordingPlanner) -> Iterator[TestClient]:
    workbench = _workbench(tmp_path, planner)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as test_client:
        yield test_client
    workbench.close()


def _dataset(client: TestClient) -> str:
    upload = client.post(
        f"{API}/documents", files={"file": ("Angebot.csv", DEFECTIVE_CSV, "text/csv")}
    )
    assert upload.status_code == 201, upload.text
    return str(upload.json()["dataset"]["dataset_id"])


def test_the_default_planner_is_the_baseline_planner(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path, None)
    try:
        assert isinstance(workbench.planner, BaselinePlanner)
        assert workbench.planner.kind is PlannerKind.BASELINE
        profile = workbench.profiles.get("boq")
        builder = DatasetBuilder(profile)
        builder.table("LV", [("Qty", "quantity")]).row(["1"])
        plan = workbench.planner.plan(builder.build(), profile)
        assert [step.detector_id for step in plan.steps] == workbench.detectors.ids()
    finally:
        workbench.close()


def test_foreground_runs_use_the_injected_planner(
    client: TestClient, planner: RecordingPlanner
) -> None:
    dataset_id = _dataset(client)
    response = client.post(f"{API}/datasets/{dataset_id}/validation-runs")
    assert response.status_code == 201, response.text
    run = response.json()
    assert planner.calls == [(dataset_id, 1, "boq")]
    assert run["plan"]["planner"] == "baseline"
    assert [step["detector_id"] for step in run["plan"]["steps"]] == [STEP.detector_id]
    assert run["plan"]["notes"] == [NOTE]
    assert [report["detector_id"] for report in run["detector_reports"]] == [STEP.detector_id]


def test_background_runs_use_the_injected_planner(
    client: TestClient, planner: RecordingPlanner
) -> None:
    dataset_id = _dataset(client)
    accepted = client.post(f"{API}/datasets/{dataset_id}/validation-runs", headers=ASYNC)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["plan"]["notes"] == [NOTE]
    finished = _finished(client, accepted.headers["location"])
    assert planner.calls == [(dataset_id, 1, "boq")]  # planned once, when the run was queued
    assert [report["detector_id"] for report in finished["detector_reports"]] == [STEP.detector_id]


def test_a_plan_from_the_client_does_not_choose_the_checks(
    client: TestClient, planner: RecordingPlanner
) -> None:
    dataset_id = _dataset(client)
    plan = {"steps": [{"detector_id": "deterministic.required_values"}]}
    response = client.post(f"{API}/datasets/{dataset_id}/validation-runs", json={"plan": plan})
    assert response.status_code == 201, response.text
    assert response.json()["plan"]["planner"] == "baseline"
    assert [step["detector_id"] for step in response.json()["plan"]["steps"]] == [STEP.detector_id]
    assert planner.calls == [(dataset_id, 1, "boq")]


@pytest.mark.parametrize("headers", [{}, ASYNC], ids=["foreground", "background"])
def test_the_planner_kind_is_the_trusted_source(tmp_path: Path, headers: dict[str, str]) -> None:
    # An adaptive planner must keep every registered check: one check alone is refused, and
    # labelling the plan "baseline" does not make it one.
    for declared in (PlannerKind.LLM, PlannerKind.BASELINE):
        adaptive = RecordingPlanner(PlannerKind.LLM, declared)
        workbench = _workbench(tmp_path / declared.value / str(bool(headers)), adaptive)
        with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
            dataset_id = _dataset(client)
            response = client.post(f"{API}/datasets/{dataset_id}/validation-runs", headers=headers)
            assert response.status_code == 422, response.text
            error = response.json()["error"]
            assert error["code"] == "invalid_validation_plan"
            if declared is PlannerKind.LLM:
                [problem] = error["details"]["errors"]
                assert problem["code"] == "check_missing"
            else:
                assert error["details"] == {"declared": "baseline", "source": "llm"}
            assert client.get(f"{API}/datasets/{dataset_id}/validation-runs").json()["items"] == []
        workbench.close()
