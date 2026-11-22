"""Unit-of-work machinery shared by both adapters.

* :class:`UnitOfWorkBase` is the ``with`` lifecycle of every unit of work: refuse re-entry,
  acquire the adapter's resources, then commit on clean exit or roll back on an exception, and
  always release the resources. Adapters supply only ``_begin`` and ``_finish``.
* :class:`UnitOfWorkScope` holds what a unit of work's repositories operate on (the in-memory
  tables, or the SQL connection) while its ``with`` block is open and refuses access outside
  it, so a repository kept past its block fails loudly instead of writing outside a transaction.
* :class:`ExclusiveLock` serializes units of work on resources that cannot isolate concurrent
  transactions themselves: the in-memory database and a single-connection in-memory SQLite
  database. It fails fast on nesting within one thread instead of deadlocking.
* :class:`NestingGuard` only refuses nesting within one thread, for SQLite file databases:
  their units of work hold the write lock from the start (``BEGIN IMMEDIATE``), so a nested
  one would wait for its own outer unit of work until the busy timeout.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Generic, Self, TypeVar

from app.repositories.errors import UnitOfWorkError

ResourceT = TypeVar("ResourceT")

DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0


class UnitOfWorkScope(Generic[ResourceT]):
    """The resource of one unit of work, available only while its ``with`` block is open."""

    def __init__(self, description: str) -> None:
        self.description = description
        self._resource: ResourceT | None = None

    def open(self, resource: ResourceT) -> None:
        if self._resource is not None:
            raise UnitOfWorkError(f"The {self.description} is already active.")
        self._resource = resource

    def close(self) -> None:
        self._resource = None

    def resource(self) -> ResourceT:
        """The open resource; raises :class:`UnitOfWorkError` outside the ``with`` block."""
        resource = self._resource
        if resource is None:
            raise UnitOfWorkError(
                f"The {self.description} is not active: use its repositories (and consume "
                "their iterators) only inside its 'with' block."
            )
        return resource

    def ensure_open(self) -> None:
        """Raise :class:`UnitOfWorkError` unless the ``with`` block is open."""
        self.resource()


class UnitOfWorkBase(ABC, Generic[ResourceT]):
    """``with uow:`` commits on success and rolls back on exception (which then propagates).

    A unit of work is meant for one ``with`` block (one per request, never shared between
    threads); entering it again while it is active raises :class:`UnitOfWorkError`.

    Let an exception raised by a repository propagate out of the block. Catching it and carrying
    on is not portable: PostgreSQL refuses every further statement of a transaction after a
    failed one, SQLite keeps what the failed statement wrote before it stopped (an executemany
    may have stored part of a batch), and the in-memory adapter checks before it writes.
    """

    def __init__(self, description: str) -> None:
        self._scope: UnitOfWorkScope[ResourceT] = UnitOfWorkScope(description)
        self._resources: ExitStack | None = None

    def __enter__(self) -> Self:
        if self._resources is not None:
            raise UnitOfWorkError(
                f"This {self._scope.description} is already active; use a new unit of work "
                "for each 'with' block."
            )
        resources = ExitStack()
        try:
            resource = self._begin(resources)
        except BaseException:
            resources.close()
            raise
        self._resources = resources
        self._scope.open(resource)
        return self

    def __exit__(self, *exc_info: object) -> None:
        resources = self._resources
        if resources is None:
            raise UnitOfWorkError(f"This {self._scope.description} is not active.")
        resource = self._scope.resource()
        self._resources = None
        self._scope.close()
        failed = bool(exc_info) and exc_info[0] is not None
        with resources:  # released even when committing fails
            self._finish(resource, failed=failed)

    @abstractmethod
    def _begin(self, resources: ExitStack) -> ResourceT:
        """Acquire what the block needs (register releases on ``resources``) and start the
        transaction; return the resource the repositories use."""

    @abstractmethod
    def _finish(self, resource: ResourceT, *, failed: bool) -> None:
        """Commit (``failed`` is False) or roll back the transaction."""


def _nesting_refused(resource: str) -> UnitOfWorkError:
    return UnitOfWorkError(
        f"A unit of work is already open on {resource} in this thread; units of work cannot "
        "be nested here. Finish the outer one first."
    )


class NestingGuard:
    """Refuses a second unit of work in a thread that already has one open on the resource.

    Units of work of different threads are not serialized here; the database does that.
    """

    def __init__(self, resource: str) -> None:
        self._resource = resource
        self._local = threading.local()

    @contextmanager
    def hold(self) -> Iterator[None]:
        if getattr(self._local, "held", False):
            raise _nesting_refused(self._resource)
        self._local.held = True
        try:
            yield
        finally:
            self._local.held = False


class ExclusiveLock:
    """A non-reentrant lock for one unit of work at a time.

    Other threads wait up to ``timeout_seconds`` (then :class:`UnitOfWorkError`, never an
    endless hang); the thread that already holds the lock gets :class:`UnitOfWorkError` at
    once, because a nested unit of work would otherwise share or wait for its own transaction.
    """

    def __init__(
        self, resource: str, *, timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._resource = resource
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._owner: int | None = None

    @contextmanager
    def hold(self) -> Iterator[None]:
        me = threading.get_ident()
        # Only this thread ever stores its own ident, so this unlocked read is reliable.
        if self._owner == me:
            raise _nesting_refused(self._resource)
        if not self._lock.acquire(timeout=self._timeout):
            raise UnitOfWorkError(
                f"Timed out after {self._timeout:g}s waiting for {self._resource}: another "
                "unit of work did not finish."
            )
        self._owner = me
        try:
            yield
        finally:
            self._owner = None
            self._lock.release()
