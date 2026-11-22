"""Background jobs: a small thread pool for validation runs started with
``Prefer: respond-async`` (RFC 7240), contract K3 of ``docs/api/rest-api.md``.

A job is a callable that records its own progress (the run service stores every state change
of its run), so the pool keeps no state a client could need: clients poll the run. The pool is
created on the first submission and has ``Settings.jobs.workers`` threads (validation is
CPU-bound Python, so a few threads are enough to keep one long run from blocking the others).

:meth:`JobRunner.shutdown` (the application's shutdown) refuses new jobs, cancels the jobs that
have not started (their ``on_cancelled`` callback runs, so the run service can mark them
failed) and waits for the running ones, which are bounded by the run time limit. Runs that a
crash leaves queued or running are failed at the next start (``runs.recover_interrupted``).
"""

from __future__ import annotations

import contextvars
import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor

from app.core.errors import UnavailableError

logger = logging.getLogger(__name__)

RESPOND_ASYNC = "respond-async"


class JobRefusedError(UnavailableError):
    """A background job was not accepted (503)."""


class JobRunnerClosedError(JobRefusedError):
    """A job was submitted while the server is shutting down."""

    code = "shutting_down"


class JobQueueFullError(JobRefusedError):
    """Every worker is busy and as many jobs as allowed are already waiting."""

    code = "run_queue_full"
    retry_after = 30


def prefers_respond_async(prefer_headers: Iterable[str]) -> bool:
    """Whether the ``Prefer`` header values (RFC 7240: comma-separated preferences, each with
    optional ``;``-separated parameters; names are case-insensitive) ask for
    ``respond-async``."""
    return any(
        preference.split(";", 1)[0].strip().lower() == RESPOND_ASYNC
        for header in prefer_headers
        for preference in header.split(",")
    )


class JobRunner:
    """Runs submitted callables on a lazily created thread pool of ``workers`` threads. At
    most ``max_waiting`` jobs wait for a free worker; more are refused, so a client cannot
    queue unbounded work."""

    def __init__(
        self, *, workers: int, max_waiting: int = 16, thread_name_prefix: str = "twb-job"
    ) -> None:
        if workers < 1:
            raise ValueError(f"workers must be >= 1, got {workers}")
        if max_waiting < 0:
            raise ValueError(f"max_waiting must be >= 0, got {max_waiting}")
        self.workers = workers
        self.max_waiting = max_waiting
        self._thread_name_prefix = thread_name_prefix
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False
        self._jobs: dict[str, tuple[Future[None], Callable[[], None]]] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    def active(self) -> list[str]:
        """Ids of the jobs submitted and not finished yet (queued or running)."""
        with self._lock:
            return list(self._jobs)

    def ensure_capacity(self) -> None:
        """Raise what :meth:`submit` would raise now if the runner is closed or full, so a
        caller can refuse a request before it stores anything. :meth:`submit` checks again."""
        with self._lock:
            self._check_accepting()

    def _check_accepting(self) -> None:  # with self._lock held
        if self._closed:
            raise JobRunnerClosedError(
                "The server is shutting down and starts no background work; start the run "
                "again once it is back."
            )
        if len(self._jobs) >= self.workers + self.max_waiting:
            raise JobQueueFullError(
                f"All {self.workers} background worker(s) are busy and {self.max_waiting} "
                "run(s) are already waiting; start the run again later."
            )

    def submit(
        self, job_id: str, work: Callable[[], None], *, on_cancelled: Callable[[], None]
    ) -> None:
        """Queue ``work``; ``on_cancelled`` runs instead when shutdown cancels it unstarted.
        Raises :class:`JobRunnerClosedError` after :meth:`shutdown` and
        :class:`JobQueueFullError` when ``workers + max_waiting`` jobs are unfinished."""
        with self._lock:
            self._check_accepting()
            if job_id in self._jobs:
                raise ValueError(f"job {job_id!r} is already queued")
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.workers, thread_name_prefix=self._thread_name_prefix
                )
            # The job runs in a copy of the submitter's context, so its log lines carry the id
            # of the request that queued it (app.core.logging.request_id_var).
            context = contextvars.copy_context()
            future = self._executor.submit(context.run, _guarded, job_id, work)
            self._jobs[job_id] = (future, on_cancelled)
        future.add_done_callback(lambda _: self._forget(job_id))

    def shutdown(self, *, wait: bool = True) -> None:
        """Refuse new jobs, cancel the unstarted ones (calling their ``on_cancelled``) and, with
        ``wait``, wait for the running ones. Safe to call more than once."""
        with self._lock:
            self._closed = True
            executor, self._executor = self._executor, None
            jobs = dict(self._jobs)
        if executor is None:
            return
        cancelled = [job_id for job_id, (future, _) in jobs.items() if future.cancel()]
        for job_id in cancelled:
            _, on_cancelled = jobs[job_id]
            _guarded(job_id, on_cancelled)
        if cancelled:
            logger.warning(
                "Shutdown cancelled %d background job(s) that had not started", len(cancelled)
            )
        executor.shutdown(wait=wait, cancel_futures=True)

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)


def _guarded(job_id: str, work: Callable[[], None]) -> None:
    """Run ``work``; an exception is logged (jobs record their own failures) and never ends
    the worker thread."""
    try:
        work()
    except Exception:
        logger.exception("Background job %s raised", job_id)
