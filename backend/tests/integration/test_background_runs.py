"""Background validation runs (contract K3): ``Prefer: respond-async`` answers 202 with the
queued run and a Location to poll; a worker stores ``running`` and the final status. Plans are
checked before anything is queued, failures and shutdowns leave failed runs with a warning,
runs a crash left unfinished fail at the next start, and concurrent runs on one SQLite file
all complete."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import JobSettings, Settings
from app.core.ids import SequentialIdFactory
from app.core.logging import request_id_var
from app.main import create_app
from app.models.run import RunStatus
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services import runs
from app.services.jobs import (
    JobQueueFullError,
    JobRunner,
    JobRunnerClosedError,
    prefers_respond_async,
)
from app.services.workbench import Workbench, build_workbench
from app.storage.file_store import LocalFileStore
from app.validation.pipeline import ValidationPipeline
from tests.integration.test_api import DEFECTIVE_CSV
from tests.unit.repositories.postgres import POSTGRESQL, backends, fresh_postgres_url
from tests.unit.repositories.samples import make_run

pytestmark = pytest.mark.integration
API = "/api/v1"
ASYNC = {"Prefer": "respond-async"}
FINAL = {"completed", "completed_with_errors", "failed"}


def _workbench(
    tmp_path: Path,
    *,
    sqlite: bool,
    postgresql: bool = False,
    workers: int = 2,
    max_waiting: int = 16,
    auto_validate: bool = False,
    ids: SequentialIdFactory | None = None,
    **settings: Any,
) -> Workbench:
    if postgresql:
        settings["database_url"] = fresh_postgres_url()
    jobs = JobSettings(workers=workers, max_waiting=max_waiting, auto_validate=auto_validate)
    return build_workbench(
        Settings(data_dir=tmp_path, environment="test", jobs=jobs, **settings),
        uow=None if sqlite or postgresql else InMemoryUnitOfWorkFactory(InMemoryDatabase()),
        files=LocalFileStore(tmp_path),
        ids=ids or SequentialIdFactory(),
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


def _dataset(client: TestClient) -> str:
    upload = client.post(
        f"{API}/documents", files={"file": ("Angebot.csv", DEFECTIVE_CSV, "text/csv")}
    )
    assert upload.status_code == 201, upload.text
    return upload.json()["dataset"]["dataset_id"]  # type: ignore[no-any-return]


def _until(check: Callable[[], Any], *, timeout: float = 30.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("timed out")


def _finished(client: TestClient, location: str) -> dict[str, Any]:
    def poll() -> dict[str, Any] | None:
        run = client.get(location).json()
        return run if run["status"] in FINAL else None

    return _until(poll)  # type: ignore[no-any-return]


def _issues(client: TestClient, run_id: str) -> list[tuple[str, str]]:
    items = client.get(f"{API}/validation-runs/{run_id}/issues?limit=500").json()["items"]
    return [(issue["fingerprint"], issue["review_status"]) for issue in items]


def test_respond_async_queues_the_run_and_a_worker_finishes_it(client: TestClient) -> None:
    dataset_id = _dataset(client)
    accepted = client.post(f"{API}/datasets/{dataset_id}/validation-runs", headers=ASYNC)
    assert accepted.status_code == 202, accepted.text
    queued = accepted.json()
    run_id = queued["run_id"]
    assert queued["status"] == "queued" and queued["finished_at"] is None
    assert queued["issue_count"] == 0 and queued["issue_counts"]["total"] == 0
    assert queued["plan"]["planner"] == "baseline" and queued["detector_reports"] == []
    assert accepted.headers["location"] == f"{API}/validation-runs/{run_id}"
    assert accepted.headers["preference-applied"] == "respond-async"

    finished = _finished(client, accepted.headers["location"])
    synchronous = client.post(f"{API}/datasets/{dataset_id}/validation-runs")
    assert synchronous.status_code == 201
    expected = synchronous.json()
    for key in ("status", "issue_count", "issue_counts", "warnings", "plan"):
        assert finished[key] == expected[key], key
    assert [(r["detector_id"], r["status"]) for r in finished["detector_reports"]] == [
        (r["detector_id"], r["status"]) for r in expected["detector_reports"]
    ]
    assert finished["issue_count"] > 0
    assert _issues(client, run_id) == _issues(client, expected["run_id"])
    listed = client.get(f"{API}/datasets/{dataset_id}/validation-runs").json()["items"]
    assert {item["run_id"] for item in listed} == {run_id, expected["run_id"]}


def test_only_respond_async_makes_a_run_asynchronous(client: TestClient) -> None:
    dataset_id = _dataset(client)
    url = f"{API}/datasets/{dataset_id}/validation-runs"
    assert client.post(url, headers={"Prefer": "return=minimal"}).status_code == 201
    assert client.post(url).status_code == 201
    combined = client.post(url, headers={"Prefer": "wait=5, Respond-Async; x=1"})
    assert combined.status_code == 202
    _finished(client, combined.headers["location"])


def test_prefer_header_parsing() -> None:
    assert prefers_respond_async(["respond-async"])
    assert prefers_respond_async(["return=minimal", "RESPOND-ASYNC"])
    assert prefers_respond_async(["wait=10,respond-async;foo"])
    assert not prefers_respond_async([])
    assert not prefers_respond_async(["return=representation", "respond-asynchronously"])
    assert not prefers_respond_async(["wait=respond-async"])


def test_a_running_run_is_followed_only_while_its_inputs_are_the_same(tmp_path: Path) -> None:
    """A run that started before a tender was added to the bid's project checks the old inputs,
    so a new request queues another run instead of following it."""
    workbench = _workbench(tmp_path, sqlite=False)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        dataset_id = _dataset(client)
        with workbench.uow() as uow:
            dataset = uow.datasets.get(dataset_id)
        assert dataset is not None
        profile = workbench.profiles.get(dataset.profile_id)
        plan = workbench.planner.plan(dataset, profile)
        current = runs.inputs_digest(workbench, dataset, profile, plan, None, None)
        for run_id, digest in (("run_same", current), ("run_stale", "0" * 64)):
            running = make_run(run_id, dataset_id=dataset_id, status=RunStatus.RUNNING)
            with workbench.uow() as uow:
                uow.runs.add(running.evolve(document_id=dataset.document_id, inputs_digest=digest))
            followed = runs.start_in_background(workbench, dataset_id)
            if run_id == "run_same":
                assert followed["run_id"] == "run_same"
            else:
                assert followed["run_id"] != "run_stale" and followed["status"] == "queued"
                _finished(client, f"{API}/validation-runs/{followed['run_id']}")
    workbench.close()


def test_requests_are_checked_before_anything_is_queued(client: TestClient) -> None:
    dataset_id = _dataset(client)
    missing = client.post(f"{API}/datasets/ds_nope/validation-runs", headers=ASYNC)
    assert missing.status_code == 404
    assert client.get(f"{API}/datasets/{dataset_id}/validation-runs").json()["items"] == []


def test_a_background_run_that_raises_fails_with_a_sanitized_warning(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    dataset_id = _dataset(client)

    def explode(self: ValidationPipeline, **_: Any) -> Any:
        raise RuntimeError("Oberboden abtragen 1.250,50")  # document content

    monkeypatch.setattr(ValidationPipeline, "execute", explode)
    with caplog.at_level(logging.INFO, logger="app"):
        accepted = client.post(f"{API}/datasets/{dataset_id}/validation-runs", headers=ASYNC)
        failed = _finished(client, accepted.headers["location"])
    assert failed["status"] == "failed" and failed["finished_at"] is not None
    [warning] = failed["warnings"]
    assert "RuntimeError" in warning and failed["run_id"] in warning
    assert "Oberboden" not in warning
    assert "failed in the background" in caplog.text  # the cause stays in the server log


def test_runs_a_crash_left_unfinished_fail_at_start_up(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path, sqlite=True)
    with workbench.uow() as uow:
        uow.runs.add(make_run("run_queued", status=RunStatus.QUEUED))
        uow.runs.add(make_run("run_running", status=RunStatus.RUNNING))
        uow.runs.add(make_run("run_done", status=RunStatus.COMPLETED))
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        statuses = {
            run_id: client.get(f"{API}/validation-runs/{run_id}").json()
            for run_id in ("run_queued", "run_running", "run_done")
        }
    assert statuses["run_done"]["status"] == "completed" and statuses["run_done"]["warnings"] == []
    for run_id, was in (("run_queued", "queued"), ("run_running", "running")):
        run = statuses[run_id]
        assert run["status"] == "failed" and run["finished_at"] is not None
        assert run["warnings"] == [
            f"The server stopped while this run was {was}, so it did not finish; start it again."
        ]
    workbench.close()


def test_recovery_can_be_turned_off(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path, sqlite=False)
    workbench = build_workbench(
        workbench.settings.model_copy(update={"jobs": JobSettings(recover_interrupted_runs=False)}),
        uow=workbench.uow,
        files=workbench.files,
    )
    with workbench.uow() as uow:
        uow.runs.add(make_run("run_queued", status=RunStatus.QUEUED))
    assert runs.recover_interrupted(workbench) == []
    with workbench.uow() as uow:
        assert uow.runs.get("run_queued").status is RunStatus.QUEUED


def test_shutdown_waits_for_running_runs_and_fails_queued_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workbench = _workbench(tmp_path, sqlite=True, workers=1)
    started, release = threading.Event(), threading.Event()
    original = ValidationPipeline.execute

    def held(self: ValidationPipeline, **kwargs: Any) -> Any:
        started.set()
        assert release.wait(30)
        return original(self, **kwargs)

    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        dataset_id, other_id = _dataset(client), _dataset(client)
        monkeypatch.setattr(ValidationPipeline, "execute", held)
        url = f"{API}/datasets/{dataset_id}/validation-runs"
        other_url = f"{API}/datasets/{other_id}/validation-runs"
        first = client.post(url, headers=ASYNC).json()["run_id"]
        # A second request for the same revision follows the unfinished run.
        assert client.post(url, headers=ASYNC).json()["run_id"] == first
        second = client.post(other_url, headers=ASYNC).json()["run_id"]
        assert started.wait(30)
        assert client.get(f"{API}/validation-runs/{first}").json()["status"] == "running"
        stopping = threading.Thread(target=workbench.jobs.shutdown)
        stopping.start()
        _until(lambda: client.get(f"{API}/validation-runs/{second}").json()["status"] == "failed")
        assert stopping.is_alive()  # still waiting for the running one
        release.set()
        stopping.join(30)
        assert not stopping.is_alive()
        done = client.get(f"{API}/validation-runs/{first}").json()
        cancelled = client.get(f"{API}/validation-runs/{second}").json()
        refused = client.post(other_url, headers=ASYNC)
    assert done["status"] in {"completed", "completed_with_errors"} and done["issue_count"] > 0
    assert cancelled["warnings"] == [
        "The server shut down before this run started; start it again."
    ]
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "shutting_down"
    with workbench.uow() as uow:  # the refused request left no queued run behind
        assert uow.runs.list_with_status([RunStatus.QUEUED, RunStatus.RUNNING]) == []
    workbench.close()


def test_concurrent_runs_on_one_sqlite_file_all_complete(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path, sqlite=True, workers=3)

    def start(n: int) -> str:
        if n % 4 == 3:  # synchronous runs interleave with the background ones
            return str(runs.start(workbench, dataset_id)["run_id"])
        return str(runs.start_in_background(workbench, dataset_id)["run_id"])

    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        dataset_id = _dataset(client)
        with ThreadPoolExecutor(max_workers=8) as pool:
            run_ids = list(pool.map(start, range(12)))
        _until(lambda: not workbench.jobs.active())
        with workbench.uow() as uow:
            finished = [uow.runs.get(run_id) for run_id in run_ids]
    assert len(set(run_ids)) < 12  # requests for the same revision share runs
    assert {run.status for run in finished} == {finished[0].status}
    assert finished[0].status in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_ERRORS}
    assert {run.issue_count for run in finished} == {finished[0].issue_count}
    workbench.close()


def test_run_start_and_finish_are_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    dataset_id = _dataset(client)
    with caplog.at_level(logging.INFO, logger="app.services.runs"):
        accepted = client.post(f"{API}/datasets/{dataset_id}/validation-runs", headers=ASYNC)
        finished = _finished(client, accepted.headers["location"])
    run_id = finished["run_id"]
    messages = [r.getMessage() for r in caplog.records if r.name == "app.services.runs"]
    assert any(
        m.startswith(f"Validation run {run_id} queued for dataset {dataset_id}") for m in messages
    )
    assert any(
        m.startswith(f"Validation run {run_id} started on dataset {dataset_id}") for m in messages
    )
    [end] = [m for m in messages if m.startswith(f"Validation run {run_id} finished")]
    assert f"{finished['status']}, {finished['issue_count']} finding(s)" in end
    assert end.endswith(" ms") and "completed" in end
    [record] = [r for r in caplog.records if r.getMessage() == end]
    assert record.run_id == run_id and record.dataset_id == dataset_id  # type: ignore[attr-defined]


def test_the_job_runner_contains_failures_and_refuses_work_after_shutdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = JobRunner(workers=1)
    done = threading.Event()
    runner.submit("job_1", lambda: 1 / 0, on_cancelled=lambda: None)  # raises
    runner.submit("job_2", done.set, on_cancelled=lambda: None)
    assert done.wait(10)  # the worker survived the first job
    runner.shutdown()
    assert "Background job job_1 raised" in caplog.text
    with pytest.raises(JobRunnerClosedError):
        runner.submit("job_3", done.set, on_cancelled=lambda: None)
    runner.shutdown()  # idempotent
    with pytest.raises(ValueError, match="workers"):
        JobRunner(workers=0)


def _hold_execute(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    """Make every validation wait in the pipeline until the returned ``release`` is set."""
    started, release = threading.Event(), threading.Event()
    original = ValidationPipeline.execute

    def held(self: ValidationPipeline, **kwargs: Any) -> Any:
        started.set()
        assert release.wait(30)
        return original(self, **kwargs)

    monkeypatch.setattr(ValidationPipeline, "execute", held)
    return started, release


def test_a_full_queue_refuses_background_runs_before_storing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With every worker busy and ``max_waiting`` runs waiting, a further request gets 503 with
    Retry-After and leaves no run behind; once a worker is free, runs are accepted again."""
    workbench = _workbench(tmp_path, sqlite=False, workers=1, max_waiting=1)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        first, second, third = (
            f"{API}/datasets/{_dataset(client)}/validation-runs" for _ in range(3)
        )
        url = third
        started, release = _hold_execute(monkeypatch)
        running = client.post(first, headers=ASYNC)
        assert running.status_code == 202 and started.wait(30)
        waiting = client.post(second, headers=ASYNC)
        assert waiting.status_code == 202
        refused = client.post(url, headers=ASYNC)
        assert refused.status_code == 503, refused.text
        assert refused.json()["error"]["code"] == "run_queue_full"
        assert refused.headers["Retry-After"] == "30"
        assert client.get(url).json()["items"] == []
        release.set()
        _finished(client, waiting.headers["location"])
        _until(lambda: not workbench.jobs.active())
        assert client.post(url, headers=ASYNC).status_code == 202
        _until(lambda: not workbench.jobs.active())
    workbench.close()


def test_a_second_app_on_the_same_workbench_still_runs_in_the_background(
    tmp_path: Path,
) -> None:
    """Only the owner of a workbench shuts its job runner down: an app built on a workbench it
    was given leaves the runner open for the next app."""
    workbench = _workbench(tmp_path, sqlite=False)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        dataset_id = _dataset(client)
    assert not workbench.jobs.closed
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        accepted = client.post(f"{API}/datasets/{dataset_id}/validation-runs", headers=ASYNC)
        assert accepted.status_code == 202, accepted.text
        _finished(client, accepted.headers["location"])
    workbench.close()
    assert workbench.jobs.closed


def test_a_cross_origin_client_can_read_the_location_of_a_background_run(
    client: TestClient,
) -> None:
    dataset_id = _dataset(client)
    origin = Settings().cors_origins[0]
    accepted = client.post(
        f"{API}/datasets/{dataset_id}/validation-runs", headers={**ASYNC, "Origin": origin}
    )
    assert accepted.status_code == 202
    exposed = {
        h.strip().lower() for h in accepted.headers["access-control-expose-headers"].split(",")
    }
    assert {"location", "preference-applied"} <= exposed
    _finished(client, accepted.headers["location"])


def test_the_job_runner_checks_its_capacity() -> None:
    runner = JobRunner(workers=1, max_waiting=0)
    release = threading.Event()
    runner.ensure_capacity()
    runner.submit("job_1", lambda: release.wait(10) and None, on_cancelled=lambda: None)
    with pytest.raises(JobQueueFullError, match="1 background worker"):
        runner.ensure_capacity()
    with pytest.raises(JobQueueFullError):
        runner.submit("job_2", lambda: None, on_cancelled=lambda: None)
    release.set()
    _until(lambda: not runner.active())
    runner.ensure_capacity()
    runner.shutdown()
    with pytest.raises(JobRunnerClosedError):
        runner.ensure_capacity()
    with pytest.raises(ValueError, match="max_waiting"):
        JobRunner(workers=1, max_waiting=-1)


def test_a_background_job_keeps_the_request_id_of_the_request_that_queued_it() -> None:
    runner = JobRunner(workers=1)
    seen: list[str | None] = []
    token = request_id_var.set("req-queued")
    try:
        runner.submit("job_1", lambda: seen.append(request_id_var.get()), on_cancelled=lambda: None)
    finally:
        request_id_var.reset(token)
    _until(lambda: not runner.active())
    runner.shutdown()
    assert seen == ["req-queued"]
    assert request_id_var.get() is None  # the submitter's context is unchanged


def test_bills_are_validated_on_upload_and_at_start_up_without_being_asked(
    tmp_path: Path,
) -> None:
    def finished(client: TestClient, dataset_id: str) -> list[dict[str, Any]]:
        items = client.get(f"{API}/datasets/{dataset_id}/validation-runs").json()["items"]
        return [run for run in items if run["status"] in {"completed", "completed_with_errors"}]

    quiet = _workbench(tmp_path, sqlite=True)
    with TestClient(create_app(workbench=quiet), base_url="http://localhost") as client:
        waiting = _dataset(client)  # uploaded while automatic validation was off
        assert client.get(f"{API}/datasets/{waiting}/validation-runs").json()["items"] == []
    quiet.close()
    later = SequentialIdFactory()  # after a restart, ids continue past the stored ones
    for prefix in ("run", "iss", "aud", "doc", "ds"):
        later._counters[prefix] = 1000
    restarted = _workbench(tmp_path, sqlite=True, auto_validate=True, ids=later)
    with TestClient(create_app(workbench=restarted), base_url="http://localhost") as client:
        [at_start] = _until(lambda: finished(client, waiting))
        assert at_start["issue_count"] > 0
    restarted.close()

    (tmp_path / "other").mkdir()
    workbench = _workbench(tmp_path / "other", sqlite=True, auto_validate=True)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
        uploaded = _dataset(client)
        [on_upload] = _until(lambda: finished(client, uploaded))
        _until(lambda: not workbench.jobs.active())
        # Asking again changes nothing: the same run comes back.
        again = client.post(f"{API}/datasets/{uploaded}/validation-runs").json()
        assert again["run_id"] == on_upload["run_id"]
    workbench.close()
