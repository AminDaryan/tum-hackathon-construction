"""The SQL database: engine, SQLite connection and transaction settings, schema creation,
version check and upgrades (:mod:`app.repositories.sql.migrations`)."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Connection,
    Engine,
    RootTransaction,
    create_engine,
    event,
    func,
    insert,
    inspect,
    select,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from app.core.config import AutoUpgradePolicy
from app.repositories.errors import PersistenceError, SchemaVersionError, UnitOfWorkError
from app.repositories.lru_cache import DEFAULT_MAX_ENTRIES, LruCache
from app.repositories.records import dumps_strict
from app.repositories.sql import migrations
from app.repositories.sql.datasets import DatasetCache
from app.repositories.sql.migrations import Migration
from app.repositories.sql.schema import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_KEY,
    SEQUENCED_TABLES,
    metadata,
    schema_info,
    sequence_counters,
)
from app.repositories.transactions import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ExclusiveLock,
    NestingGuard,
)

logger = logging.getLogger(__name__)

# How long a unit of work waits for another one's write lock on a SQLite file before it fails
# with UnitOfWorkError: as long as the in-memory adapters wait for their lock, so a waiting
# request outlasts the longest expected write (storing a large run) but never hangs.
DEFAULT_BUSY_TIMEOUT_MS = int(DEFAULT_LOCK_TIMEOUT_SECONDS * 1000)
_SQLITE_BUSY_CODES = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
# The command that upgrades a database by hand (app/cli.py).
UPGRADE_COMMAND = "python -m app.cli db upgrade"
# PostgreSQL advisory lock held while the schema is prepared ("TWB" in ASCII).
SCHEMA_LOCK_KEY = 0x545742


class Database:
    """Owns the engine and the decoded-dataset cache; create one per process and share it.

    ``url`` is any SQLAlchemy URL, normally ``Settings.resolved_database_url``. For SQLite the
    settings needed for use from FastAPI's thread pool are applied to every connection:
    ``check_same_thread=False``, ``PRAGMA foreign_keys=ON``, ``busy_timeout`` and, for file
    databases, ``journal_mode=WAL``; missing parent directories of the file are created.

    SQLite transactions (ADR 0005): the driver is put in autocommit mode
    (``isolation_level = None``; its legacy transaction control would send ``BEGIN`` only at
    the first write, leaving earlier reads outside the transaction) and every transaction
    starts with ``BEGIN IMMEDIATE``, emitted in the engine's ``begin`` event. A unit of work's
    reads and writes are therefore one transaction holding the write lock, and concurrent
    units of work run one after the other: a writer waits up to ``busy_timeout_ms`` for the
    lock, then :meth:`begin` raises :class:`UnitOfWorkError`. Units of work cannot be nested
    in one thread (the inner one would wait for the outer one's lock). In-memory SQLite
    (``sqlite://``, for tests) is one shared connection (``StaticPool``), so its units of
    work are additionally serialized by a lock. Other databases (PostgreSQL) keep the
    driver's own transaction handling.

    Construction creates missing tables and records :data:`SCHEMA_VERSION` in ``schema_info``.
    A database of an older schema version is upgraded by :mod:`.migrations` in the same
    transaction when ``auto_upgrade`` allows it for this backend (``"sqlite"``: SQLite only,
    the default of ``Settings.persistence.auto_upgrade``; ``"always"``; ``"never"``), after a
    copy of a SQLite file was written next to it (``backup_before_upgrade``); otherwise it is
    refused with :class:`SchemaVersionError` naming ``python -m app.cli db upgrade``. A database
    of a newer or unreadable version, or holding workbench tables without a recorded version,
    is always refused. ``migrations_applied`` lists the steps construction applied.
    """

    def __init__(
        self,
        url: str | URL,
        *,
        dataset_cache_entries: int = DEFAULT_MAX_ENTRIES,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        auto_upgrade: AutoUpgradePolicy = "sqlite",
        backup_before_upgrade: bool = True,
        echo: bool = False,
    ) -> None:
        if busy_timeout_ms < 0:
            raise ValueError(f"busy_timeout_ms must be >= 0, got {busy_timeout_ms}")
        self.url = make_url(url)
        self.is_sqlite = self.url.get_backend_name() == "sqlite"
        self.in_memory = self.is_sqlite and _is_memory_url(self.url)
        self.auto_upgrade = upgrades_automatically(auto_upgrade, is_sqlite=self.is_sqlite)
        self.migrations_applied: tuple[Migration, ...] = ()
        if self.is_sqlite and not self.in_memory:
            _create_parent_directory(self.url)
        self.engine = _create_engine(self.url, in_memory=self.in_memory, echo=echo)
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.is_sqlite:
            event.listen(
                self.engine,
                "connect",
                _SqliteConnectionSettings(busy_timeout_ms=busy_timeout_ms, wal=not self.in_memory),
            )
            event.listen(self.engine, "begin", _begin_immediate)
        self._gate = _unit_of_work_gate(
            is_sqlite=self.is_sqlite,
            in_memory=self.in_memory,
            lock_timeout_seconds=lock_timeout_seconds,
        )
        self.dataset_cache: DatasetCache = LruCache(dataset_cache_entries)
        backup = backup_before_upgrade and self.is_sqlite and not self.in_memory
        try:
            with self.connect() as connection, self.begin(connection):
                self.migrations_applied = prepare_schema(
                    connection,
                    auto_upgrade=self.auto_upgrade,
                    before_upgrade=self._backup_file if backup else None,
                )
        except BaseException:
            self.engine.dispose()
            raise

    def _backup_file(self, version: int) -> None:
        copy = backup_sqlite_file(self.url, label=f"schema-v{version}")
        if copy is None:
            logger.warning("No copy of the SQLite database was made before upgrading it.")
        else:
            logger.info("Copied the SQLite database to %s before upgrading it", copy)

    @classmethod
    def in_memory_sqlite(cls, **options: Any) -> Database:
        """A private in-memory SQLite database (tests)."""
        return cls("sqlite://", **options)

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        """A connection for one unit of work (exclusive on in-memory SQLite; on SQLite, a
        second one in the same thread raises :class:`UnitOfWorkError`)."""
        gate = self._gate.hold() if self._gate is not None else nullcontext()
        with gate, self.engine.connect() as connection:
            yield connection

    def begin(self, connection: Connection) -> RootTransaction:
        """Start the transaction of a unit of work on ``connection``.

        On SQLite this takes the write lock (``BEGIN IMMEDIATE``); a database that stays
        locked by another writer for longer than the busy timeout raises
        :class:`UnitOfWorkError`.
        """
        try:
            return connection.begin()
        except OperationalError as exc:
            if self.is_sqlite and _is_busy(exc):
                raise UnitOfWorkError(
                    f"The database stayed busy for more than {self.busy_timeout_ms} ms: "
                    "another unit of work held its write lock.",
                    details={"busy_timeout_ms": self.busy_timeout_ms},
                ) from exc
            raise

    def dispose(self) -> None:
        """Close all pooled connections and drop cached datasets."""
        self.dataset_cache.clear()
        self.engine.dispose()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.dispose()

    def __repr__(self) -> str:
        return f"Database({self.url.render_as_string(hide_password=True)!r})"


def upgrades_automatically(policy: AutoUpgradePolicy, *, is_sqlite: bool) -> bool:
    """Whether ``policy`` (``Settings.persistence.auto_upgrade``) upgrades an older database of
    this backend at start-up."""
    return policy == "always" or (policy == "sqlite" and is_sqlite)


def prepare_schema(
    connection: Connection,
    *,
    auto_upgrade: bool = False,
    before_upgrade: Callable[[int], None] | None = None,
) -> tuple[Migration, ...]:
    """Verify (or record) the schema version, upgrade an older database when
    ``auto_upgrade`` (``before_upgrade`` is called with its version first), create missing
    tables and seed the insertion sequences. Runs inside the caller's transaction; returns the
    migration steps applied."""
    if connection.dialect.name == "postgresql":
        # Instances starting at the same time prepare (and upgrade) the schema one by one.
        connection.execute(select(func.pg_advisory_xact_lock(SCHEMA_LOCK_KEY)))
    existing = set(inspect(connection).get_table_names())
    applied: tuple[Migration, ...] = ()
    if schema_info.name in existing:
        version = _verified_schema_version(connection, auto_upgrade=auto_upgrade)
        if version < SCHEMA_VERSION:
            if before_upgrade is not None:
                before_upgrade(version)
            applied = migrations.upgrade(connection, version)
    else:
        ours = sorted(existing & set(metadata.tables))
        if ours:
            raise SchemaVersionError(
                f"The database holds workbench tables ({', '.join(ours)}) but no "
                f"{schema_info.name!r} table, so its schema version is unknown. Refusing to use "
                "it: migrate it or configure a new database.",
                details={"tables": ours},
            )
    metadata.create_all(connection)
    if schema_info.name not in existing:
        connection.execute(
            insert(schema_info).values(key=SCHEMA_VERSION_KEY, value=str(SCHEMA_VERSION))
        )
        logger.info("Created workbench database schema version %s", SCHEMA_VERSION)
    _seed_sequence_counters(connection)
    return applied


def stored_schema_version(connection: Connection) -> str | None:
    """The raw schema version recorded in ``schema_info`` (``None`` when none is recorded)."""
    return connection.execute(
        select(schema_info.c.value).where(schema_info.c.key == SCHEMA_VERSION_KEY)
    ).scalar_one_or_none()


def _verified_schema_version(connection: Connection, *, auto_upgrade: bool) -> int:
    """The recorded schema version when this build may use the database (an older one only
    when it is upgraded automatically); anything else is refused before any table is created
    or read."""
    stored = stored_schema_version(connection)
    if stored == str(SCHEMA_VERSION):  # always written as str(the version)
        return SCHEMA_VERSION
    details = {"found": stored, "expected": SCHEMA_VERSION}
    found = parse_schema_version(stored)
    if found is not None and found < SCHEMA_VERSION:
        if auto_upgrade:
            return found
        raise SchemaVersionError(
            f"The database {_describe_version(stored)}, but this build requires version "
            f"{SCHEMA_VERSION}, and automatic upgrades are off for this database "
            "(TWB_PERSISTENCE__AUTO_UPGRADE). Back it up, then upgrade it with "
            f"'{UPGRADE_COMMAND}'.",
            details=details,
        )
    raise SchemaVersionError(
        f"The database {_describe_version(stored)}, but this build requires version "
        f"{SCHEMA_VERSION}. Refusing to use it, so its records are not misread: use the build "
        "that wrote it, or configure a new database (TWB_DATABASE_URL).",
        details=details,
    )


def parse_schema_version(stored: str | None) -> int | None:
    """A recorded schema version as a number; ``None`` when it is missing or unreadable."""
    if stored is None or re.fullmatch(r"[0-9]{1,9}", stored) is None:
        return None
    return int(stored)


def _describe_version(stored: str | None) -> str:
    found = parse_schema_version(stored)
    if stored is None:
        return "records no schema version"
    if found is not None and found < SCHEMA_VERSION:
        return f"has schema version {stored}, written by an older build"
    if found is not None:
        return f"has schema version {stored}, written by a newer build"
    return f"has an unreadable schema version {stored!r}"


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    """What :func:`schema_status` found: whether the database exists, the version it records
    (raw text, ``None`` when it records none or is empty) and the steps an upgrade applies."""

    url: str  # with the password hidden
    exists: bool
    has_tables: bool
    stored: str | None
    pending: tuple[Migration, ...]

    @property
    def up_to_date(self) -> bool:
        return self.stored == str(SCHEMA_VERSION)


def schema_status(url: str | URL) -> SchemaStatus:
    """Read a database's schema version without creating, changing or upgrading anything (a
    SQLite file that does not exist is reported, not created)."""
    parsed = make_url(url)
    shown = parsed.render_as_string(hide_password=True)
    is_sqlite = parsed.get_backend_name() == "sqlite"
    if is_sqlite and _is_memory_url(parsed):
        return SchemaStatus(shown, exists=False, has_tables=False, stored=None, pending=())
    database = parsed.database or ""
    if is_sqlite and not database.startswith("file:") and not Path(database).is_file():
        return SchemaStatus(shown, exists=False, has_tables=False, stored=None, pending=())
    engine = _create_engine(parsed, in_memory=False, echo=False)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            stored = stored_schema_version(connection) if schema_info.name in tables else None
    finally:
        engine.dispose()
    found = parse_schema_version(stored)
    steps = migrations.pending(found) if found is not None and found < SCHEMA_VERSION else ()
    return SchemaStatus(
        shown,
        exists=True,
        has_tables=bool(tables & set(metadata.tables)),
        stored=stored,
        pending=steps,
    )


def backup_sqlite_file(url: URL, *, label: str) -> Path | None:
    """Copy the SQLite file behind ``url`` next to it, as ``<name>.<label>-<UTC time>.bak``,
    with SQLite's online backup (a consistent copy, also of a database in WAL mode). Returns
    the copy's path; ``None`` when ``url`` names no plain file (memory, URI filenames)."""
    database = url.database
    if not database or database.startswith("file:") or _is_memory_url(url):
        return None
    source_path = Path(os.path.abspath(database))
    if not source_path.is_file():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target_path = source_path.with_name(f"{source_path.name}.{label}-{stamp}.bak")
    with (
        closing(sqlite3.connect(source_path)) as source,
        closing(sqlite3.connect(target_path)) as target,
    ):
        source.backup(target)
    return target_path


def _seed_sequence_counters(connection: Connection) -> None:
    """Add a missing counter row per sequenced table, starting after the table's highest seq."""
    present = set(connection.execute(select(sequence_counters.c.name)).scalars())
    for table in SEQUENCED_TABLES:
        if table.name in present:
            continue
        highest = connection.execute(select(func.coalesce(func.max(table.c.seq), 0))).scalar_one()
        connection.execute(insert(sequence_counters).values(name=table.name, value=highest))


class _SqliteConnectionSettings:
    """``connect`` event handler applying per-connection SQLite settings."""

    def __init__(self, *, busy_timeout_ms: int, wal: bool) -> None:
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._wal = wal

    def __call__(self, dbapi_connection: Any, _connection_record: Any) -> None:
        # Autocommit mode: the driver emits no BEGIN of its own (it still sends COMMIT and
        # ROLLBACK for the transaction _begin_immediate opens).
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            if cursor.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise PersistenceError(
                    "This SQLite build does not enforce foreign keys; refusing to use it."
                )
            cursor.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms:d}")
            if self._wal:
                mode = cursor.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if str(mode).lower() != "wal":
                    logger.warning(
                        "SQLite kept journal mode %r instead of WAL (unsupported file system?); "
                        "readers will wait for writers.",
                        mode,
                    )
        finally:
            cursor.close()


def _begin_immediate(connection: Connection) -> None:
    """``begin`` event handler: open every SQLite transaction with the write lock, so its reads
    and writes are one transaction and concurrent writers wait instead of interleaving."""
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def _is_busy(error: OperationalError) -> bool:
    """True when SQLite reported that the database is locked by another connection."""
    code = getattr(error.orig, "sqlite_errorcode", None)
    return isinstance(code, int) and code & 0xFF in _SQLITE_BUSY_CODES


def _unit_of_work_gate(
    *, is_sqlite: bool, in_memory: bool, lock_timeout_seconds: float
) -> ExclusiveLock | NestingGuard | None:
    """What :meth:`Database.connect` holds: an exclusive lock for the single connection of an
    in-memory database, a nesting guard for SQLite files, nothing elsewhere."""
    if in_memory:
        return ExclusiveLock("the in-memory SQLite database", timeout_seconds=lock_timeout_seconds)
    if is_sqlite:
        return NestingGuard("the SQLite database")
    return None


def _create_engine(url: URL, *, in_memory: bool, echo: bool) -> Engine:
    options: dict[str, Any] = {"echo": echo, "json_serializer": dumps_strict}
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if in_memory:
            options["poolclass"] = StaticPool
    else:
        options["pool_pre_ping"] = True
    return create_engine(url, **options)


def _is_memory_url(url: URL) -> bool:
    """The same rule SQLAlchemy's pysqlite dialect uses to tell memory from file databases."""
    database = url.database
    return not database or database == ":memory:" or url.query.get("mode") == "memory"


def _create_parent_directory(url: URL) -> None:
    database = url.database
    if database is None or database.startswith("file:"):
        return  # URI filenames are resolved by SQLite itself
    Path(os.path.abspath(database)).parent.mkdir(parents=True, exist_ok=True)
