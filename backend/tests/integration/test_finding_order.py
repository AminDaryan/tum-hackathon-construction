"""Findings come out in the same order in every run of the same data.

Every run gives its findings new random issue ids, so an order that fell back on the id would
change from run to run. A bill with one item row repeated verbatim produces findings that tie
on severity and position (several detectors report the repeated row's cells); the API list and
the issues CSV export of repeated runs must still agree, on in-memory storage and on SQLite.
The runs plan every check, with the duplicate check comparing the item code as well (the BoQ
profile leaves the OZ out; an adaptive planner may set that parameter): it and the uniqueness
check then both start at the repeated row's code cell, which makes the tie.
"""

from __future__ import annotations

import csv
import io
import itertools
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.dataset import Dataset
from app.models.plan import PlannerKind, ValidationPlan
from app.models.profile import DomainProfile
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services import runs as runs_service
from app.services.workbench import build_workbench
from app.storage.file_store import LocalFileStore
from app.validation.planner import BaselinePlanner
from tests.integration.test_api import _csv
from tests.unit.normalization.raw_builders import GERMAN_LV
from tests.unit.repositories.postgres import POSTGRESQL, backends, fresh_postgres_url

pytestmark = pytest.mark.integration
API = "/api/v1"
RUNS = 8
RUN_SPECIFIC_COLUMNS = ("validation_run_id", "issue_id")

_ROWS = deepcopy(GERMAN_LV)
_REPEATED = next(i for i, row in enumerate(_ROWS) if row and row[0] == "01.01.0020")
_ROWS.insert(_REPEATED + 1, list(_ROWS[_REPEATED]))
DUPLICATED_ITEM_CSV = _csv(_ROWS)
DUPLICATES = "deterministic.exact_duplicates"


class ComparingItemCodes(BaselinePlanner):
    """Every check, with the duplicate check comparing the item code too."""

    kind = PlannerKind.LLM

    def plan(self, dataset: Dataset, profile: DomainProfile) -> ValidationPlan:
        plan = super().plan(dataset, profile)
        steps = [
            step.model_copy(update={"config": {"ignore_fields": []}})
            if step.detector_id == DUPLICATES
            else step
            for step in plan.steps
        ]
        return plan.model_copy(update={"planner": PlannerKind.LLM, "steps": steps})


@pytest.fixture(params=backends("memory", "sqlite"))
def client(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TestClient]:
    """The real id factory (random ids) and clock, unlike the other API tests."""
    url = fresh_postgres_url() if request.param == POSTGRESQL else None
    settings = Settings(data_dir=tmp_path, environment="test", database_url=url)
    memory = InMemoryUnitOfWorkFactory(InMemoryDatabase())
    workbench = build_workbench(
        settings, uow=memory if request.param == "memory" else None, files=LocalFileStore(tmp_path)
    )
    workbench = replace(workbench, planner=ComparingItemCodes(workbench.detectors))
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as test_client:
        yield test_client
    workbench.close()


def _place(issue: dict[str, Any]) -> tuple[Any, ...]:
    """What the order compares before stored content: severity and the first cell's source."""
    cells = issue["affected_cells"]
    source = (cells[0].get("source") if cells else None) or {}
    return (
        issue["severity"],
        source.get("sheet_index"),
        source.get("row_number"),
        source.get("column_number"),
    )


def _run(client: TestClient, dataset_id: str) -> tuple[list[dict[str, Any]], list[list[str]]]:
    created = client.post(f"{API}/datasets/{dataset_id}/validation-runs")
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    listed = client.get(f"{API}/validation-runs/{run_id}/issues", params={"limit": 500}).json()
    assert listed["total"] == len(listed["items"])
    exported = client.get(f"{API}/validation-runs/{run_id}/export/issues.csv")
    assert exported.status_code == 200, exported.text
    rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    return listed["items"], rows


def _without_run_specific_columns(rows: list[list[str]]) -> list[list[str]]:
    header = rows[0]
    keep = [i for i, name in enumerate(header) if name not in RUN_SPECIFIC_COLUMNS]
    return [[row[i] for i in keep] for row in rows]


def test_repeated_runs_list_and_export_findings_in_the_same_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Starting a run on unchanged inputs returns the latest run; this test needs fresh runs.
    monkeypatch.setattr(runs_service, "_unchanged", lambda *_: None)
    upload = client.post(
        f"{API}/documents", files={"file": ("Angebot doppelt.csv", DUPLICATED_ITEM_CSV, "text/csv")}
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["dataset"]["dataset_id"]

    runs = [_run(client, dataset_id) for _ in range(RUNS)]

    first_items, first_rows = runs[0]
    tied = [a for a, b in itertools.pairwise(first_items) if _place(a) == _place(b)]
    assert tied, "the bill must produce findings that tie on severity and position"
    assert {issue["detector_id"] for issue in first_items} >= {
        "deterministic.exact_duplicates",
        "deterministic.field_constraints",
    }
    issue_ids: set[str] = set()
    for items, rows in runs:
        assert [issue["fingerprint"] for issue in items] == [
            issue["fingerprint"] for issue in first_items
        ]
        # The export lists the run's findings in the order of its API list ...
        header = rows[0]
        exported_ids = [row[header.index("issue_id")] for row in rows[1:]]
        assert exported_ids == [issue["issue_id"] for issue in items]
        # ... and agrees with every other run's export apart from the run's own ids.
        assert _without_run_specific_columns(rows) == _without_run_specific_columns(first_rows)
        issue_ids.update(exported_ids)
    assert len(issue_ids) == RUNS * len(first_items)  # every run had new random ids
