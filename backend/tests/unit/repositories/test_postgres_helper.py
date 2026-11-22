"""The switch that runs the persistence and API tests on PostgreSQL as well."""

from __future__ import annotations

import pytest

from tests.unit.repositories.postgres import (
    POSTGRESQL,
    REQUIRE_VARIABLE,
    TEST_DATABASE_URL_VARIABLE,
    backends,
)


def test_postgresql_joins_the_backends_only_with_a_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(REQUIRE_VARIABLE, raising=False)
    monkeypatch.delenv(TEST_DATABASE_URL_VARIABLE, raising=False)
    assert backends("memory", "sqlite") == ("memory", "sqlite")
    monkeypatch.setenv(TEST_DATABASE_URL_VARIABLE, "postgresql+pg8000://u@127.0.0.1:1/x")
    assert backends("memory", "sqlite") == ("memory", "sqlite", POSTGRESQL)


def test_a_required_but_missing_test_database_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CI's postgres job sets the requirement: a misnamed URL variable must fail the job."""
    monkeypatch.delenv(TEST_DATABASE_URL_VARIABLE, raising=False)
    monkeypatch.setenv(REQUIRE_VARIABLE, "1")
    with pytest.raises(RuntimeError, match=TEST_DATABASE_URL_VARIABLE):
        backends("sqlite")
    monkeypatch.setenv(TEST_DATABASE_URL_VARIABLE, "postgresql+pg8000://u@127.0.0.1:1/x")
    assert backends("sqlite") == ("sqlite", POSTGRESQL)
