"""Command line of the workbench: ``python -m app.cli db current`` and ``db upgrade``.

``db current`` reports the schema version a database records, the version this build needs
and the migrations an upgrade would apply, without creating or changing anything. ``db
upgrade`` applies them in one transaction (a SQLite file is first copied next to itself,
unless ``--no-backup``); a database that does not exist yet is created at the current version.
Both use the configured database (``TWB_DATABASE_URL``, or the SQLite file in
``TWB_DATA_DIR``) unless ``--database-url`` names another.

Exit status: 0 on success; 1 when ``db current --check`` finds an upgrade pending; 2 when the
database is refused (written by a newer build, unreadable or unversioned), cannot be opened or
read (a damaged file, an unreachable server, a missing driver) or cannot be upgraded.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from typing import TextIO

from sqlalchemy.exc import ArgumentError, DBAPIError, NoSuchModuleError, SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.repositories.errors import PersistenceError
from app.repositories.sql.database import Database, schema_status
from app.repositories.sql.schema import SCHEMA_VERSION

EXIT_OK = 0
EXIT_UPGRADE_PENDING = 1
EXIT_REFUSED = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="Tabular Integrity Workbench administration."
    )
    groups = parser.add_subparsers(dest="group", required=True)
    database = groups.add_parser("db", help="the database schema version and its upgrades")
    actions = database.add_subparsers(dest="action", required=True)
    current = actions.add_parser(
        "current", help="show the schema version and the pending migrations; change nothing"
    )
    current.add_argument(
        "--check", action="store_true", help="exit with status 1 when an upgrade is pending"
    )
    upgrade = actions.add_parser("upgrade", help="upgrade the database to this build's version")
    upgrade.add_argument(
        "--no-backup", action="store_true", help="do not copy a SQLite file before upgrading it"
    )
    for action in (current, upgrade):
        action.add_argument("--database-url", help="the database (default: the configured one)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run one command; returns the exit status."""
    args = _parser().parse_args(argv)
    settings = settings or get_settings()
    out = out or sys.stdout
    err = err or sys.stderr
    url = args.database_url or settings.resolved_database_url
    try:
        if args.action == "current":
            return _current(url, check=args.check, out=out)
        return _upgrade(url, settings=settings, backup=not args.no_backup, out=out)
    except PersistenceError as exc:
        print(f"error: {exc.message}", file=err)
        return EXIT_REFUSED
    except (SQLAlchemyError, sqlite3.Error, OSError, ImportError) as exc:
        # A damaged file, an unreachable server, a missing driver: refused, not a traceback,
        # whose exit status 1 would read as "upgrade pending".
        print(f"error: cannot use the database: {_reason(exc)}", file=err)
        return EXIT_REFUSED


def _reason(exc: SQLAlchemyError | sqlite3.Error | OSError | ImportError) -> str:
    """What went wrong, without the URL (an unparsable one could hold a password)."""
    if isinstance(exc, NoSuchModuleError | ImportError):
        return f"no driver is installed for it ({exc})"
    if isinstance(exc, ArgumentError):
        return "the database URL is not valid"
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        return f"{type(exc.orig).__name__}: {exc.orig}"
    return f"{type(exc).__name__}: {exc}"


def _current(url: str, *, check: bool, out: TextIO) -> int:
    status = schema_status(url)
    print(f"Database: {status.url}", file=out)
    if not status.exists or (status.stored is None and not status.has_tables):
        print(
            f"No workbench schema yet: it is created at version {SCHEMA_VERSION} on first use.",
            file=out,
        )
        return EXIT_OK
    if status.stored is None:
        print("It holds workbench tables but records no schema version: refused.", file=out)
        return EXIT_REFUSED
    print(f"Schema version: {status.stored} (this build: {SCHEMA_VERSION})", file=out)
    if status.up_to_date:
        print("Up to date.", file=out)
        return EXIT_OK
    if not status.pending:
        print("Written by a newer build, or unreadable: this build refuses it.", file=out)
        return EXIT_REFUSED
    print(f"{len(status.pending)} migration(s) pending:", file=out)
    for step in status.pending:
        print(f"  {step.from_version} -> {step.to_version}: {step.summary}", file=out)
    return EXIT_UPGRADE_PENDING if check else EXIT_OK


def _upgrade(url: str, *, settings: Settings, backup: bool, out: TextIO) -> int:
    before = schema_status(url)
    persistence = settings.persistence
    database = Database(
        url,
        dataset_cache_entries=0,
        busy_timeout_ms=persistence.busy_timeout_ms,
        lock_timeout_seconds=persistence.lock_timeout_seconds,
        auto_upgrade="always",
        backup_before_upgrade=backup,
    )
    try:
        print(f"Database: {database.url.render_as_string(hide_password=True)}", file=out)
        applied = database.migrations_applied
    finally:
        database.dispose()
    for step in applied:
        print(f"Applied {step.from_version} -> {step.to_version}: {step.summary}", file=out)
    if applied:
        print(f"Now at schema version {SCHEMA_VERSION}.", file=out)
    elif before.stored is None:
        print(f"Created the workbench schema, version {SCHEMA_VERSION}.", file=out)
    else:
        print(f"Already at schema version {SCHEMA_VERSION}: nothing to upgrade.", file=out)
    return EXIT_OK


if __name__ == "__main__":
    configure_logging(get_settings().logging)
    raise SystemExit(main())
