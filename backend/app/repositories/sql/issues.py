"""SQL implementation of :class:`~app.repositories.base.IssueRepository`.

Filters, ordering and counts come from :mod:`app.repositories.querying` (shared with the
in-memory adapter); the indexed columns are recomputed from the issue on every write. Updates
are compare-and-set on the ``version`` column (:mod:`app.repositories.versions`).
"""

from __future__ import annotations

import itertools
from collections.abc import Collection, Iterable, Iterator, Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from app.models.issue import ValidationIssue
from app.repositories.base import IssueCounts, IssueQuery, Page
from app.repositories.errors import IntegrityViolationError, PersistenceError
from app.repositories.querying import (
    COUNT_COLUMNS,
    ISSUE_ORDER,
    REVIEWED_ORDER,
    build_issue_counts,
    carried_decisions,
    check_paging,
    issue_conditions,
    latest_reviews,
    reviewed_conditions,
)
from app.repositories.records import issue_columns, load_model, to_payload
from app.repositories.sql.schema import issues as issue_table
from app.repositories.sql.statements import (
    SqlRepository,
    count_rows,
    insert_rows,
    missing_on_update,
    next_sequence_values,
    order_by,
    violates_constraint,
    where,
)
from app.repositories.versions import check_successor_version, stale_version

# iter_all() selects the ordered ids of all matches first, then loads payloads in batches of
# this size, so no cursor stays open between yields and the result set is fixed at the start.
# reviewed_by_fingerprint() uses it too, so no statement exceeds SQLite's parameter limit.
ITER_BATCH_SIZE = 500


def _load(issue_id: str, payload: object) -> ValidationIssue:
    return load_model(ValidationIssue, payload, what=f"issue {issue_id!r}")


def _batches(values: Sequence[str]) -> Iterator[Sequence[str]]:
    for start in range(0, len(values), ITER_BATCH_SIZE):
        yield values[start : start + ITER_BATCH_SIZE]


class SqlIssueRepository(SqlRepository):
    def add_many(self, issues: Sequence[ValidationIssue]) -> None:
        """One executemany INSERT with consecutive insertion ``seq`` values. A duplicate id or a
        missing validation run raises
        :class:`~app.repositories.errors.IntegrityViolationError`; letting it propagate rolls
        the whole batch back."""
        if not issues:
            self._scope.ensure_open()
            return
        connection = self._connection
        seqs = next_sequence_values(connection, issue_table, len(issues))
        rows = [
            {**issue_columns(issue), "seq": seq, "payload": to_payload(issue)}
            for seq, issue in zip(seqs, issues, strict=True)
        ]
        insert_rows(connection, issue_table, rows, what=f"{len(rows)} issue(s)")

    def get(self, issue_id: str) -> ValidationIssue | None:
        payload = self._connection.execute(
            select(issue_table.c.payload).where(issue_table.c.issue_id == issue_id)
        ).scalar_one_or_none()
        return None if payload is None else _load(issue_id, payload)

    def update(self, issue: ValidationIssue, *, expected_version: int) -> None:
        """``UPDATE … WHERE issue_id = ? AND version = ?`` with every indexed column recomputed
        from ``issue``; when no row matched, the stored version tells a missing issue
        (NotFoundError) from a stale one (ConflictError)."""
        check_successor_version(issue, expected_version)
        connection = self._connection
        what = f"issue {issue.issue_id!r}"
        statement = (
            update(issue_table)
            .where(
                issue_table.c.issue_id == issue.issue_id,
                issue_table.c.version == expected_version,
            )
            .values({**issue_columns(issue), "payload": to_payload(issue)})
        )
        try:
            result = connection.execute(statement)
        except DBAPIError as exc:
            if not violates_constraint(exc):
                raise
            raise IntegrityViolationError(f"Cannot store {what}: {exc.orig}") from exc
        if result.rowcount == 1:
            return
        current = connection.execute(
            select(issue_table.c.version).where(issue_table.c.issue_id == issue.issue_id)
        ).scalar_one_or_none()
        if current is None:
            raise missing_on_update(what)
        raise stale_version(
            issue.issue_id, expected_version=expected_version, current_version=current
        )

    def reviewed_by_fingerprint(
        self, document_id: str, fingerprints: Collection[str]
    ) -> dict[str, ValidationIssue]:
        """Ranks the candidates of each batch of fingerprints in SQL (ids only), then loads
        the payloads of the winners."""
        wanted = list(dict.fromkeys(fingerprints))
        candidates = itertools.chain.from_iterable(
            self._reviewed_candidates(document_id, batch) for batch in _batches(wanted)
        )
        winners = latest_reviews(wanted, candidates)
        payloads = self._payloads(list(winners.values()))
        return carried_decisions(
            {
                fingerprint: _load(issue_id, payloads[issue_id])
                for fingerprint, issue_id in winners.items()
            }
        )

    def query(
        self, query: IssueQuery, *, offset: int = 0, limit: int = 100
    ) -> Page[ValidationIssue]:
        check_paging(offset, limit)
        conditions = where(issue_table, issue_conditions(query))
        connection = self._connection
        rows = connection.execute(
            select(issue_table.c.issue_id, issue_table.c.payload)
            .where(*conditions)
            .order_by(*order_by(issue_table, ISSUE_ORDER))
            .offset(offset)
            .limit(limit)
        ).all()
        return Page(
            items=[_load(row.issue_id, row.payload) for row in rows],
            total=count_rows(connection, issue_table, conditions),
            offset=offset,
            limit=limit,
        )

    def counts(self, query: IssueQuery) -> IssueCounts:
        """One GROUP BY over all count dimensions, folded by the shared aggregator."""
        columns = [issue_table.c[name] for name in COUNT_COLUMNS]
        groups = self._connection.execute(
            select(*columns, func.count())
            .where(*where(issue_table, issue_conditions(query)))
            .group_by(*columns)
        ).all()
        return build_issue_counts((tuple(row[:-1]), row[-1]) for row in groups)

    def change_mark(self, query: IssueQuery) -> tuple[int, int]:
        count, versions = self._connection.execute(
            select(func.count(), func.coalesce(func.sum(issue_table.c.version), 0)).where(
                *where(issue_table, issue_conditions(query))
            )
        ).one()
        return int(count), int(versions)

    def iter_all(self, query: IssueQuery) -> Iterator[ValidationIssue]:
        """Every match in query order; the matches are fixed when iteration starts. Consume it
        inside the unit of work: the next item after its block ends raises."""
        ids = list(
            self._connection.execute(
                select(issue_table.c.issue_id)
                .where(*where(issue_table, issue_conditions(query)))
                .order_by(*order_by(issue_table, ISSUE_ORDER))
            ).scalars()
        )
        for batch in _batches(ids):
            payloads = self._payloads(batch)
            for issue_id in batch:
                self._scope.ensure_open()
                yield _load(issue_id, payloads[issue_id])

    def _reviewed_candidates(
        self, document_id: str, fingerprints: Sequence[str]
    ) -> Iterable[tuple[str, str]]:
        """``(fingerprint, issue_id)`` of the reviewed issues in :data:`REVIEWED_ORDER`."""
        rows = self._connection.execute(
            select(issue_table.c.fingerprint, issue_table.c.issue_id)
            .where(*where(issue_table, reviewed_conditions(document_id, fingerprints)))
            .order_by(*order_by(issue_table, REVIEWED_ORDER))
        )
        return [(row.fingerprint, row.issue_id) for row in rows]

    def _payloads(self, issue_ids: Sequence[str]) -> dict[str, Any]:
        """Stored payloads by issue id, fetched in batches; every id must exist."""
        payloads: dict[str, Any] = {}
        for batch in _batches(issue_ids):
            rows = self._connection.execute(
                select(issue_table.c.issue_id, issue_table.c.payload).where(
                    issue_table.c.issue_id.in_(batch)
                )
            )
            payloads.update((row.issue_id, row.payload) for row in rows)
        vanished = [issue_id for issue_id in issue_ids if issue_id not in payloads]
        if vanished:  # no deletes exist; this would be a concurrent schema change
            raise PersistenceError(f"Issue {vanished[0]!r} vanished while it was being read.")
        return payloads
