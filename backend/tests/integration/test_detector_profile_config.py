"""K8: ``GET /detectors?profile_id=...`` shows the parameters a run on that profile uses for each
detector when the plan sets none (``profile_config``), resolved as the plan validator resolves a
step; without the parameter ``profile_id`` and every ``profile_config`` are ``null``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import BUILTIN_PROFILE_DIR, Settings
from app.core.ids import SequentialIdFactory
from app.main import create_app
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services.workbench import Workbench, build_workbench
from app.storage.file_store import LocalFileStore
from app.validation.plan_validation import PlanValidator, profile_config
from tests.integration.test_api import GERMAN_CSV

pytestmark = pytest.mark.integration
API = "/api/v1"
LINE_TOTAL = "deterministic.line_total"
CUSTOM = "boq_medium_lines"  # the built-in boq profile with one plannable parameter changed


@pytest.fixture
def workbench(tmp_path: Path) -> Iterator[Workbench]:
    profile = yaml.safe_load((BUILTIN_PROFILE_DIR / "boq.yaml").read_text(encoding="utf-8"))
    profile["profile_id"] = CUSTOM
    profile["name"] = "Bill of quantities, medium line totals"
    # severity is a plannable parameter of the line-total check; its code default is "high".
    profile["detector_defaults"][LINE_TOTAL]["severity"] = "medium"
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / f"{CUSTOM}.yaml").write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    built = build_workbench(
        Settings(data_dir=tmp_path / "data", environment="test", extra_profile_dirs=[profiles]),
        uow=InMemoryUnitOfWorkFactory(InMemoryDatabase()),
        files=LocalFileStore(tmp_path / "data"),
        ids=SequentialIdFactory(),
        clock=FixedClock(),
    )
    yield built
    built.close()


@pytest.fixture
def client(workbench: Workbench) -> Iterator[TestClient]:
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as test_client:
        yield test_client


def _entry(listing: dict[str, Any], detector_id: str) -> dict[str, Any]:
    [entry] = [e for e in listing["items"] if e["spec"]["detector_id"] == detector_id]
    return entry


def test_profile_config_shows_the_profiles_value(client: TestClient) -> None:
    listing = client.get(f"{API}/detectors", params={"profile_id": CUSTOM})
    assert listing.status_code == 200, listing.text
    assert listing.json()["profile_id"] == CUSTOM
    line_total = _entry(listing.json(), LINE_TOTAL)
    assert "severity" in line_total["plannable_parameters"]
    assert line_total["default_config"]["severity"] == "high"
    assert line_total["profile_config"]["severity"] == "medium"
    # The profile's other parameters for the check are merged in as well.
    tolerance = {"absolute": "0.01", "relative": "0", "per_term_absolute": "0"}
    assert line_total["profile_config"]["tolerance"] == tolerance
    one = client.get(f"{API}/detectors/{LINE_TOTAL}", params={"profile_id": CUSTOM}).json()
    assert one == line_total
    builtin = client.get(f"{API}/detectors", params={"profile_id": "boq"}).json()
    assert _entry(builtin, LINE_TOTAL)["profile_config"]["severity"] == "high"


@pytest.mark.parametrize("profile_id", ["boq", "generic", CUSTOM])
def test_profile_config_is_what_the_plan_validator_resolves(
    client: TestClient, workbench: Workbench, profile_id: str
) -> None:
    listing = client.get(f"{API}/detectors", params={"profile_id": profile_id}).json()
    profile = workbench.profiles.get(profile_id)
    validator = PlanValidator(workbench.detectors, workbench.settings.validation)
    assert {entry["spec"]["detector_id"] for entry in listing["items"]} == set(
        workbench.detectors.ids()
    )
    for entry in listing["items"]:
        detector_id = entry["spec"]["detector_id"]
        plan = ValidationPlan(
            planner=PlannerKind.BASELINE, steps=[PlanStep(detector_id=detector_id, config={})]
        )
        [step] = validator.validate(plan, profile, source=PlannerKind.BASELINE)
        assert step.config is not None
        assert entry["profile_config"] == step.config.model_dump(mode="json"), detector_id


def test_a_run_without_a_plan_uses_the_profiles_value(client: TestClient) -> None:
    created = client.post(
        f"{API}/documents",
        files={"file": ("Angebot.csv", GERMAN_CSV, "text/csv")},
        data={"profile_id": CUSTOM},
    )
    assert created.status_code == 201, created.text
    assert created.json()["document"]["profile_id"] == CUSTOM
    dataset_id = created.json()["dataset"]["dataset_id"]
    run = client.post(f"{API}/datasets/{dataset_id}/validation-runs")
    assert run.status_code == 201, run.text
    assert run.json()["plan"]["planner"] == "baseline"
    [report] = [r for r in run.json()["detector_reports"] if r["detector_id"] == LINE_TOTAL]
    assert report["status"] == "completed"
    assert report["config"]["severity"] == "medium"
    listing = client.get(f"{API}/detectors", params={"profile_id": CUSTOM}).json()
    by_id = {e["spec"]["detector_id"]: e["profile_config"] for e in listing["items"]}
    assert all(r["config"] == by_id[r["detector_id"]] for r in run.json()["detector_reports"])


def test_an_unknown_profile_is_an_invalid_request(client: TestClient) -> None:
    available = ["boq", CUSTOM, "generic"]
    for path in (f"{API}/detectors", f"{API}/detectors/{LINE_TOTAL}"):
        for profile_id in ("nope", ""):
            response = client.get(path, params={"profile_id": profile_id})
            assert response.status_code == 422, response.text
            error = response.json()["error"]
            assert error["code"] == "invalid_input"
            assert error["details"] == {"profile_id": profile_id, "available": available}
    # The detector is looked up first.
    missing = client.get(f"{API}/detectors/deterministic.nope", params={"profile_id": "nope"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_without_a_profile_both_are_null_and_nothing_else_changes(
    client: TestClient, workbench: Workbench
) -> None:
    listing = client.get(f"{API}/detectors").json()
    assert listing["profile_id"] is None
    assert [e["spec"]["detector_id"] for e in listing["items"]] == workbench.detectors.ids()
    for entry in listing["items"]:
        assert entry["profile_config"] is None
        described = workbench.detectors.describe(entry["spec"]["detector_id"])
        assert {k: v for k, v in entry.items() if k != "profile_config"} == described.model_dump(
            mode="json"
        )
    one = client.get(f"{API}/detectors/{LINE_TOTAL}").json()
    assert one == _entry(listing, LINE_TOTAL)


def test_invalid_profile_parameters_resolve_to_no_configuration(workbench: Workbench) -> None:
    """Startup rejects such a profile; resolved directly, the catalogue's answer matches the
    plan validator's, which fails the baseline step instead of running it."""
    boq = workbench.profiles.get("boq")
    broken = boq.evolve(detector_defaults={LINE_TOTAL: {"severity": "loudest"}})
    assert profile_config(workbench.detectors, broken, LINE_TOTAL) is None
    plan = ValidationPlan(planner=PlannerKind.BASELINE, steps=[PlanStep(detector_id=LINE_TOTAL)])
    validator = PlanValidator(workbench.detectors, workbench.settings.validation)
    [step] = validator.validate(plan, broken, source=PlannerKind.BASELINE)
    assert step.config is None and step.config_error
    resolved = profile_config(workbench.detectors, boq, LINE_TOTAL)
    assert resolved is not None and resolved.model_dump(mode="json")["severity"] == "high"
