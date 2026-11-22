"""ValidationRunRepository on both adapters: storage, updates, newest-first listing."""

from __future__ import annotations

import pytest

from app.core.errors import NotFoundError
from app.models.run import RunStatus
from app.repositories.base import UnitOfWorkFactory
from app.repositories.errors import IntegrityViolationError
from tests.unit.repositories.samples import T0, make_run, minutes


def _ids(runs) -> list[str]:
    return [run.run_id for run in runs]


def test_add_get_and_update(uow_factory: UnitOfWorkFactory) -> None:
    running = make_run(status=RunStatus.RUNNING)
    with uow_factory() as uow:
        uow.runs.add(running)
    with uow_factory() as uow:
        assert uow.runs.get(running.run_id) == running
        assert uow.runs.get("run_unknown") is None
    completed = running.evolve(status=RunStatus.COMPLETED, finished_at=minutes(3), issue_count=4)
    with uow_factory() as uow:
        uow.runs.update(completed)
    with uow_factory() as uow:
        assert uow.runs.get(running.run_id) == completed


def test_update_of_an_unknown_run_raises_not_found(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow, pytest.raises(NotFoundError):
        uow.runs.update(make_run())


def test_duplicate_run_id_is_refused(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.runs.add(make_run())
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.runs.add(make_run())


def test_list_for_dataset_is_newest_started_first(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.runs.add(make_run("run_a", started_at=T0))
        uow.runs.add(make_run("run_b", started_at=minutes(2), revision=2))
        uow.runs.add(make_run("run_c", started_at=T0))  # same instant as run_a, stored later
        uow.runs.add(make_run("run_other", dataset_id="ds_other", started_at=minutes(9)))
    with uow_factory() as uow:
        assert _ids(uow.runs.list_for_dataset("ds_000001")) == ["run_b", "run_c", "run_a"]
        assert uow.runs.list_for_dataset("ds_unknown") == []


def test_latest_for_dataset_is_the_newest_started_run(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        assert uow.runs.latest_for_dataset("ds_000001") is None
        uow.runs.add(make_run("run_new", started_at=minutes(5), status=RunStatus.RUNNING))
        uow.runs.add(make_run("run_old", started_at=minutes(1)))
    with uow_factory() as uow:
        latest = uow.runs.latest_for_dataset("ds_000001")
    assert latest is not None
    assert latest.run_id == "run_new"


def test_runs_are_listed_by_status_newest_first(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.runs.add(make_run("run_a", status=RunStatus.QUEUED, started_at=minutes(0)))
        uow.runs.add(make_run("run_b", dataset_id="ds_2", status=RunStatus.RUNNING))
        uow.runs.add(make_run("run_c", status=RunStatus.COMPLETED, started_at=minutes(5)))
        uow.runs.add(make_run("run_d", status=RunStatus.QUEUED, started_at=minutes(9)))
    with uow_factory() as uow:
        unfinished = uow.runs.list_with_status([RunStatus.QUEUED, RunStatus.RUNNING])
        assert [run.run_id for run in unfinished] == ["run_d", "run_b", "run_a"]
        assert uow.runs.list_with_status([RunStatus.FAILED]) == []
        assert [r.run_id for r in uow.runs.list_with_status(["completed"])] == ["run_c"]
