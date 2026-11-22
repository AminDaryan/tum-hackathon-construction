"""SQLite write serialization on a file database (ADR 0005, maintainability critique finding 4).

The driver runs in autocommit mode and every transaction starts with ``BEGIN IMMEDIATE``, so a
unit of work's reads and writes are one transaction holding the write lock and concurrent
units of work run one after the other. Issue updates are compare-and-set on the version, so
two decisions made on the same version cannot both be stored.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise

import pytest
from sqlalchemy import event, select

from app.core.errors import ConflictError
from app.models.audit import EntityType
from app.models.document import ProcessingStatus
from app.models.issue import ReviewStatus, ValidationIssue
from app.repositories.errors import UnitOfWorkError
from app.repositories.sql import Database, SqlUnitOfWorkFactory
from app.repositories.sql import schema as sql_schema
from app.repositories.sql.database import _begin_immediate, _unit_of_work_gate
from tests.unit.repositories.samples import (
    T0,
    make_document,
    make_issue,
    make_run,
    minutes,
    review_event,
    review_state,
)

ISSUE = "iss_000001"
WAIT = 10.0  # seconds; generous bound for thread hand-offs so a broken lock fails, not hangs


def _store_issue(factory: SqlUnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.runs.add(make_run())
        uow.issues.add_many([make_issue(ISSUE)])


def _targets(status: ReviewStatus) -> tuple[ReviewStatus, ReviewStatus]:
    """Two decisions allowed from ``status`` (with_review checks the transition)."""
    if status is ReviewStatus.PENDING_REVIEW:
        return (ReviewStatus.CONFIRMED_ERROR, ReviewStatus.FALSE_POSITIVE)
    return (ReviewStatus.PENDING_REVIEW, ReviewStatus.PENDING_REVIEW)


def _history(factory: SqlUnitOfWorkFactory) -> tuple[ValidationIssue, list]:
    with factory() as uow:
        stored = uow.issues.get(ISSUE)
        events = uow.audit.list_for_entity(EntityType.ISSUE, ISSUE)
    assert stored is not None
    return stored, events


def _assert_consistent_trail(stored: ValidationIssue, events: list, decisions: int) -> None:
    """One event per stored decision, each starting where the previous one ended, the last
    ending at the stored state."""
    assert stored.version == decisions + 1
    assert len(events) == decisions
    assert events[0].before == review_state(make_issue(ISSUE))
    for previous, current in pairwise(events):
        assert current.before == previous.after
    assert events[-1].after == review_state(stored)


# -------------------------------------------------------------------- the review race
ROUNDS = 8


def _race(factory: SqlUnitOfWorkFactory, seen: ValidationIssue, round_no: int) -> list:
    """Two reviewers submit different decisions made on the same version ``seen`` at once.
    Returns, per reviewer, the stored decision or the ConflictError it got."""
    targets = _targets(seen.review_status)
    start = threading.Barrier(2, timeout=WAIT)

    def review(reviewer: int) -> ValidationIssue | ConflictError:
        decided = seen.with_review(
            targets[reviewer], f"round {round_no}, reviewer {reviewer}", at=minutes(round_no + 1)
        )
        start.wait()
        try:
            with factory() as uow:
                current = uow.issues.get(ISSUE)  # read inside the transaction
                assert current is not None
                uow.issues.update(decided, expected_version=seen.version)
                uow.audit.append(review_event(f"aud_{round_no}_{reviewer}", current, decided))
        except ConflictError as conflict:
            return conflict
        return decided

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(review, range(2)))


def test_two_reviews_of_the_same_version_admit_exactly_one(file_database_url: str) -> None:
    with Database(file_database_url) as database:
        factory = SqlUnitOfWorkFactory(database)
        _store_issue(factory)
        for round_no in range(ROUNDS):
            with factory() as uow:
                seen = uow.issues.get(ISSUE)  # what both reviewers' screens show
            assert seen is not None
            outcomes = _race(factory, seen, round_no)
            stored = [o for o in outcomes if isinstance(o, ValidationIssue)]
            conflicts = [o for o in outcomes if isinstance(o, ConflictError)]
            assert (len(stored), len(conflicts)) == (1, 1), outcomes
            assert conflicts[0].details == {
                "issue_id": ISSUE,
                "expected_version": seen.version,
                "current_version": seen.version + 1,
            }
            with factory() as uow:
                assert uow.issues.get(ISSUE) == stored[0]  # the winner's decision, unchanged
        final, events = _history(factory)
    _assert_consistent_trail(final, events, ROUNDS)


# ------------------------------------------------------ reads belong to the transaction
def test_reads_of_a_unit_of_work_are_part_of_its_transaction(file_database_url: str) -> None:
    stored = make_document(status=ProcessingStatus.STORED)
    processed = stored.evolve(processing_status=ProcessingStatus.PROCESSED)
    with Database(file_database_url) as database:
        factory = SqlUnitOfWorkFactory(database)
        with factory() as uow:
            uow.documents.add(stored)
        reader_has_read = threading.Event()
        writer_done = threading.Event()

        def write() -> None:
            assert reader_has_read.wait(WAIT)
            with factory() as uow:
                uow.documents.update(processed)
            writer_done.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            writing = pool.submit(write)
            with factory() as uow:
                first = uow.documents.get(stored.document_id)
                reader_has_read.set()
                # A writer must not get in between the reads of one unit of work.
                writer_finished_meanwhile = writer_done.wait(0.3)
                second = uow.documents.get(stored.document_id)
            writing.result(timeout=WAIT)
        with factory() as uow:
            final = uow.documents.get(stored.document_id)
    assert not writer_finished_meanwhile
    assert first == second == stored
    assert final == processed


def test_the_driver_is_in_a_transaction_after_a_read(file_database_url: str) -> None:
    # The finding: with the driver's legacy transaction control a SELECT inside begin() ran
    # outside any transaction.
    with Database(file_database_url) as database:
        assert event.contains(database.engine, "begin", _begin_immediate)
        with database.connect() as connection, database.begin(connection):
            connection.execute(select(sql_schema.documents.c.document_id)).all()
            driver = connection.connection.dbapi_connection
            assert driver is not None
            assert driver.isolation_level is None  # the driver emits no BEGIN of its own
            assert driver.in_transaction


def test_read_check_write_units_of_work_never_interleave(file_database_url: str) -> None:
    # Every reviewer reads the current version inside its unit of work; serialized writers
    # never see a version that changes before their update, so nothing conflicts.
    reviewers, decisions = 4, 5
    with Database(file_database_url) as database:
        factory = SqlUnitOfWorkFactory(database)
        _store_issue(factory)
        start = threading.Barrier(reviewers, timeout=WAIT)

        def reviewer(n: int) -> None:
            start.wait()
            for k in range(decisions):
                with factory() as uow:
                    current = uow.issues.get(ISSUE)
                    assert current is not None
                    target = _targets(current.review_status)[n % 2]
                    decided = current.with_review(target, f"reviewer {n}, decision {k}", at=T0)
                    uow.issues.update(decided, expected_version=current.version)
                    uow.audit.append(review_event(f"aud_{n}_{k}", current, decided))

        with ThreadPoolExecutor(max_workers=reviewers) as pool:
            list(pool.map(reviewer, range(reviewers)))  # re-raises any ConflictError
        final, events = _history(factory)
    _assert_consistent_trail(final, events, reviewers * decisions)


# -------------------------------------------------------------- busy timeout, nesting
def test_a_write_lock_held_beyond_the_busy_timeout_is_reported(file_database_url: str) -> None:
    with (
        Database(file_database_url, busy_timeout_ms=100) as first,
        Database(file_database_url, busy_timeout_ms=100) as second,
    ):
        with SqlUnitOfWorkFactory(first)() as holder:
            holder.documents.add(make_document())
            started = time.perf_counter()
            with pytest.raises(UnitOfWorkError, match="busy for more than 100 ms") as busy:
                SqlUnitOfWorkFactory(second)().__enter__()
            waited = time.perf_counter() - started
        with SqlUnitOfWorkFactory(second)() as uow:  # the lock is free again
            assert uow.documents.get("doc_000001") == make_document()
    assert busy.value.details == {"busy_timeout_ms": 100}
    assert waited >= 0.05  # it waited for the lock instead of failing at once


def test_units_of_work_cannot_be_nested_on_a_file_database(file_database_url: str) -> None:
    with Database(file_database_url) as database:
        factory = SqlUnitOfWorkFactory(database)
        started = time.perf_counter()
        with factory(), pytest.raises(UnitOfWorkError, match="nested"), factory():
            pass
        elapsed = time.perf_counter() - started
        with factory() as uow:  # the guard is released with the outer unit of work
            assert uow.documents.list().total == 0
    assert elapsed < 1.0  # refused at once, not after the busy timeout


def test_only_sqlite_gets_the_sqlite_unit_of_work_gates() -> None:
    assert _unit_of_work_gate(is_sqlite=False, in_memory=False, lock_timeout_seconds=1) is None
    with Database.in_memory_sqlite() as database:
        assert event.contains(database.engine, "begin", _begin_immediate)
