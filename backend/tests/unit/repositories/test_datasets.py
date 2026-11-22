"""DatasetRepository on both adapters: revisions, listing, integrity, lossless round trip."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.dataset import Dataset
from app.models.profile import DomainProfile
from app.models.source import SourceKind
from app.models.values import NumberValue
from app.repositories.base import DatasetCounts, UnitOfWorkFactory
from app.repositories.errors import IntegrityViolationError
from tests.unit.repositories.samples import build_dataset, make_document, minutes


def _revision(dataset: Dataset, revision: int, *, minute: float) -> Dataset:
    return dataset.evolve(
        revision=revision, parent_revision=revision - 1, created_at=minutes(minute)
    )


def _store(factory: UnitOfWorkFactory, *datasets: Dataset) -> None:
    with factory() as uow:
        for document_id in dict.fromkeys(d.document_id for d in datasets):
            if uow.documents.get(document_id) is None:
                uow.documents.add(make_document(document_id))
        for dataset in datasets:
            uow.datasets.add(dataset)


def test_snapshot_round_trip_is_lossless(uow_factory: UnitOfWorkFactory, dataset: Dataset) -> None:
    _store(uow_factory, dataset)
    with uow_factory() as uow:
        loaded = uow.datasets.get(dataset.dataset_id, 1)
    assert loaded == dataset
    table = loaded.tables[0]
    original_table = dataset.tables[0]
    # Decimals keep their exact digits (Decimal("10.5") == Decimal("10.500") would hide a loss).
    quantity = table.column_for_field("quantity")
    values = [row.cells[quantity.column_id].normalized_value for row in table.rows]
    numbers = [str(v.value) for v in values if isinstance(v, NumberValue)]
    assert numbers == ["10.500", "0.0001"]
    rate = table.rows[2].cells[table.column_for_field("unit_price").column_id]
    assert rate.normalized_value == NumberValue(value=Decimal("1234.5678"), currency="EUR")
    assert rate.formula is not None
    assert rate.formula.expression == "=C4*E4"
    # Source locations survive, including the computed A1 reference.
    assert rate.source.kind is SourceKind.SPREADSHEET
    assert (rate.source.sheet_name, rate.source.row_number, rate.source.a1) == ("LV", 4, "E4")
    assert loaded.tables[1].source.sheet_index == 1
    # Mappings come back in their original (column) order.
    assert list(table.rows[1].cells) == list(original_table.rows[1].cells)


def test_get_without_revision_returns_the_latest(
    uow_factory: UnitOfWorkFactory, dataset: Dataset
) -> None:
    second = _revision(dataset, 2, minute=5)
    _store(uow_factory, dataset, second)
    with uow_factory() as uow:
        assert uow.datasets.get(dataset.dataset_id) == second
        assert uow.datasets.get(dataset.dataset_id, 1) == dataset
        assert uow.datasets.get(dataset.dataset_id, 2) == second


def test_latest_is_the_highest_revision_not_the_last_stored(
    uow_factory: UnitOfWorkFactory, dataset: Dataset
) -> None:
    second = _revision(dataset, 2, minute=5)
    _store(uow_factory, second, dataset)  # revision 1 stored after revision 2
    with uow_factory() as uow:
        assert uow.datasets.get(dataset.dataset_id).revision == 2


def test_unknown_dataset_or_revision_returns_none(
    uow_factory: UnitOfWorkFactory, dataset: Dataset
) -> None:
    _store(uow_factory, dataset)
    with uow_factory() as uow:
        assert uow.datasets.get("ds_unknown") is None
        assert uow.datasets.get(dataset.dataset_id, 7) is None
        assert uow.datasets.list_for_document("doc_unknown") == []


def test_list_for_document_returns_every_revision_oldest_first(
    uow_factory: UnitOfWorkFactory, boq_profile: DomainProfile, dataset: Dataset
) -> None:
    other = build_dataset(boq_profile, dataset_id="ds_000002").evolve(created_at=minutes(1))
    second = _revision(dataset, 2, minute=2)
    third = _revision(dataset, 3, minute=2)  # same instant as revision 2: stored order decides
    unrelated = build_dataset(boq_profile, document_id="doc_000002", dataset_id="ds_000003")
    _store(uow_factory, dataset, other, second, third, unrelated)
    with uow_factory() as uow:
        listed = uow.datasets.list_for_document("doc_000001")
    keys = [(d.dataset_id, d.revision) for d in listed]
    assert keys == [("ds_000001", 1), ("ds_000002", 1), ("ds_000001", 2), ("ds_000001", 3)]
    assert listed[2] == second


def test_duplicate_revision_is_refused(uow_factory: UnitOfWorkFactory, dataset: Dataset) -> None:
    _store(uow_factory, dataset)
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.datasets.add(dataset)


def test_a_dataset_requires_its_document(uow_factory: UnitOfWorkFactory, dataset: Dataset) -> None:
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.datasets.add(dataset)
    with uow_factory() as uow:
        assert uow.datasets.get(dataset.dataset_id) is None


def _latest_key(factory: UnitOfWorkFactory, document_id: str = "doc_000001"):
    with factory() as uow:
        latest = uow.datasets.latest_for_document(document_id)
        counts = uow.datasets.latest_counts_for_document(document_id)
    # The stored counts belong to the same revision and match its content.
    assert counts == (None if latest is None else DatasetCounts.of(latest))
    return None if latest is None else (latest.dataset_id, latest.revision)


def test_latest_for_document_without_datasets_is_none(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.documents.add(make_document())
    assert _latest_key(uow_factory) is None
    assert _latest_key(uow_factory, "doc_unknown") is None


def test_latest_for_document_is_the_newest_dataset_at_its_highest_revision(
    uow_factory: UnitOfWorkFactory, boq_profile: DomainProfile, dataset: Dataset
) -> None:
    older = dataset  # ds_000001, created at FIXED_TIME
    newer = build_dataset(boq_profile, dataset_id="ds_000002").evolve(created_at=minutes(1))
    _store(uow_factory, older, newer)
    assert _latest_key(uow_factory) == ("ds_000002", 1)
    # A correction of the older dataset does not make it the latest dataset again ...
    _store(uow_factory, _revision(older, 2, minute=2))
    assert _latest_key(uow_factory) == ("ds_000002", 1)
    # ... a correction of the newest one is returned.
    newer_revision = _revision(newer, 2, minute=3)
    _store(uow_factory, newer_revision)
    with uow_factory() as uow:
        assert uow.datasets.latest_for_document("doc_000001") == newer_revision


def test_latest_for_document_breaks_creation_ties_by_storage_order(
    uow_factory: UnitOfWorkFactory, boq_profile: DomainProfile
) -> None:
    first = build_dataset(boq_profile, dataset_id="ds_b")
    second = build_dataset(boq_profile, dataset_id="ds_a")  # same created_at, stored later
    _store(uow_factory, first, second)
    assert _latest_key(uow_factory) == ("ds_a", 1)


def test_latest_for_document_takes_the_highest_revision_whatever_the_storage_order(
    uow_factory: UnitOfWorkFactory, boq_profile: DomainProfile, dataset: Dataset
) -> None:
    unrelated = build_dataset(boq_profile, document_id="doc_000002", dataset_id="ds_000009")
    _store(
        uow_factory,
        _revision(dataset, 2, minute=5),
        dataset,
        unrelated.evolve(created_at=minutes(9)),
    )
    assert _latest_key(uow_factory) == ("ds_000001", 2)
    assert _latest_key(uow_factory, "doc_000002") == ("ds_000009", 1)
