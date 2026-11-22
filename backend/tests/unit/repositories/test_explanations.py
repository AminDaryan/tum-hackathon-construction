"""ExplanationRepository on every adapter: storage, updates, the latest explanation of a
problem and the newest-first listing of a run, and integrity (an explanation's run must exist,
ids are unique, a failed unit of work stores nothing)."""

from __future__ import annotations

import pytest

from app.core.errors import NotFoundError
from app.models.explanation import ExplanationStatus
from app.repositories.base import UnitOfWorkFactory
from app.repositories.errors import IntegrityViolationError
from tests.unit.repositories.samples import (
    T0,
    Boom,
    fail_after,
    make_explanation,
    make_run,
    minutes,
)


def _ids(explanations) -> list[str]:
    return [explanation.explanation_id for explanation in explanations]


@pytest.fixture
def runs(uow_factory: UnitOfWorkFactory) -> UnitOfWorkFactory:
    with uow_factory() as uow:
        uow.runs.add(make_run("run_000001"))
        uow.runs.add(make_run("run_000002", started_at=minutes(1)))
    return uow_factory


def test_add_get_and_update(runs: UnitOfWorkFactory) -> None:
    queued = make_explanation(status=ExplanationStatus.QUEUED)
    with runs() as uow:
        uow.explanations.add(queued)
    with runs() as uow:
        assert uow.explanations.get(queued.explanation_id) == queued
        assert uow.explanations.get("exp_unknown") is None
    completed = make_explanation(status=ExplanationStatus.COMPLETED)
    with runs() as uow:
        uow.explanations.update(completed)
    with runs() as uow:
        stored = uow.explanations.get(queued.explanation_id)
        assert stored == completed
        assert stored is not None and stored.claims[0].rendered.startswith("Der Gesamtpreis")


def test_failed_explanations_round_trip(runs: UnitOfWorkFactory) -> None:
    failed = make_explanation(status=ExplanationStatus.FAILED)
    with runs() as uow:
        uow.explanations.add(failed)
    with runs() as uow:
        assert uow.explanations.get(failed.explanation_id) == failed


def test_update_of_an_unknown_explanation_raises_not_found(runs: UnitOfWorkFactory) -> None:
    with runs() as uow, pytest.raises(NotFoundError):
        uow.explanations.update(make_explanation())


def test_duplicate_ids_are_refused(runs: UnitOfWorkFactory) -> None:
    with runs() as uow:
        uow.explanations.add(make_explanation())
    with pytest.raises(IntegrityViolationError), runs() as uow:
        uow.explanations.add(make_explanation())


def test_the_run_must_exist(runs: UnitOfWorkFactory) -> None:
    with pytest.raises(IntegrityViolationError), runs() as uow:
        uow.explanations.add(make_explanation(run_id="run_unknown"))
    with runs() as uow:
        uow.explanations.add(make_explanation())
    with pytest.raises(IntegrityViolationError), runs() as uow:
        uow.explanations.update(make_explanation(run_id="run_unknown"))
    with runs() as uow:
        assert uow.explanations.list_for_run("run_unknown") == []


def test_latest_for_problem(runs: UnitOfWorkFactory) -> None:
    with runs() as uow:
        assert uow.explanations.latest_for_problem("run_000001", "prb_a") is None
        uow.explanations.add(make_explanation("exp_old", problem_id="prb_a", created_at=T0))
        uow.explanations.add(make_explanation("exp_new", problem_id="prb_a", created_at=minutes(5)))
        uow.explanations.add(make_explanation("exp_tie", problem_id="prb_a", created_at=minutes(5)))
        uow.explanations.add(
            make_explanation("exp_other", problem_id="prb_b", created_at=minutes(9))
        )
        uow.explanations.add(
            make_explanation(
                "exp_run2", run_id="run_000002", problem_id="prb_a", created_at=minutes(20)
            )
        )
    with runs() as uow:
        latest = uow.explanations.latest_for_problem("run_000001", "prb_a")
        assert latest is not None and latest.explanation_id == "exp_tie"  # stored last
        other = uow.explanations.latest_for_problem("run_000002", "prb_a")
        assert other is not None and other.explanation_id == "exp_run2"
        assert uow.explanations.latest_for_problem("run_000001", "prb_unknown") is None


def test_list_for_run_is_newest_created_first(runs: UnitOfWorkFactory) -> None:
    with runs() as uow:
        assert uow.explanations.list_for_run("run_000001") == []
        uow.explanations.add(make_explanation("exp_a", problem_id="prb_a", created_at=T0))
        uow.explanations.add(make_explanation("exp_b", problem_id="prb_b", created_at=minutes(2)))
        uow.explanations.add(make_explanation("exp_c", problem_id="prb_a", created_at=T0))
        uow.explanations.add(make_explanation("exp_x", run_id="run_000002", problem_id="prb_a"))
    with runs() as uow:
        assert _ids(uow.explanations.list_for_run("run_000001")) == ["exp_b", "exp_c", "exp_a"]
        assert _ids(uow.explanations.list_for_run("run_000002")) == ["exp_x"]


def test_an_update_keeps_the_insertion_order(runs: UnitOfWorkFactory) -> None:
    with runs() as uow:
        uow.explanations.add(make_explanation("exp_a", status=ExplanationStatus.RUNNING))
        uow.explanations.add(make_explanation("exp_b", status=ExplanationStatus.RUNNING))
    with runs() as uow:
        uow.explanations.update(make_explanation("exp_a"))
    with runs() as uow:
        assert _ids(uow.explanations.list_for_run("run_000001")) == ["exp_b", "exp_a"]
        latest = uow.explanations.latest_for_problem("run_000001", "prb_line_total_1")
        assert latest is not None and latest.explanation_id == "exp_b"


def test_a_failed_unit_of_work_stores_nothing(runs: UnitOfWorkFactory) -> None:
    with pytest.raises(Boom):
        fail_after(runs, lambda uow: uow.explanations.add(make_explanation()))
    with runs() as uow:
        assert uow.explanations.get("exp_000001") is None
        uow.explanations.add(make_explanation(status=ExplanationStatus.RUNNING))
    with pytest.raises(Boom):
        fail_after(runs, lambda uow: uow.explanations.update(make_explanation()))
    with runs() as uow:
        stored = uow.explanations.get("exp_000001")
        assert stored is not None and stored.status is ExplanationStatus.RUNNING
