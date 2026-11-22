"""DocumentRepository on both adapters: storage, updates, newest-first listing, paging."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.errors import InvalidInputError, NotFoundError
from app.models.document import ProcessingStatus
from app.repositories.base import UnitOfWorkFactory
from app.repositories.errors import IntegrityViolationError
from tests.unit.repositories.samples import T0, make_document, minutes


def _ids(page) -> list[str]:
    return [document.document_id for document in page.items]


def test_add_then_get_returns_an_equal_document(uow_factory: UnitOfWorkFactory) -> None:
    document = make_document()
    with uow_factory() as uow:
        uow.documents.add(document)
    with uow_factory() as uow:
        assert uow.documents.get(document.document_id) == document
        assert uow.documents.get("doc_unknown") is None


def test_update_replaces_the_stored_version(uow_factory: UnitOfWorkFactory) -> None:
    document = make_document(status=ProcessingStatus.STORED)
    with uow_factory() as uow:
        uow.documents.add(document)
    failed = document.evolve(processing_status=ProcessingStatus.FAILED, failure_reason="bad zip")
    with uow_factory() as uow:
        uow.documents.update(failed)
    with uow_factory() as uow:
        assert uow.documents.get(document.document_id) == failed


def test_update_of_an_unknown_document_raises_not_found(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow, pytest.raises(NotFoundError, match="doc_000001"):
        uow.documents.update(make_document())


def test_duplicate_document_id_is_refused(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.documents.add(make_document())
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.documents.add(make_document())


def test_list_is_newest_first_and_ties_put_the_latest_stored_first(
    uow_factory: UnitOfWorkFactory,
) -> None:
    with uow_factory() as uow:
        uow.documents.add(make_document("doc_a", uploaded_at=T0))
        uow.documents.add(make_document("doc_b", uploaded_at=minutes(1)))
        uow.documents.add(make_document("doc_c", uploaded_at=T0))  # same instant as doc_a
        uow.documents.add(make_document("doc_d", uploaded_at=minutes(1)))  # same as doc_b
    with uow_factory() as uow:
        assert _ids(uow.documents.list()) == ["doc_d", "doc_b", "doc_c", "doc_a"]


def test_update_keeps_the_listing_position(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.documents.add(make_document("doc_a"))
        uow.documents.add(make_document("doc_b"))
    with uow_factory() as uow:
        uow.documents.update(make_document("doc_a", status=ProcessingStatus.NEEDS_REVIEW))
    with uow_factory() as uow:
        assert _ids(uow.documents.list()) == ["doc_b", "doc_a"]


def test_list_orders_by_instant_across_utc_offsets(uow_factory: UnitOfWorkFactory) -> None:
    # 10:30+02:00 is 08:30 UTC: earlier than 09:00 UTC although its wall-clock time is later.
    berlin_summer = timezone(timedelta(hours=2))
    with uow_factory() as uow:
        uow.documents.add(
            make_document(
                "doc_offset", uploaded_at=datetime(2026, 3, 1, 10, 30, tzinfo=berlin_summer)
            )
        )
        uow.documents.add(make_document("doc_utc", uploaded_at=T0))
        uow.documents.add(make_document("doc_naive", uploaded_at=datetime(2026, 3, 1, 8, 45)))
    with uow_factory() as uow:
        page = uow.documents.list()
        assert _ids(page) == ["doc_utc", "doc_naive", "doc_offset"]  # naive = UTC
        assert page.items[2].uploaded_at.utcoffset() == timedelta(hours=2)  # payload kept


def test_list_pages_report_the_total(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        for n in range(5):
            uow.documents.add(make_document(f"doc_{n}", uploaded_at=minutes(n)))
    with uow_factory() as uow:
        first = uow.documents.list(offset=0, limit=2)
        second = uow.documents.list(offset=2, limit=2)
        last = uow.documents.list(offset=4, limit=2)
        beyond = uow.documents.list(offset=9, limit=2)
        counted_only = uow.documents.list(limit=0)
    assert (_ids(first), first.total, first.offset, first.limit) == (["doc_4", "doc_3"], 5, 0, 2)
    assert (_ids(second), second.total) == (["doc_2", "doc_1"], 5)
    assert (_ids(last), last.total) == (["doc_0"], 5)
    assert (_ids(beyond), beyond.total) == ([], 5)
    assert (_ids(counted_only), counted_only.total) == ([], 5)


@pytest.mark.parametrize(("offset", "limit"), [(-1, 10), (0, -1)])
def test_negative_paging_is_refused(
    uow_factory: UnitOfWorkFactory, offset: int, limit: int
) -> None:
    with uow_factory() as uow, pytest.raises(InvalidInputError):
        uow.documents.list(offset=offset, limit=limit)
