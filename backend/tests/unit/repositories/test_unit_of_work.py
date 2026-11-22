"""Units of work on both adapters: commit, rollback, isolation and misuse."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import cast

import pytest

from app.models.dataset import Dataset
from app.models.document import ProcessingStatus
from app.repositories.base import IssueCounts, IssueQuery, UnitOfWork, UnitOfWorkFactory
from app.repositories.errors import PayloadEncodingError, UnitOfWorkError
from tests.unit.repositories.samples import (
    Boom,
    fail_after,
    make_document,
    make_event,
    make_issue,
    make_run,
)


def test_rollback_on_exception_leaves_nothing_behind(
    uow_factory: UnitOfWorkFactory, dataset: Dataset
) -> None:
    def write_everything(uow: UnitOfWork) -> None:
        uow.documents.add(make_document())
        uow.datasets.add(dataset)
        uow.runs.add(make_run())
        uow.issues.add_many([make_issue("iss_000001")])
        uow.audit.append(make_event("aud_000001"))
        assert uow.datasets.get(dataset.dataset_id) == dataset  # visible inside the block

    with pytest.raises(Boom):
        fail_after(uow_factory, write_everything)
    with uow_factory() as uow:
        assert uow.documents.get("doc_000001") is None
        assert uow.documents.list().total == 0
        assert uow.datasets.get(dataset.dataset_id) is None
        assert uow.datasets.list_for_document("doc_000001") == []
        assert uow.runs.get("run_000001") is None
        assert uow.runs.list_for_dataset("ds_000001") == []
        assert uow.issues.get("iss_000001") is None
        assert uow.issues.query(IssueQuery()).total == 0
        assert uow.issues.counts(IssueQuery()) == IssueCounts()
        assert uow.audit.list_for_entity("issue", "iss_000001") == []


def test_rollback_restores_updated_records(uow_factory: UnitOfWorkFactory) -> None:
    original = make_document(status=ProcessingStatus.STORED)
    with uow_factory() as uow:
        uow.documents.add(original)

    def change(uow: UnitOfWork) -> None:
        uow.documents.update(original.evolve(processing_status=ProcessingStatus.PROCESSED))
        uow.documents.add(make_document("doc_000002"))

    with pytest.raises(Boom):
        fail_after(uow_factory, change)
    with uow_factory() as uow:
        assert uow.documents.get("doc_000001") == original
        assert [d.document_id for d in uow.documents.list().items] == ["doc_000001"]


@pytest.mark.parametrize(
    ("context", "field"),
    [
        ({"ratio": float("nan")}, "context.ratio"),
        ({"stats": {"max": float("inf")}}, "context.stats.max"),
        ({"values": [1.0, float("-inf")]}, "context.values.1"),
        ({"amount": Decimal("NaN")}, "context.amount"),
    ],
    ids=["nan", "nested-inf", "listed-inf", "decimal-nan"],
)
def test_non_finite_numbers_are_refused_by_both_adapters(
    uow_factory: UnitOfWorkFactory, context: dict[str, object], field: str
) -> None:
    # ``context`` is Any-typed: Pydantic's JSON mode would silently store null for these.
    event = make_event("aud_nan").evolve(context=context)
    expected = rf"audit event 'aud_nan': {re.escape(field)} is not a finite number"
    with pytest.raises(PayloadEncodingError, match=expected) as refused, uow_factory() as uow:
        uow.audit.append(event)
    assert refused.value.details == {"field": field}
    with uow_factory() as uow:
        assert uow.audit.list_for_entity("issue", "iss_000001") == []


def test_values_json_cannot_represent_are_refused_by_both_adapters(
    uow_factory: UnitOfWorkFactory,
) -> None:
    event = make_event("aud_object").evolve(context={"handle": object()})
    with (
        pytest.raises(PayloadEncodingError, match="audit event 'aud_object' as JSON"),
        uow_factory() as uow,
    ):
        uow.audit.append(event)


def _unit_of_work(factory: UnitOfWorkFactory) -> UnitOfWork:
    """The unit of work itself (both adapters return it from ``__call__``), not yet entered."""
    return cast(UnitOfWork, factory())


def test_repositories_refuse_use_outside_the_with_block(uow_factory: UnitOfWorkFactory) -> None:
    uow = _unit_of_work(uow_factory)
    with pytest.raises(UnitOfWorkError):
        uow.documents.get("doc_000001")
    with uow:
        pass
    with pytest.raises(UnitOfWorkError):
        uow.documents.list()
    with pytest.raises(UnitOfWorkError):
        uow.issues.add_many([])  # refused even with nothing to write


def test_a_unit_of_work_can_be_reused_but_not_reentered(uow_factory: UnitOfWorkFactory) -> None:
    uow = _unit_of_work(uow_factory)
    with uow as active:
        active.documents.add(make_document("doc_a"))
        with pytest.raises(UnitOfWorkError):
            active.__enter__()
    with uow as active:
        assert active.documents.get("doc_a") is not None


def test_nesting_is_refused_on_single_connection_databases(
    single_connection_uow_factory: UnitOfWorkFactory,
) -> None:
    # In-memory storage and in-memory SQLite have one shared connection (PostgreSQL gives each
    # unit of work its own, so it is not parametrized here).
    factory = single_connection_uow_factory
    with factory(), pytest.raises(UnitOfWorkError, match="nested"), factory():
        pass


def test_units_of_work_from_many_threads_are_serialized(uow_factory: UnitOfWorkFactory) -> None:
    errors: list[BaseException] = []
    start = threading.Barrier(4)

    def worker(n: int) -> None:
        start.wait()
        for k in range(10):
            try:
                with uow_factory() as uow:
                    uow.documents.add(make_document(f"doc_{n}_{k}"))
                    if k == 9:
                        raise Boom  # the last write of every worker is rolled back
            except Boom:
                pass
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))
    assert errors == []
    with uow_factory() as uow:
        page = uow.documents.list(limit=100)
    assert page.total == 36
    assert {d.document_id for d in page.items} == {
        f"doc_{n}_{k}" for n in range(4) for k in range(9)
    }
