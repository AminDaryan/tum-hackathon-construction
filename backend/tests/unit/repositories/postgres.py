"""PostgreSQL for the persistence and API tests.

Set ``TWB_TEST_DATABASE_URL`` to the URL of a PostgreSQL database the tests may wipe (for
example ``postgresql+pg8000://postgres@127.0.0.1:5432/twb_test``, with the ``postgres`` extra
installed) and every test parametrized with :func:`backends` runs against it as well; without
it they run on in-memory storage and SQLite only. Each test starts from an empty database.

``TWB_TEST_REQUIRE_POSTGRESQL=1`` (set by CI's postgres job) turns a missing URL into an error
at collection, so a misnamed or missing variable cannot leave that job green without testing
PostgreSQL.
"""

from __future__ import annotations

import os

from sqlalchemy import MetaData, create_engine

TEST_DATABASE_URL_VARIABLE = "TWB_TEST_DATABASE_URL"
REQUIRE_VARIABLE = "TWB_TEST_REQUIRE_POSTGRESQL"
POSTGRESQL = "postgresql"


def postgres_url() -> str | None:
    return os.environ.get(TEST_DATABASE_URL_VARIABLE) or None


def backends(*base: str) -> tuple[str, ...]:
    """``base`` plus ``"postgresql"`` when a test database is configured. Raises when
    ``TWB_TEST_REQUIRE_POSTGRESQL=1`` and none is."""
    if postgres_url():
        return (*base, POSTGRESQL)
    if os.environ.get(REQUIRE_VARIABLE) == "1":
        raise RuntimeError(
            f"{REQUIRE_VARIABLE}=1 but {TEST_DATABASE_URL_VARIABLE} is not set, so the "
            "PostgreSQL tests would not run"
        )
    return base


def fresh_postgres_url() -> str:
    """The test database's URL after dropping every table in it."""
    url = postgres_url()
    if url is None:
        raise RuntimeError(f"{TEST_DATABASE_URL_VARIABLE} is not set")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            tables = MetaData()
            tables.reflect(connection)
            tables.drop_all(connection)
    finally:
        engine.dispose()
    return url
