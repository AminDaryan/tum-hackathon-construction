"""SQL adapter specifics: file databases, SQLite settings, schema versioning, thread pool use
and PostgreSQL-compatible DDL."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models.dataset import Dataset
from app.repositories.base import IssueQuery
from app.repositories.errors import SchemaVersionError
from app.repositories.querying import ISSUE_ORDER, issue_conditions
from app.repositories.sql import SCHEMA_VERSION, Database, SqlUnitOfWorkFactory
from app.repositories.sql import schema as sql_schema
from app.repositories.sql.database import UPGRADE_COMMAND
from app.repositories.sql.statements import order_by, where
from tests.unit.repositories.samples import make_document, minutes


def _sqlite_path(url: str) -> Path:
    return Path(url.removeprefix("sqlite:///"))


def _execute_raw(url: str, statement: str) -> None:
    """Change the database behind the adapter's back (simulates another build or tool)."""
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def test_file_database_creates_directories_and_records_the_schema_version(
    file_database_url: str,
) -> None:
    assert not _sqlite_path(file_database_url).parent.exists()
    with Database(file_database_url) as database:
        assert not database.in_memory
        with database.connect() as connection:
            stored = connection.execute(
                select(sql_schema.schema_info.c.value).where(
                    sql_schema.schema_info.c.key == "schema_version"
                )
            ).scalar_one()
    assert _sqlite_path(file_database_url).is_file()
    assert stored == str(SCHEMA_VERSION) == "13"


def test_sqlite_connections_enforce_foreign_keys_wal_and_busy_timeout(
    file_database_url: str,
) -> None:
    with Database(file_database_url, busy_timeout_ms=2_500) as database:
        with database.connect() as connection:
            pragma = {
                name: connection.exec_driver_sql(f"PRAGMA {name}").scalar()
                for name in ("foreign_keys", "journal_mode", "busy_timeout")
            }
        assert pragma == {"foreign_keys": 1, "journal_mode": "wal", "busy_timeout": 2_500}


def test_in_memory_database_shares_one_connection_and_enforces_foreign_keys() -> None:
    with Database.in_memory_sqlite() as database:
        assert database.in_memory
        assert isinstance(database.engine.pool, StaticPool)
        with database.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_data_survives_reopening_the_file(file_database_url: str, dataset: Dataset) -> None:
    with Database(file_database_url) as database, SqlUnitOfWorkFactory(database)() as uow:
        uow.documents.add(make_document())
        uow.datasets.add(dataset)
    with Database(file_database_url) as reopened, SqlUnitOfWorkFactory(reopened)() as uow:
        assert uow.documents.get("doc_000001") == make_document()
        assert uow.datasets.get(dataset.dataset_id) == dataset
        uow.documents.add(make_document("doc_000002", uploaded_at=minutes(-1)))
        # The insertion sequence continues after reopening: the tie order stays correct.
        uow.documents.add(make_document("doc_000003"))
        ids = [d.document_id for d in uow.documents.list().items]
    assert ids == ["doc_000003", "doc_000001", "doc_000002"]


@pytest.mark.parametrize(
    ("found", "described", "advice"),
    [
        ("4", "written by an older build", UPGRADE_COMMAND),  # when not upgraded automatically
        (str(SCHEMA_VERSION + 1), "written by a newer build", "configure a new database"),
        ("two", "unreadable", "configure a new database"),
    ],
)
def test_a_database_with_another_schema_version_is_refused(
    file_database_url: str, found: str, described: str, advice: str
) -> None:
    Database(file_database_url).dispose()
    _execute_raw(
        file_database_url, f"UPDATE schema_info SET value = '{found}' WHERE key = 'schema_version'"
    )
    with pytest.raises(
        SchemaVersionError, match=rf"{described}.*requires version {SCHEMA_VERSION}"
    ) as refused:
        Database(file_database_url, auto_upgrade="never")
    assert refused.value.details == {"found": found, "expected": SCHEMA_VERSION}
    assert advice in refused.value.message
    if found != "4":  # never upgraded, whatever the policy says
        with pytest.raises(SchemaVersionError, match=described):
            Database(file_database_url, auto_upgrade="always")


def test_a_version_1_database_is_refused_before_anything_is_read_or_created(
    file_database_url: str,
) -> None:
    # The layout of schema version 1: issues without document_id, version, reviewed_at, seq.
    _sqlite_path(file_database_url).parent.mkdir(parents=True)
    for statement in (
        "CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "INSERT INTO schema_info VALUES ('schema_version', '1')",
        "CREATE TABLE issues (issue_id TEXT PRIMARY KEY, validation_run_id TEXT NOT NULL, "
        "fingerprint TEXT NOT NULL, review_status TEXT NOT NULL, payload JSON NOT NULL)",
    ):
        _execute_raw(file_database_url, statement)
    with pytest.raises(SchemaVersionError, match=r"schema version 1, written by an older build"):
        Database(file_database_url, auto_upgrade="never")
    connection = sqlite3.connect(_sqlite_path(file_database_url))
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(issues)")}
    finally:
        connection.close()
    assert tables == {"schema_info", "issues", "sqlite_autoindex_schema_info_1",
                      "sqlite_autoindex_issues_1"}  # fmt: skip
    assert "version" not in columns  # nothing was added to the old table


def test_a_database_without_a_recorded_version_is_refused(file_database_url: str) -> None:
    Database(file_database_url).dispose()
    _execute_raw(file_database_url, "DELETE FROM schema_info")
    with pytest.raises(
        SchemaVersionError, match=rf"records no schema version.*requires version {SCHEMA_VERSION}"
    ):
        Database(file_database_url)


def test_workbench_tables_without_schema_info_are_refused(file_database_url: str) -> None:
    _sqlite_path(file_database_url).parent.mkdir(parents=True)
    _execute_raw(file_database_url, "CREATE TABLE documents (document_id TEXT PRIMARY KEY)")
    with pytest.raises(SchemaVersionError, match="no 'schema_info' table"):
        Database(file_database_url)


def test_units_of_work_from_a_thread_pool_on_a_file_database(file_database_url: str) -> None:
    with Database(file_database_url) as database:
        factory = SqlUnitOfWorkFactory(database)

        def upload(n: int) -> None:
            with factory() as uow:
                uow.documents.add(make_document(f"doc_{n:03d}", uploaded_at=minutes(0)))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(upload, range(40)))
        with factory() as uow:
            page = uow.documents.list(limit=100)
        with database.connect() as connection:
            seqs = list(connection.execute(select(sql_schema.documents.c.seq)).scalars())
    assert page.total == 40
    assert len({d.document_id for d in page.items}) == 40
    assert sorted(seqs) == list(range(1, 41))  # unique, gap-free insertion sequence


def test_schema_and_issue_queries_compile_for_postgresql() -> None:
    dialect = postgresql.dialect()
    ddl = {
        table.name: str(CreateTable(table).compile(dialect=dialect))
        for table in sql_schema.metadata.sorted_tables
    }
    assert "uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl["documents"]
    assert "snapshot BYTEA NOT NULL" in ddl["datasets"]
    assert "payload JSON NOT NULL" in ddl["issues"]
    for table in sql_schema.metadata.sorted_tables:
        for index in table.indexes:
            assert len(index.name) <= 63  # PostgreSQL identifier limit
            CreateIndex(index).compile(dialect=dialect)
    issues = sql_schema.issues
    query = IssueQuery(run_id="run_1", severities=frozenset({"high", "low"}))
    sql = str(
        select(issues.c.issue_id)
        .where(*where(issues, issue_conditions(query)))
        .order_by(*order_by(issues, ISSUE_ORDER))
        .compile(dialect=dialect)
    )
    assert "ORDER BY CASE WHEN (issues.detector_id IN (" in sql  # style findings last
    assert "END ASC, issues.severity_rank DESC, issues.sort_sheet ASC NULLS LAST" in sql
    assert "issues.sort_row ASC NULLS FIRST, issues.sort_column ASC NULLS FIRST" in sql
    assert sql.endswith(  # text by code point, as SQLite and the in-memory adapter order it
        'issues.detector_id COLLATE "C" ASC, issues.rule_id COLLATE "C" ASC, '
        'issues.fingerprint COLLATE "C" ASC, issues.seq ASC, issues.issue_id COLLATE "C" ASC'
    )
    on_sqlite = select(issues.c.issue_id).order_by(*order_by(issues, ISSUE_ORDER))
    assert "COLLATE" not in str(on_sqlite.compile(dialect=sqlite.dialect()))
