"""Versioned schema migrations of the SQL database (SQLite and PostgreSQL).

:data:`MIGRATIONS` is the ordered list of steps: the step ``from_version = n`` upgrades a
database of schema version ``n`` to ``n + 1``, so a database of any earlier version reaches
:data:`~app.repositories.sql.schema.SCHEMA_VERSION` by applying the steps from its own version
on, in order. :func:`upgrade` runs them inside the caller's transaction and records each new
version in ``schema_info``; SQLite and PostgreSQL both have transactional DDL, so an upgrade
that fails part-way leaves the database exactly as it was. A database recording a version newer
than this build is never touched (:mod:`app.repositories.sql.database` refuses it).

Each step is frozen in time: it names the tables, columns and indexes of its own two versions
(never the objects of :mod:`~app.repositories.sql.schema`, which later versions change) and
reads stored payloads as plain JSON instead of through the models. A NOT NULL column added to a
table with rows gets a temporary default for those rows, which PostgreSQL then drops; SQLite
cannot drop a column default without rebuilding the table, so its upgraded tables keep it (the
repositories always write these columns, so the default is never used).

Adding a schema version: bump ``SCHEMA_VERSION`` and extend the version history in
``schema.py``, append one step here, and add the old layout to the migration tests
(``tests/unit/repositories/legacy_schemas.py``).
"""

from __future__ import annotations

import json
import logging
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    TableClause,
    bindparam,
    column,
    inspect,
    literal_column,
    select,
    table,
    update,
)
from sqlalchemy.types import TypeEngine

from app.repositories.errors import PersistenceError
from app.repositories.records import as_utc
from app.repositories.sql.schema import SCHEMA_VERSION, SCHEMA_VERSION_KEY, schema_info

logger = logging.getLogger(__name__)

# Rows read or written per statement while a step rewrites data (well below SQLite's limit on
# bound parameters, and a bounded number of payloads in memory at a time).
BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class Migration:
    """One step: upgrades a database of schema version ``from_version`` to the next one."""

    from_version: int
    summary: str
    apply: Callable[[Connection], None]

    @property
    def to_version(self) -> int:
        return self.from_version + 1


def pending(from_version: int) -> tuple[Migration, ...]:
    """The steps that take a database of ``from_version`` to :data:`SCHEMA_VERSION`, in order
    (empty for the current version). Raises :class:`PersistenceError` for a version this build
    has no path from (newer, or older than the first step)."""
    steps = tuple(step for step in MIGRATIONS if step.from_version >= from_version)
    versions = [step.from_version for step in steps]
    if from_version > SCHEMA_VERSION or versions != list(range(from_version, SCHEMA_VERSION)):
        raise PersistenceError(
            f"This build cannot upgrade a database of schema version {from_version} to version "
            f"{SCHEMA_VERSION}.",
            details={"found": from_version, "expected": SCHEMA_VERSION},
        )
    return steps


def upgrade(connection: Connection, from_version: int) -> tuple[Migration, ...]:
    """Apply every pending step inside the caller's transaction; returns the steps applied."""
    steps = pending(from_version)
    for step in steps:
        logger.info(
            "Upgrading the workbench database from schema version %s to %s: %s",
            step.from_version,
            step.to_version,
            step.summary,
        )
        step.apply(connection)
        connection.execute(
            update(schema_info)
            .where(schema_info.c.key == SCHEMA_VERSION_KEY)
            .values(value=str(step.to_version))
        )
    return steps


# ------------------------------------------------------------------------------- helpers
def _quote(connection: Connection, name: str) -> str:
    return connection.dialect.identifier_preparer.quote(name)


def _literal(value: int | str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"unsupported column default {value!r}")


def _add_column(
    connection: Connection,
    table_name: str,
    column_name: str,
    type_: TypeEngine[Any],
    *,
    fill: int | str | None,
) -> None:
    """``ALTER TABLE … ADD COLUMN``: NOT NULL with ``fill`` as the existing rows' value, or
    nullable when ``fill`` is None."""
    ddl = (
        f"ALTER TABLE {_quote(connection, table_name)} ADD COLUMN "
        f"{_quote(connection, column_name)} {type_.compile(dialect=connection.dialect)}"
    )
    if fill is not None:
        ddl += f" NOT NULL DEFAULT {_literal(fill)}"
    connection.exec_driver_sql(ddl)


def _drop_fill_defaults(connection: Connection, table_name: str, columns: Sequence[str]) -> None:
    """Drop the temporary defaults of :func:`_add_column` where the database can (not SQLite;
    see the module docstring), so an upgraded table matches a newly created one."""
    if connection.dialect.name == "sqlite":
        return
    for name in columns:
        connection.exec_driver_sql(
            f"ALTER TABLE {_quote(connection, table_name)} "
            f"ALTER COLUMN {_quote(connection, name)} DROP DEFAULT"
        )


def _create_index(
    connection: Connection, name: str, table_name: str, columns: Sequence[str]
) -> None:
    listed = ", ".join(_quote(connection, column_name) for column_name in columns)
    connection.exec_driver_sql(
        f"CREATE INDEX {_quote(connection, name)} ON {_quote(connection, table_name)} ({listed})"
    )


def _drop_index(connection: Connection, name: str) -> None:
    connection.exec_driver_sql(f"DROP INDEX IF EXISTS {_quote(connection, name)}")


def _update_rows(
    connection: Connection,
    target: TableClause,
    keys: Sequence[str],
    values: Mapping[str, TypeEngine[Any]],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """``UPDATE target SET <values> WHERE <keys>`` for each of ``rows`` (dicts keyed by column
    name), in batches of executemany."""
    statement = (
        update(target)
        .where(*(target.c[key] == bindparam(f"key_{key}") for key in keys))
        .values({name: bindparam(f"new_{name}", type_=type_) for name, type_ in values.items()})
    )
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        connection.execute(
            statement,
            [
                {f"key_{key}": row[key] for key in keys}
                | {f"new_{name}": row[name] for name in values}
                for row in batch
            ],
        )


def _payloads(
    connection: Connection, target: TableClause, ids: Sequence[str]
) -> Iterator[tuple[str, Any]]:
    """``(issue_id, payload)`` of the given issues, loaded in batches."""
    for start in range(0, len(ids), BATCH_SIZE):
        batch = ids[start : start + BATCH_SIZE]
        rows = connection.execute(
            select(target.c.issue_id, target.c.payload).where(target.c.issue_id.in_(batch))
        )
        yield from ((row.issue_id, row.payload) for row in rows)


def _utc(value: object, *, what: str) -> datetime | None:
    """A stored ISO timestamp as an aware UTC datetime (``None`` stays ``None``)."""
    if value is None:
        return None
    try:
        return as_utc(datetime.fromisoformat(str(value)))
    except ValueError:
        raise PersistenceError(f"Cannot upgrade {what}: {value!r} is not a timestamp.") from None


def _payload_object(payload: object, *, what: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PersistenceError(f"Cannot upgrade {what}: its payload is not a JSON object.")
    return payload


# --------------------------------------------------------------------------------- steps
def _issues_gain_review_columns(connection: Connection) -> None:
    """1 -> 2: issues gain ``document_id``, ``version``, ``reviewed_at`` and ``seq``; review
    decisions are carried within a document, so the fingerprint index leads with it."""
    for name, type_, fill in (
        ("seq", Integer(), 0),
        ("document_id", String(), ""),
        ("version", Integer(), 1),
    ):
        _add_column(connection, "issues", name, type_, fill=fill)
    _add_column(connection, "issues", "reviewed_at", DateTime(timezone=True), fill=None)
    issues = table(
        "issues",
        column("issue_id", String),
        column("validation_run_id", String),
        column("payload", JSON),
    )
    runs = table("validation_runs", column("run_id", String), column("seq", Integer))
    # Version 1 recorded no insertion order. SQLite's rowid is that order (rows are never
    # deleted); elsewhere issues follow their run's insertion order, then their creation time.
    if connection.dialect.name == "sqlite":
        stored_order = {
            row.issue_id: (row.rowid,)
            for row in connection.execute(
                select(issues.c.issue_id, literal_column("rowid").label("rowid"))
            )
        }
    else:
        run_seq: dict[str, int] = dict(connection.execute(select(runs.c.run_id, runs.c.seq)).all())
        stored_order = {
            row.issue_id: (run_seq.get(row.validation_run_id, 0),)
            for row in connection.execute(select(issues.c.issue_id, issues.c.validation_run_id))
        }
    updated: list[dict[str, Any]] = []
    impacts_dropped = 0
    for issue_id, raw in _payloads(connection, issues, sorted(stored_order)):
        what = f"issue {issue_id!r}"
        payload = _payload_object(raw, what=what)
        impact = payload.get("estimated_financial_impact")
        if isinstance(impact, dict) and impact.get("currency") is None:
            # Version 2: an impact exists only in an explicit currency (amounts in unknown
            # currencies cannot be summed), so a currency-less impact is dropped.
            payload = {**payload, "estimated_financial_impact": None}
            impacts_dropped += 1
        created_at = _utc(payload.get("created_at"), what=what) or datetime.min.replace(tzinfo=UTC)
        updated.append(
            {
                "issue_id": issue_id,
                "order": (*stored_order[issue_id], created_at, issue_id),
                "document_id": str(payload["document_id"]),
                "version": int(payload.get("version", 1)),
                "reviewed_at": _utc(payload.get("reviewed_at"), what=what),
                "payload": payload,
            }
        )
    updated.sort(key=lambda row: row["order"])
    for seq, row in enumerate(updated, start=1):
        row["seq"] = seq
    target = table(
        "issues",
        column("issue_id", String),
        column("seq", Integer),
        column("document_id", String),
        column("version", Integer),
        column("reviewed_at", DateTime(timezone=True)),
        column("payload", JSON),
    )
    _update_rows(
        connection,
        target,
        ["issue_id"],
        {
            "seq": Integer(),
            "document_id": String(),
            "version": Integer(),
            "reviewed_at": DateTime(timezone=True),
            "payload": JSON(),
        },
        updated,
    )
    if impacts_dropped:
        logger.warning(
            "%s finding(s) lost a financial impact without an explicit currency (schema "
            "version 2 records an impact only in an explicit currency).",
            impacts_dropped,
        )
    _drop_fill_defaults(connection, "issues", ("seq", "document_id", "version"))
    _drop_index(connection, "ix_issues_fingerprint")
    _create_index(
        connection, "ix_issues_document_fingerprint", "issues", ("document_id", "fingerprint")
    )


def _snapshot_size(codec: str, data: bytes, *, what: str) -> tuple[int, int]:
    """``(table_count, row_count)`` read from a stored snapshot without the models."""
    if codec != "json+zlib/1":
        raise PersistenceError(f"Cannot upgrade {what}: unknown snapshot codec {codec!r}.")
    try:
        document = json.loads(zlib.decompress(data))
    except (zlib.error, ValueError) as exc:
        raise PersistenceError(f"Cannot upgrade {what}: its snapshot is damaged ({exc}).") from exc
    tables = document.get("tables") if isinstance(document, dict) else None
    if not isinstance(tables, list) or not all(
        isinstance(item, dict) and isinstance(item.get("rows", []), list) for item in tables
    ):
        raise PersistenceError(f"Cannot upgrade {what}: its snapshot holds no table list.")
    return len(tables), sum(len(item.get("rows", [])) for item in tables)


def _datasets_gain_counts(connection: Connection) -> None:
    """2 -> 3: datasets gain ``table_count`` and ``row_count`` (document listings read them
    instead of decoding snapshots)."""
    _add_column(connection, "datasets", "table_count", Integer(), fill=0)
    _add_column(connection, "datasets", "row_count", Integer(), fill=0)
    datasets = table(
        "datasets",
        column("dataset_id", String),
        column("revision", Integer),
        column("snapshot", LargeBinary),
        column("snapshot_codec", String),
        column("table_count", Integer),
        column("row_count", Integer),
    )
    keys = connection.execute(select(datasets.c.dataset_id, datasets.c.revision)).all()
    updated: list[dict[str, Any]] = []
    for dataset_id, revision in keys:  # one snapshot in memory at a time
        row = connection.execute(
            select(datasets.c.snapshot, datasets.c.snapshot_codec).where(
                datasets.c.dataset_id == dataset_id, datasets.c.revision == revision
            )
        ).one()
        what = f"dataset {dataset_id!r} revision {revision}"
        table_count, row_count = _snapshot_size(row.snapshot_codec, row.snapshot, what=what)
        updated.append(
            {
                "dataset_id": dataset_id,
                "revision": revision,
                "table_count": table_count,
                "row_count": row_count,
            }
        )
    _update_rows(
        connection,
        datasets,
        ["dataset_id", "revision"],
        {"table_count": Integer(), "row_count": Integer()},
        updated,
    )
    _drop_fill_defaults(connection, "datasets", ("table_count", "row_count"))


_RUN_ORDER_INDEX_V4 = (
    "validation_run_id",
    "severity_rank",
    "sort_sheet",
    "sort_row",
    "sort_column",
    "detector_id",
    "rule_id",
    "fingerprint",
    "seq",
    "issue_id",
)


def _issues_gain_rule_id(connection: Connection) -> None:
    """3 -> 4: issues gain ``rule_id``; the run-order index follows the deterministic issue
    order (detector, rule, fingerprint and insertion sequence after the source position)."""
    _add_column(connection, "issues", "rule_id", String(), fill="default")
    issues = table(
        "issues", column("issue_id", String), column("payload", JSON), column("rule_id", String)
    )
    ids: list[str] = list(connection.execute(select(issues.c.issue_id)).scalars())
    updated: list[dict[str, Any]] = []
    for issue_id, raw in _payloads(connection, issues, ids):
        rule_id = _payload_object(raw, what=f"issue {issue_id!r}").get("rule_id") or "default"
        if rule_id != "default":  # the column's fill value already
            updated.append({"issue_id": issue_id, "rule_id": str(rule_id)})
    _update_rows(connection, issues, ["issue_id"], {"rule_id": String()}, updated)
    _drop_fill_defaults(connection, "issues", ("rule_id",))
    _drop_index(connection, "ix_issues_run_order")
    _create_index(connection, "ix_issues_run_order", "issues", _RUN_ORDER_INDEX_V4)


def _explanations_table(connection: Connection) -> None:
    """4 -> 5: the ``explanations`` table, empty. Its insertion-sequence counter row is added
    after the upgrade, like every missing counter row (``database._seed_sequence_counters``)."""
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
        }
    )
    Table("validation_runs", metadata, Column("run_id", String, primary_key=True))  # referenced
    explanations = Table(
        "explanations",
        metadata,
        Column("explanation_id", String, primary_key=True),
        Column("seq", Integer, nullable=False),
        Column("run_id", String, ForeignKey("validation_runs.run_id"), nullable=False),
        Column("problem_id", String, nullable=False),
        Column("status", String, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        Column("payload", JSON, nullable=False),
        Index("ix_explanations_problem", "run_id", "problem_id", "created_at", "seq"),
    )
    explanations.create(connection)


def _projects_table(connection: Connection) -> None:
    """5 -> 6: persistent projects, without rewriting existing uploads."""
    Table(
        "projects",
        MetaData(),
        Column("project_id", String, primary_key=True),
        Column("payload", JSON, nullable=False),
    ).create(connection)


def _users_table(connection: Connection) -> None:
    """6 -> 7: user accounts, none at first."""
    metadata = MetaData(naming_convention={"pk": "pk_%(table_name)s"})
    Table(
        "users",
        metadata,
        Column("user_id", String, primary_key=True),
        Column("token_digest", String, nullable=True),
        Column("payload", JSON, nullable=False),
        Index("ix_users_token_digest", "token_digest", unique=True),
    ).create(connection)


def _collaboration_tables(connection: Connection) -> None:
    """Reviewer sessions, finding discussions and mention inboxes."""
    snapshot = MetaData()
    Table("issues", snapshot, Column("issue_id", String, primary_key=True))
    Table(
        "reviewers",
        snapshot,
        Column("handle", String, primary_key=True),
        Column("name", String, nullable=False),
    )
    Table(
        "reviewer_sessions",
        snapshot,
        Column("token_hash", String, primary_key=True),
        Column("handle", String, ForeignKey("reviewers.handle"), nullable=False),
        Column("expires_at", String, nullable=False),
    )
    Table(
        "finding_comments",
        snapshot,
        Column("comment_id", String, primary_key=True),
        Column("issue_id", String, ForeignKey("issues.issue_id"), nullable=False),
        Column("author", String, ForeignKey("reviewers.handle"), nullable=False),
        Column("body", String, nullable=False),
        Column("created_at", String, nullable=False),
        Index("ix_finding_comments_issue", "issue_id", "created_at", "comment_id"),
    )
    Table(
        "mention_notifications",
        snapshot,
        Column("notification_id", String, primary_key=True),
        Column("recipient", String, ForeignKey("reviewers.handle"), nullable=False),
        Column("comment_id", String, ForeignKey("finding_comments.comment_id"), nullable=False),
        Column("is_read", Integer, nullable=False),
        Index("ix_mentions_recipient", "recipient", "is_read"),
    )
    snapshot.create_all(
        connection, tables=[t for t in snapshot.sorted_tables if t.name != "issues"]
    )


def _converged_v8_tables(connection: Connection) -> None:
    """7 -> 8: converge both historical v7 variants into one layout."""
    table_names = set(inspect(connection).get_table_names())
    if "users" not in table_names:
        _users_table(connection)
    if "reviewers" not in table_names:
        _collaboration_tables(connection)


def _finding_tasks(connection: Connection) -> None:
    """8 -> 9: finding-thread entries gain ``kind`` (existing ones are comments) and the
    ``finding_tasks`` table (one task per finding)."""
    _add_column(connection, "finding_comments", "kind", String(), fill="comment")
    _drop_fill_defaults(connection, "finding_comments", ["kind"])
    snapshot = MetaData()
    Table("issues", snapshot, Column("issue_id", String, primary_key=True))
    Table("reviewers", snapshot, Column("handle", String, primary_key=True))
    Table(
        "finding_tasks",
        snapshot,
        Column("issue_id", String, ForeignKey("issues.issue_id"), primary_key=True),
        Column("assignee", String, ForeignKey("reviewers.handle")),
        Column("status", String, nullable=False),
        Column("task_type", String),
        Column("updated_by", String, ForeignKey("reviewers.handle"), nullable=False),
        Column("updated_at", String, nullable=False),
    ).create(connection)


def _assistant_replies(connection: Connection) -> None:
    """9 -> 10: the review assistant's reply attachments, none at first."""
    snapshot = MetaData()
    Table("finding_comments", snapshot, Column("comment_id", String, primary_key=True))
    Table(
        "assistant_replies",
        snapshot,
        Column("comment_id", String, ForeignKey("finding_comments.comment_id"), primary_key=True),
        Column("payload", JSON, nullable=False),
    ).create(connection)


def _clarifications_table(connection: Connection) -> None:
    """10 -> 11: the ``clarifications`` table (a project's questions before the bid decision)."""
    snapshot = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        }
    )
    Table("projects", snapshot, Column("project_id", String, primary_key=True))  # referenced
    Table(
        "clarifications",
        snapshot,
        Column("clarification_id", String, primary_key=True),
        Column("project_id", String, ForeignKey("projects.project_id"), nullable=False),
        Column("document_id", String, nullable=False),
        Column("risk_id", String, nullable=False),
        Column("tier", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("title", String, nullable=False),
        Column("status", String, nullable=False),
        Column("due", String),
        Column("phase", String, nullable=False),
        Column("answer", String, nullable=False),
        Column("created_at", String, nullable=False),
        Column("updated_at", String, nullable=False),
        Index("ix_clarifications_project", "project_id", "created_at", "clarification_id"),
    ).create(connection)


def _task_due_dates(connection: Connection) -> None:
    """11 -> 12: existing finding tasks have no deadline until a reviewer sets one."""
    _add_column(connection, "finding_tasks", "due_date", String(), fill=None)


def _clarification_emails(connection: Connection) -> None:
    """12 -> 13: clarifications gain the email they were drafted as and ``sent_at``."""
    for name in ("issue_id", "recipient", "subject", "body", "sent_at"):
        _add_column(connection, "clarifications", name, String(), fill=None)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "issues gain document_id, version, reviewed_at and seq; impacts without a currency "
        "are dropped",
        _issues_gain_review_columns,
    ),
    Migration(2, "datasets gain table_count and row_count", _datasets_gain_counts),
    Migration(
        3, "issues gain rule_id; the run-order index follows the issue order", _issues_gain_rule_id
    ),
    Migration(4, "the explanations table", _explanations_table),
    Migration(5, "the projects table", _projects_table),
    Migration(6, "the users table", _users_table),
    Migration(7, "users and collaboration tables are both present", _converged_v8_tables),
    Migration(8, "finding-thread entries gain kind; the finding_tasks table", _finding_tasks),
    Migration(9, "the assistant_replies table", _assistant_replies),
    Migration(10, "the clarifications table", _clarifications_table),
    Migration(11, "finding tasks gain an optional due date", _task_due_dates),
    Migration(12, "clarifications gain their email and sent_at", _clarification_emails),
)
