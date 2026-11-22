"""Statement helpers shared by the SQL repositories.

They render the adapter-agnostic specs of :mod:`app.repositories.querying` as SQL, translate
database integrity errors into :class:`IntegrityViolationError`, refuse updates that match no
row and allocate insertion sequence numbers. Payloads are encoded and loaded with the helpers
shared with the in-memory adapter (:mod:`app.repositories.records`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Connection,
    String,
    Table,
    and_,
    case,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.visitors import InternalTraversal

from app.core.errors import NotFoundError
from app.models.finding_category import CATEGORY_BY_DETECTOR, CATEGORY_BY_RULE
from app.repositories.errors import IntegrityViolationError, PersistenceError
from app.repositories.querying import (
    FINDING_CATEGORY,
    STYLE_DETECTORS,
    STYLE_FINDING,
    STYLE_RULES,
    IssueCondition,
    SortTerm,
    finding_category_key,
)
from app.repositories.sql.schema import sequence_counters
from app.repositories.transactions import UnitOfWorkScope


class SqlRepository:
    """Base of the SQL repositories: they run on the connection of their unit of work."""

    def __init__(self, scope: UnitOfWorkScope[Connection]) -> None:
        self._scope = scope

    @property
    def _connection(self) -> Connection:
        return self._scope.resource()


class CodePointOrder(ColumnElement[Any]):
    """A text column ordered by code point on every backend.

    SQLite (``BINARY``) and the in-memory adapter (Python) compare text by code point, while
    PostgreSQL uses the database's collation, often a natural-language one (``en_US``: ``_``
    sorts before ``.``, ``a`` before ``B``). ``COLLATE "C"`` makes PostgreSQL agree, so both
    adapters keep ordering identically.
    """

    inherit_cache = True
    _traverse_internals = [("column", InternalTraversal.dp_clauseelement)]

    def __init__(self, column: ColumnElement[Any]) -> None:
        self.column = column
        self.type = column.type


@compiles(CodePointOrder)
def _code_point_order(element: CodePointOrder, compiler: SQLCompiler, **kw: Any) -> str:
    return compiler.process(element.column, **kw)


@compiles(CodePointOrder, "postgresql")
def _code_point_order_postgresql(element: CodePointOrder, compiler: SQLCompiler, **kw: Any) -> str:
    return f'{compiler.process(element.column, **kw)} COLLATE "C"'


def order_by(table: Table, order: Sequence[SortTerm]) -> list[ColumnElement[Any]]:
    """ORDER BY clauses for ``order`` with explicit NULL placement; text columns are ordered
    by code point (:class:`CodePointOrder`)."""
    clauses: list[ColumnElement[Any]] = []
    for term in order:
        column = issue_column(table, term.column)
        if isinstance(column.type, String):
            column = CodePointOrder(column)
        clause = column.desc() if term.descending else column.asc()
        if term.nulls == "first":
            clause = clause.nulls_first()
        elif term.nulls == "last":
            clause = clause.nulls_last()
        clauses.append(clause)
    return clauses


def violates_constraint(error: DBAPIError) -> bool:
    """Whether ``error`` reports a violated constraint (SQLSTATE class 23: unique, foreign key,
    not null, check). pg8000 raises its ``ProgrammingError`` for every violation except unique
    ones, so the SQLSTATE it reports is checked as well."""
    if isinstance(error, IntegrityError):
        return True
    report = error.orig.args[0] if error.orig is not None and error.orig.args else None
    return isinstance(report, dict) and str(report.get("C", "")).startswith("23")


def where(table: Table, conditions: Iterable[IssueCondition]) -> list[ColumnElement[bool]]:
    """One ``column IN (...)`` clause per condition (AND across, OR within)."""
    return [issue_column(table, column).in_(sorted(accepted)) for column, accepted in conditions]


def issue_column(table: Table, column: str) -> ColumnElement[Any]:
    """``table.c[column]``, or for the derived ``finding_category`` and ``style_finding`` the
    expression that computes it from the stored columns."""
    if column == FINDING_CATEGORY:
        return finding_category_expression(table)
    if column == STYLE_FINDING:
        return style_finding_expression(table)
    return table.c[column]


def style_finding_expression(table: Table) -> ColumnElement[int]:
    """:func:`app.repositories.querying.is_style_finding` as SQL: 1 or 0."""
    detector, rule = table.c.detector_id, table.c.rule_id
    style = or_(
        detector.in_(sorted(STYLE_DETECTORS)),
        *(and_(detector == d, rule == r) for d, r in sorted(STYLE_RULES)),
    )
    return case((style, 1), else_=0)


def finding_category_expression(table: Table) -> ColumnElement[str]:
    """:func:`app.models.finding_category.finding_category_of` as SQL, with its result named
    as :func:`~app.repositories.querying.finding_category_key` names it: a CASE over the
    detector and rule columns, built from the same tables in the same order (the rule entries,
    then the detector entries)."""
    none = finding_category_key(None)
    detector, rule = table.c.detector_id, table.c.rule_id
    whens: list[tuple[ColumnElement[bool], str]] = [
        (and_(detector == detector_id, rule == rule_id), finding_category_key(category))
        for (detector_id, rule_id), category in CATEGORY_BY_RULE.items()
    ]
    whens += [
        (detector == detector_id, finding_category_key(category))
        for detector_id, category in CATEGORY_BY_DETECTOR.items()
    ]
    return case(*whens, else_=none)


def count_rows(
    connection: Connection, table: Table, conditions: Sequence[ColumnElement[bool]] = ()
) -> int:
    return connection.execute(
        select(func.count()).select_from(table).where(*conditions)
    ).scalar_one()


def insert_rows(
    connection: Connection, table: Table, rows: Sequence[Mapping[str, Any]], *, what: str
) -> None:
    """INSERT ``rows`` (executemany for several); duplicate keys and missing references raise
    :class:`IntegrityViolationError`."""
    try:
        connection.execute(insert(table), list(rows))
    except DBAPIError as exc:
        if not violates_constraint(exc):
            raise
        raise IntegrityViolationError(f"Cannot store {what}: {exc.orig}") from exc


def update_row(
    connection: Connection,
    table: Table,
    match: ColumnElement[bool],
    values: Mapping[str, Any],
    *,
    what: str,
) -> None:
    """UPDATE exactly one row; a missing row raises :class:`NotFoundError`."""
    try:
        result = connection.execute(update(table).where(match).values(dict(values)))
    except DBAPIError as exc:
        if not violates_constraint(exc):
            raise
        raise IntegrityViolationError(f"Cannot store {what}: {exc.orig}") from exc
    if result.rowcount != 1:
        raise missing_on_update(what)


def missing_on_update(what: str) -> NotFoundError:
    """The error for an ``update()`` of a record that does not exist."""
    return NotFoundError(f"Cannot update {what}: it does not exist.")


def next_sequence_value(connection: Connection, table: Table) -> int:
    """Allocate the next insertion ``seq`` of ``table`` (see :func:`next_sequence_values`)."""
    return next_sequence_values(connection, table, 1)[0]


def next_sequence_values(connection: Connection, table: Table, count: int) -> range:
    """Allocate ``count`` consecutive insertion ``seq`` values of ``table`` inside the caller's
    transaction (one counter update, also for a batch).

    The counter row stays locked until the transaction ends, so values are unique and follow
    the order in which concurrent writers commit.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    counter = sequence_counters.c.name == table.name
    result = connection.execute(
        update(sequence_counters).where(counter).values(value=sequence_counters.c.value + count)
    )
    if result.rowcount != 1:
        raise PersistenceError(
            f"The insertion sequence of {table.name!r} is missing from "
            f"{sequence_counters.name!r}; the database schema is incomplete."
        )
    last = connection.execute(select(sequence_counters.c.value).where(counter)).scalar_one()
    return range(last - count + 1, last + 1)
