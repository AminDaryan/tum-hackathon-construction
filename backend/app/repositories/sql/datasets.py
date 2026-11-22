"""SQL implementation of :class:`~app.repositories.base.DatasetRepository`.

Each revision is one compressed snapshot (:mod:`app.repositories.snapshot_codec`) stored with
the SHA-256 of its bytes and its table and row counts (listings read those, never the
snapshot). Decoded revisions are kept in the database's shared LRU cache, keyed by
``(dataset_id, revision)``. Every read still resolves the revision (and its digest) from the
database first, a cheap key lookup, and a cached dataset is served only when its digest matches
the stored one. A rolled-back or re-inserted revision can therefore never be served stale, and
the cache may be filled on ``add`` before the transaction commits.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

from sqlalchemy import Column, Connection, Row, select, tuple_

from app.models.dataset import Dataset
from app.repositories.base import DatasetCounts
from app.repositories.errors import CorruptSnapshotError, PersistenceError
from app.repositories.lru_cache import LruCache
from app.repositories.querying import DATASET_ORDER, latest_dataset_key
from app.repositories.records import dataset_columns
from app.repositories.snapshot_codec import EncodedSnapshot, decode_dataset, encode_dataset
from app.repositories.sql.schema import datasets
from app.repositories.sql.statements import (
    SqlRepository,
    insert_rows,
    next_sequence_value,
    order_by,
)
from app.repositories.transactions import UnitOfWorkScope

# A result row of a statement whose column list is built at run time. (A TypeAlias, not a
# `type` statement: those need Python 3.12.)
_AnyRow: TypeAlias = Row[*tuple[Any, ...]]

DatasetKey = tuple[str, int]  # (dataset_id, revision)


@dataclass(frozen=True, slots=True)
class CachedDataset:
    digest: str  # SHA-256 of the snapshot the dataset was encoded to / decoded from
    dataset: Dataset


DatasetCache = LruCache[DatasetKey, CachedDataset]

_KEY_COLUMNS = (datasets.c.dataset_id, datasets.c.revision, datasets.c.snapshot_sha256)


def _describe(key: DatasetKey) -> str:
    return f"dataset {key[0]!r} revision {key[1]}"


class SqlDatasetRepository(SqlRepository):
    def __init__(self, scope: UnitOfWorkScope[Connection], cache: DatasetCache) -> None:
        super().__init__(scope)
        self._cache = cache

    def add(self, dataset: Dataset) -> None:
        connection = self._connection
        key = (dataset.dataset_id, dataset.revision)
        snapshot = encode_dataset(dataset)
        digest = hashlib.sha256(snapshot.data).hexdigest()
        row = {
            **dataset_columns(dataset),
            "seq": next_sequence_value(connection, datasets),
            "snapshot": snapshot.data,
            "snapshot_codec": snapshot.codec,
            "snapshot_sha256": digest,
        }
        insert_rows(connection, datasets, [row], what=_describe(key))
        self._cache.put(key, CachedDataset(digest, dataset))

    def get(self, dataset_id: str, revision: int | None = None) -> Dataset | None:
        """Latest revision when ``revision`` is None (always resolved in the database)."""
        statement = select(*_KEY_COLUMNS).where(datasets.c.dataset_id == dataset_id)
        if revision is None:
            statement = statement.order_by(datasets.c.revision.desc()).limit(1)
        else:
            statement = statement.where(datasets.c.revision == revision)
        connection = self._connection
        row = connection.execute(statement).first()
        if row is None:
            return None
        return self._load(connection, [row])[0]

    def list_for_document(self, document_id: str) -> list[Dataset]:
        """All revisions of the document's datasets, oldest first."""
        connection = self._connection
        rows = connection.execute(
            select(*_KEY_COLUMNS)
            .where(datasets.c.document_id == document_id)
            .order_by(*order_by(datasets, DATASET_ORDER))
        ).all()
        return self._load(connection, rows)

    def latest_for_document(self, document_id: str) -> Dataset | None:
        """The latest dataset by creation at its highest revision (rule:
        :func:`~app.repositories.querying.latest_dataset_key`). Reads only the key columns of
        the document's revisions (a handful) and decodes one snapshot at most."""
        row = self._latest_row(document_id)
        return None if row is None else self._load(self._connection, [row])[0]

    def latest_counts_for_document(self, document_id: str) -> DatasetCounts | None:
        """The same revision's stored counts; decodes nothing."""
        row = self._latest_row(document_id, datasets.c.table_count, datasets.c.row_count)
        if row is None:
            return None
        return DatasetCounts(row.dataset_id, row.revision, row.table_count, row.row_count)

    def _latest_row(self, document_id: str, *columns: Column[Any]) -> _AnyRow | None:
        """The key columns (and ``columns``) of the document's latest revision."""
        rows = self._connection.execute(
            select(*_KEY_COLUMNS, *columns)
            .where(datasets.c.document_id == document_id)
            .order_by(*order_by(datasets, DATASET_ORDER))
        ).all()
        key = latest_dataset_key((row.dataset_id, row.revision) for row in rows)
        return None if key is None else next(r for r in rows if (r.dataset_id, r.revision) == key)

    def _load(self, connection: Connection, rows: Sequence[_AnyRow]) -> list[Dataset]:
        """Datasets for ``(dataset_id, revision, snapshot_sha256)`` rows, in row order: from the
        cache when the digest matches, otherwise fetched and decoded in one query."""
        loaded: dict[DatasetKey, Dataset] = {}
        missing: list[DatasetKey] = []
        for row in rows:
            key = (row.dataset_id, row.revision)
            cached = self._cache.get(key)
            if cached is not None and cached.digest == row.snapshot_sha256:
                loaded[key] = cached.dataset
            else:
                missing.append(key)
        if missing:
            snapshots = connection.execute(
                select(*_KEY_COLUMNS, datasets.c.snapshot, datasets.c.snapshot_codec).where(
                    tuple_(datasets.c.dataset_id, datasets.c.revision).in_(missing)
                )
            )
            for snapshot_row in snapshots:
                key = (snapshot_row.dataset_id, snapshot_row.revision)
                dataset = _decode(key, snapshot_row)
                self._cache.put(key, CachedDataset(snapshot_row.snapshot_sha256, dataset))
                loaded[key] = dataset
        result: list[Dataset] = []
        for row in rows:
            found = loaded.get((row.dataset_id, row.revision))
            if found is None:  # no deletes exist; this would be a concurrent schema change
                raise PersistenceError(f"{_describe((row.dataset_id, row.revision))} vanished.")
            result.append(found)
        return result


def _decode(key: DatasetKey, row: _AnyRow) -> Dataset:
    """Decode a stored snapshot after checking its digest and the identity it holds."""
    if hashlib.sha256(row.snapshot).hexdigest() != row.snapshot_sha256:
        raise CorruptSnapshotError(
            f"The snapshot of {_describe(key)} does not match its stored SHA-256."
        )
    dataset = decode_dataset(
        EncodedSnapshot(codec=row.snapshot_codec, data=row.snapshot),
        what=f"snapshot of {_describe(key)}",
    )
    if (dataset.dataset_id, dataset.revision) != key:
        raise CorruptSnapshotError(
            f"The snapshot stored as {_describe(key)} holds "
            f"{_describe((dataset.dataset_id, dataset.revision))}."
        )
    return dataset
