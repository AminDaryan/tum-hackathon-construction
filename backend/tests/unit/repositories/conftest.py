"""Fixtures: every test using ``uow_factory`` runs once per adapter (in-memory, SQLite and,
when ``TWB_TEST_DATABASE_URL`` names one, PostgreSQL: see :mod:`tests.unit.repositories.postgres`).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.models.dataset import Dataset
from app.models.profile import DomainProfile
from app.repositories.base import UnitOfWorkFactory
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.repositories.sql import Database, SqlUnitOfWorkFactory
from tests.unit.repositories.postgres import POSTGRESQL, backends, fresh_postgres_url
from tests.unit.repositories.samples import build_dataset

ADAPTERS = backends("memory", "sqlite")
# Backends whose units of work share one connection, so they cannot nest in one thread.
SINGLE_CONNECTION_ADAPTERS = ("memory", "sqlite")


def _factory(adapter: str) -> Iterator[UnitOfWorkFactory]:
    if adapter == "memory":
        yield InMemoryUnitOfWorkFactory(InMemoryDatabase())
        return
    url = fresh_postgres_url() if adapter == POSTGRESQL else "sqlite://"
    with Database(url) as database:
        yield SqlUnitOfWorkFactory(database)


@pytest.fixture(params=ADAPTERS)
def uow_factory(request: pytest.FixtureRequest) -> Iterator[UnitOfWorkFactory]:
    """A fresh, empty database behind the adapter named by the parameter."""
    yield from _factory(request.param)


@pytest.fixture(params=SINGLE_CONNECTION_ADAPTERS)
def single_connection_uow_factory(request: pytest.FixtureRequest) -> Iterator[UnitOfWorkFactory]:
    """Like ``uow_factory``, for the adapters with one shared connection (in-memory storage and
    in-memory SQLite)."""
    yield from _factory(request.param)


@pytest.fixture(params=backends("sqlite"))
def sql_database(request: pytest.FixtureRequest) -> Iterator[Database]:
    url = fresh_postgres_url() if request.param == POSTGRESQL else "sqlite://"
    with Database(url) as database:
        yield database


@pytest.fixture
def file_database_url(tmp_path) -> str:
    """URL of a file database whose parent directories do not exist yet."""
    return f"sqlite:///{(tmp_path / 'nested' / 'data' / 'workbench.sqlite3').as_posix()}"


@pytest.fixture
def dataset(boq_profile: DomainProfile) -> Dataset:
    return build_dataset(boq_profile)
