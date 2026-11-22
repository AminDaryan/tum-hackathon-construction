"""A dataset of about 20,000 cells round-trips through a file database quickly and exactly."""

from __future__ import annotations

import time

import pytest

from app.models.dataset import Dataset
from app.models.profile import DomainProfile
from app.repositories.sql import Database, SqlUnitOfWorkFactory
from tests.support.builders import DatasetBuilder
from tests.unit.repositories.samples import BOQ_COLUMNS, make_document

ROWS = 3_334  # x 6 columns = 20,004 cells
MAX_SECONDS = 3.0


def _large_dataset(profile: DomainProfile) -> Dataset:
    builder = DatasetBuilder(profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for i in range(ROWS):
        quantity = f"{i % 97}.125"
        table.row(
            [f"01.{i:05d}", f"Position {i} – Beton C25/30", quantity, "m³", "12.40", f"{i}.50"]
        )
    return builder.build()


@pytest.mark.performance
def test_twenty_thousand_cells_round_trip_well_under_a_few_seconds(
    boq_profile: DomainProfile, file_database_url: str
) -> None:
    dataset = _large_dataset(boq_profile)
    assert sum(len(row.cells) for table in dataset.tables for row in table.rows) >= 20_000
    with Database(file_database_url) as database:
        factory = SqlUnitOfWorkFactory(database)
        started = time.perf_counter()
        with factory() as uow:
            uow.documents.add(make_document())
            uow.datasets.add(dataset)
        database.dataset_cache.clear()  # force a real decode
        with factory() as uow:
            loaded = uow.datasets.get(dataset.dataset_id)
        elapsed = time.perf_counter() - started
    assert loaded == dataset
    assert elapsed < MAX_SECONDS, f"round trip took {elapsed:.2f}s"
