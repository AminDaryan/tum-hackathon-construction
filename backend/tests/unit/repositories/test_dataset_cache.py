"""The SQL adapter's decoded-dataset cache: hits skip decoding, but the database always decides
which revision exists, so the cache never serves a stale, rolled-back or replaced revision."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.models.dataset import Dataset
from app.models.profile import DomainProfile
from app.repositories.errors import CorruptSnapshotError, UnknownSnapshotCodecError
from app.repositories.snapshot_codec import EncodedSnapshot
from app.repositories.sql import Database, SqlUnitOfWorkFactory
from app.repositories.sql import datasets as sql_datasets
from app.repositories.sql.schema import datasets as datasets_table
from tests.unit.repositories.samples import Boom, build_dataset, fail_after, make_document


@pytest.fixture
def decodes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every snapshot decode performed by the SQL dataset repository."""
    calls: list[str] = []
    real = sql_datasets.decode_dataset

    def counting(snapshot: EncodedSnapshot, *, what: str) -> Dataset:
        dataset = real(snapshot, what=what)
        calls.append(f"{dataset.dataset_id}/{dataset.revision}")
        return dataset

    monkeypatch.setattr(sql_datasets, "decode_dataset", counting)
    return calls


def _store(database: Database, *datasets: Dataset) -> None:
    with SqlUnitOfWorkFactory(database)() as uow:
        if uow.documents.get("doc_000001") is None:
            uow.documents.add(make_document())
        for dataset in datasets:
            uow.datasets.add(dataset)


def _get(database: Database, dataset_id: str, revision: int | None = None) -> Dataset | None:
    with SqlUnitOfWorkFactory(database)() as uow:
        return uow.datasets.get(dataset_id, revision)


def test_second_read_is_served_from_the_cache_without_decoding(
    sql_database: Database, dataset: Dataset, decodes: list[str]
) -> None:
    _store(sql_database, dataset)
    sql_database.dataset_cache.clear()  # forget the write-through entry
    first = _get(sql_database, dataset.dataset_id)
    assert decodes == ["ds_000001/1"]
    second = _get(sql_database, dataset.dataset_id)
    third = _get(sql_database, dataset.dataset_id, 1)
    assert decodes == ["ds_000001/1"]  # no further decoding
    assert first == dataset
    assert second is first
    assert third is first
    assert sql_database.dataset_cache.stats().hits >= 2


def test_add_fills_the_cache(sql_database: Database, dataset: Dataset, decodes: list[str]) -> None:
    _store(sql_database, dataset)
    assert _get(sql_database, dataset.dataset_id) is dataset
    assert decodes == []


def test_latest_revision_is_resolved_in_the_database(
    sql_database: Database, dataset: Dataset, decodes: list[str]
) -> None:
    _store(sql_database, dataset)
    assert _get(sql_database, dataset.dataset_id) == dataset  # revision 1 now cached
    second = dataset.evolve(revision=2, parent_revision=1)
    _store(sql_database, second)
    sql_database.dataset_cache.clear()
    assert _get(sql_database, dataset.dataset_id) == second
    assert _get(sql_database, dataset.dataset_id, 1) == dataset
    assert decodes == ["ds_000001/2", "ds_000001/1"]


def test_a_rolled_back_or_replaced_revision_is_never_served_from_the_cache(
    file_database_url: str, boq_profile: DomainProfile, decodes: list[str]
) -> None:
    rolled_back = build_dataset(boq_profile)
    with Database(file_database_url) as first_process, Database(file_database_url) as second:
        # The first process caches a revision whose transaction then rolls back.
        with pytest.raises(Boom):
            fail_after(
                SqlUnitOfWorkFactory(first_process),
                lambda uow: (uow.documents.add(make_document()), uow.datasets.add(rolled_back)),
            )
        assert len(first_process.dataset_cache) == 1
        assert _get(first_process, rolled_back.dataset_id) is None
        assert _get(first_process, rolled_back.dataset_id, 1) is None
        # Another process stores different content under the same key: the digest in the
        # database no longer matches the cached entry, so the first process decodes it.
        replacement = rolled_back.evolve(profile_version="9.9.9")
        _store(second, replacement)
        assert _get(first_process, replacement.dataset_id) == replacement
    assert decodes == ["ds_000001/1"]


def test_cache_capacity_is_configurable(boq_profile: DomainProfile, decodes: list[str]) -> None:
    with Database.in_memory_sqlite(dataset_cache_entries=1) as database:
        first = build_dataset(boq_profile, dataset_id="ds_a")
        second = build_dataset(boq_profile, dataset_id="ds_b")
        _store(database, first, second)  # write-through keeps only ds_b
        assert _get(database, "ds_b") is second
        assert _get(database, "ds_a") == first  # evicts ds_b
        assert _get(database, "ds_b") == second  # decoded again
        stats = database.dataset_cache.stats()
    assert decodes == ["ds_a/1", "ds_b/1"]
    assert (stats.max_entries, stats.size, stats.evictions) == (1, 1, 3)


def test_a_damaged_snapshot_is_reported(sql_database: Database, dataset: Dataset) -> None:
    _store(sql_database, dataset)
    sql_database.dataset_cache.clear()
    with sql_database.connect() as connection, connection.begin():
        connection.execute(update(datasets_table).values(snapshot=b"not a snapshot"))
    with pytest.raises(CorruptSnapshotError, match="SHA-256"):
        _get(sql_database, dataset.dataset_id)


def test_an_unknown_snapshot_codec_is_refused(sql_database: Database, dataset: Dataset) -> None:
    _store(sql_database, dataset)
    sql_database.dataset_cache.clear()
    with sql_database.connect() as connection, connection.begin():
        connection.execute(update(datasets_table).values(snapshot_codec="json+zstd/9"))
    with pytest.raises(UnknownSnapshotCodecError, match="json\\+zstd/9"):
        _get(sql_database, dataset.dataset_id)


def test_latest_for_document_decodes_only_the_revision_it_returns(
    sql_database: Database, boq_profile: DomainProfile, decodes: list[str]
) -> None:
    older = build_dataset(boq_profile, dataset_id="ds_a")
    newer = build_dataset(boq_profile, dataset_id="ds_b")
    _store(sql_database, older, older.evolve(revision=2, parent_revision=1), newer)
    sql_database.dataset_cache.clear()
    with SqlUnitOfWorkFactory(sql_database)() as uow:
        latest = uow.datasets.latest_for_document("doc_000001")
    assert latest == newer
    assert decodes == ["ds_b/1"]
