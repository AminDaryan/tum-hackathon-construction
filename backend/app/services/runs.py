"""Validation runs: plan (every registered check, ADR 0010), execute, carry earlier review
decisions forward, persist; run summaries and details.

A run is synchronous by default: :func:`start` returns the finished run. Clients cannot choose
checks: every run plans every registered check through the workbench's planner. A review
decision is carried into the new run only for a
finding whose fingerprint *and* evidence digest match a reviewed finding of the same document;
the carry is recorded in the issue's history. A finding's task, its thread and the
clarifications drafted on it move to the finding with the same fingerprint in the new run.

A run records a digest of its inputs (``inputs_digest``). Starting a run when the dataset's
latest finished run has the same digest returns that run instead: nothing is created when
nothing changed. Runs of one dataset are executed one at a time.

:func:`start_in_background` (``Prefer: respond-async``, contract K3) checks the request the same
way, stores the run as ``queued`` and returns it; a worker of the workbench's
:class:`~app.services.jobs.JobRunner` then stores each state change: ``running``, then
``completed``, ``completed_with_errors`` or ``failed``. A background run that raises
unexpectedly, is cancelled by a shutdown, or is left queued or running by a crash
(:func:`recover_interrupted`, at start-up) becomes ``failed`` with a warning that says so.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from functools import partial
from typing import Any

from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.core.ids import IdPrefix
from app.models.audit import AuditAction, EntityType
from app.models.bill_review import BillReview
from app.models.dataset import Dataset
from app.models.issue import ReviewStatus, ValidationIssue
from app.models.material_answers import MaterialAnswers
from app.models.plan import PlannerKind, ValidationPlan
from app.models.profile import DomainProfile
from app.models.run import DetectorExecutionStatus, RunReviewStatus, RunStatus, ValidationRun
from app.repositories.base import IssueQuery, UnitOfWork
from app.services import bill_reviews, documents, material_matches, tenders
from app.services.datasets import load
from app.services.jobs import JobQueueFullError, JobRunnerClosedError
from app.services.workbench import Workbench
from app.validation.pipeline import PipelineOutcome, ValidationPipeline
from app.validation.plan_validation import PlanValidator

logger = logging.getLogger(__name__)

UNFINISHED_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_QUEUE_LOCK = threading.Lock()


def _dataset_lock(dataset_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(dataset_id, threading.Lock())


def inputs_digest(
    wb: Workbench,
    dataset: Dataset,
    profile: DomainProfile,
    plan: ValidationPlan,
    answers: MaterialAnswers | None,
    review: BillReview | None,
) -> str:
    """What a run of ``dataset`` checks: the same digest means the same results."""
    with wb.uow() as uow:
        document = uow.documents.get(dataset.document_id)
    model = document.model if document is not None else None
    tender = tenders.tender_for(wb, dataset)
    inputs = {
        "dataset": [dataset.dataset_id, dataset.revision],
        "profile": [profile.profile_id, profile.version],
        "plan": plan.model_dump(mode="json"),
        "detectors": sorted(f"{spec.detector_id}@{spec.version}" for spec in wb.detectors.specs()),
        "model": model.file.sha256 if model is not None else None,
        "answers": answers.model_dump(mode="json") if answers is not None else None,
        "bill_review": review.model_dump(mode="json") if review is not None else None,
        "tender": (
            [tender.dataset.dataset_id, tender.dataset.revision] if tender is not None else None
        ),
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()


def _unchanged(uow: UnitOfWork, dataset_id: str, digest: str) -> ValidationRun | None:
    """The dataset's latest run when it finished with the inputs ``digest`` describes."""
    latest = uow.runs.latest_for_dataset(dataset_id)
    if (
        latest is not None
        and latest.inputs_digest == digest
        and latest.status not in UNFINISHED_STATUSES
        and latest.status is not RunStatus.FAILED
    ):
        return latest
    return None


def start(
    wb: Workbench, dataset_id: str, *, match_materials: bool = False, bill_review: bool = False
) -> dict[str, Any]:
    """Run the validation now and return the finished run (``ValidationRunDetail``), or the
    dataset's latest run when nothing changed since it. ``match_materials`` first asks the local
    model to match the rows the price reference's keywords cannot
    (:mod:`app.services.material_matches`); ``bill_review`` first sends the bill to Claude for
    review (:mod:`app.services.bill_reviews`; refused with ``conflict`` on a server that is
    not set up for it). Every run uses the stored answers of both."""
    _check_asked(wb, bill_review)
    with _dataset_lock(dataset_id):
        with wb.uow() as uow:
            dataset = load(uow, dataset_id)
        profile = wb.profiles.get(dataset.profile_id)
        chosen, source = wb.planner.plan(dataset, profile), wb.planner.kind
        PlanValidator(wb.detectors, wb.settings.validation).validate(chosen, profile, source=source)
        answers = _answers(wb, dataset, match_materials)
        review = _review(wb, dataset, profile, chosen, source, answers, bill_review)
        digest = inputs_digest(wb, dataset, profile, chosen, answers, review)
        with wb.uow() as uow:
            unchanged = _unchanged(uow, dataset.dataset_id, digest)
            if unchanged is not None:
                return detail(uow, unchanged)
            # Stored as running first, so a background request meanwhile follows this run.
            running = ValidationRun(
                run_id=wb.ids.new(IdPrefix.RUN),
                document_id=dataset.document_id,
                dataset_id=dataset.dataset_id,
                dataset_revision=dataset.revision,
                profile_id=profile.profile_id,
                profile_version=profile.version,
                status=RunStatus.RUNNING,
                plan=chosen,
                started_at=wb.clock.now(),
                inputs_digest=digest,
            )
            uow.runs.add(running)
        try:
            run, outcome = _execute(
                wb,
                dataset,
                profile,
                chosen,
                source,
                run_id=running.run_id,
                started_at=running.started_at,
                answers=answers,
                review=review,
                digest=digest,
            )
            with wb.uow() as uow:
                _store_results(wb, uow, run, outcome, store=uow.runs.update)
        except BaseException as exc:
            _fail(wb, running.run_id, f"The run stopped unexpectedly ({type(exc).__name__}).")
            raise
        _carry_threads(wb, run)
        with wb.uow() as uow:
            return detail(uow, run)


def check_soon(wb: Workbench, dataset_id: str) -> None:
    """Queue a background validation of the dataset (``Settings.jobs.auto_validate``) unless
    nothing changed since its latest run. It is queued before this returns, so a client that
    asks for a run next follows this one. A full or closed job runner skips it (logged)."""
    if not wb.settings.jobs.auto_validate:
        return
    try:
        start_in_background(wb, dataset_id)
    except (JobQueueFullError, JobRunnerClosedError):
        logger.warning("Dataset %s was not validated automatically: no free worker", dataset_id)


def check_unvalidated(wb: Workbench) -> None:
    """At start-up, in the background: validate every document's latest dataset that has no
    run yet (``Settings.jobs.auto_validate``), one at a time."""
    if not wb.settings.jobs.auto_validate:
        return

    def work() -> None:
        offset = 0
        while True:
            with wb.uow() as uow:
                page = uow.documents.list(offset=offset, limit=50)
                pending = []
                for document in page.items:
                    dataset = uow.datasets.latest_for_document(document.document_id)
                    if dataset is None or uow.runs.latest_for_dataset(dataset.dataset_id):
                        continue
                    pending.append(dataset.dataset_id)
            for dataset_id in pending:
                _check_quietly(wb, dataset_id)
            offset += len(page.items)
            if not page.items or offset >= page.total:
                return

    try:
        wb.jobs.submit("check-unvalidated", work, on_cancelled=lambda: None)
    except (JobQueueFullError, JobRunnerClosedError, ValueError):
        logger.warning("Unvalidated bills were not checked at start-up: no free worker")


def _check_quietly(wb: Workbench, dataset_id: str) -> None:
    try:
        start(wb, dataset_id)
    except Exception:
        logger.exception("Automatic validation of dataset %s failed", dataset_id)


def _answers(wb: Workbench, dataset: Dataset, match_materials: bool) -> MaterialAnswers | None:
    return (
        material_matches.ask(wb, dataset)
        if match_materials
        else material_matches.stored(wb, dataset.dataset_id)
    )


def _check_asked(wb: Workbench, bill_review: bool) -> None:
    """Refuse a review the server cannot make before a run is stored for it."""
    if bill_review and not bill_reviews.available(wb):
        raise ConflictError(
            "The Claude bill review is not set up on this server, so the bill was not sent."
        )


def _review(
    wb: Workbench,
    dataset: Dataset,
    profile: DomainProfile,
    plan: ValidationPlan,
    source: PlannerKind,
    answers: MaterialAnswers | None,
    asked: bool,
) -> BillReview | None:
    """The stored Claude review of the dataset; when ``asked``, the bill is sent first. The
    model is told what the app's checks found, so they run once before it is asked."""
    if not asked:
        return bill_reviews.stored(wb, dataset.dataset_id)
    checked = _checks(wb, dataset, profile, plan, source, "bill-review", answers, None)
    return bill_reviews.ask(wb, dataset, checked.issues)


def start_in_background(
    wb: Workbench, dataset_id: str, *, match_materials: bool = False, bill_review: bool = False
) -> dict[str, Any]:
    """Check the request like :func:`start`, store the run as ``queued``, hand it to a worker
    and return it (``ValidationRunDetail`` with status ``queued``). Unless a model is asked, a
    run of the dataset's latest revision that is still unfinished is returned instead, and so
    is the latest run when nothing changed since it."""
    _check_asked(wb, bill_review)
    with wb.uow() as uow:
        dataset = load(uow, dataset_id)
    profile = wb.profiles.get(dataset.profile_id)
    chosen, source = wb.planner.plan(dataset, profile), wb.planner.kind
    # An invalid plan is refused now (422), not reported later as a failed run.
    PlanValidator(wb.detectors, wb.settings.validation).validate(chosen, profile, source=source)
    digest = (
        None
        if match_materials or bill_review  # asking a model may change its answers: always runs
        else inputs_digest(
            wb,
            dataset,
            profile,
            chosen,
            _answers(wb, dataset, False),
            bill_reviews.stored(wb, dataset.dataset_id),
        )
    )
    with _QUEUE_LOCK:
        with wb.uow() as uow:
            latest = uow.runs.latest_for_dataset(dataset.dataset_id)
            # A queued run reads its inputs when it starts; a running one already has, so it
            # is followed only while its inputs are still these (a tender added to the
            # project meanwhile queues a new run).
            if (
                digest is not None  # a request that asks a model waits for its own run
                and latest is not None
                and latest.status in UNFINISHED_STATUSES
                and latest.dataset_revision == dataset.revision
                and (latest.status is RunStatus.QUEUED or latest.inputs_digest in (None, digest))
            ):
                return detail(uow, latest)
            unchanged = _unchanged(uow, dataset.dataset_id, digest) if digest else None
            if unchanged is not None:
                return detail(uow, unchanged)
        return _queue(wb, dataset, profile, chosen, source, match_materials, bill_review)


def _queue(
    wb: Workbench,
    dataset: Dataset,
    profile: DomainProfile,
    chosen: ValidationPlan,
    source: PlannerKind,
    match_materials: bool,
    bill_review: bool,
) -> dict[str, Any]:
    wb.jobs.ensure_capacity()  # a closed or full runner refuses (503) before a run is stored
    queued = ValidationRun(
        run_id=wb.ids.new(IdPrefix.RUN),
        document_id=dataset.document_id,
        dataset_id=dataset.dataset_id,
        dataset_revision=dataset.revision,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        status=RunStatus.QUEUED,
        plan=chosen,
        started_at=wb.clock.now(),  # when it was requested, until a worker starts it
    )
    with wb.uow() as uow:
        uow.runs.add(queued)
        response = detail(uow, queued)
    logger.info(
        "Validation run %s queued for dataset %s revision %s (%s plan)",
        queued.run_id,
        queued.dataset_id,
        queued.dataset_revision,
        chosen.planner.value,
        extra={"run_id": queued.run_id, "dataset_id": queued.dataset_id},
    )
    try:
        wb.jobs.submit(
            queued.run_id,
            partial(_run_in_background, wb, queued, source, match_materials, bill_review),
            on_cancelled=partial(
                _fail,
                wb,
                queued.run_id,
                "The server shut down before this run started; start it again.",
            ),
        )
    except JobRunnerClosedError:  # closed between the capacity check and now
        _fail(wb, queued.run_id, "The server was shutting down; start the run again.")
        raise
    except JobQueueFullError:  # filled between the capacity check and now
        _fail(wb, queued.run_id, "Too many background runs were waiting; start it again later.")
        raise
    return response


def _run_in_background(
    wb: Workbench,
    queued: ValidationRun,
    source: PlannerKind,
    match_materials: bool = False,
    bill_review: bool = False,
) -> None:
    """The worker's part of :func:`start_in_background`: every state change is stored."""
    with _dataset_lock(queued.dataset_id):
        _run_queued(wb, queued, source, match_materials, bill_review)


def _run_queued(
    wb: Workbench,
    queued: ValidationRun,
    source: PlannerKind,
    match_materials: bool,
    bill_review: bool,
) -> None:
    try:
        with wb.uow() as uow:
            dataset = uow.datasets.get(queued.dataset_id, queued.dataset_revision)
            if dataset is None:
                raise NotFoundError(
                    f"Dataset {queued.dataset_id!r} revision {queued.dataset_revision} is gone."
                )
            running = queued.evolve(status=RunStatus.RUNNING, started_at=wb.clock.now())
            uow.runs.update(running)
        profile = wb.profiles.get(dataset.profile_id)
        answers = _answers(wb, dataset, match_materials)
        review = _review(wb, dataset, profile, queued.plan, source, answers, bill_review)
        digest = inputs_digest(wb, dataset, profile, queued.plan, answers, review)
        with wb.uow() as uow:  # what this run checks, so a later change queues another run
            running = running.evolve(inputs_digest=digest)
            uow.runs.update(running)
        run, outcome = _execute(
            wb,
            dataset,
            profile,
            queued.plan,
            source,
            run_id=queued.run_id,
            started_at=running.started_at,
            answers=answers,
            review=review,
            digest=digest,
        )
        with wb.uow() as uow:
            _store_results(wb, uow, run, outcome, store=uow.runs.update)
        _carry_threads(wb, run)
    except Exception as exc:
        logger.exception(
            "Validation run %s failed in the background",
            queued.run_id,
            extra={"run_id": queued.run_id, "dataset_id": queued.dataset_id},
        )
        _fail(
            wb,
            queued.run_id,
            f"The run stopped unexpectedly ({type(exc).__name__}); the server log names the "
            f"cause under validation run {queued.run_id}.",
        )


def _execute(
    wb: Workbench,
    dataset: Dataset,
    profile: DomainProfile,
    plan: ValidationPlan,
    source: PlannerKind,
    *,
    run_id: str,
    started_at: datetime,
    answers: MaterialAnswers | None,
    review: BillReview | None,
    digest: str,
) -> tuple[ValidationRun, PipelineOutcome]:
    """Run the pipeline (logging the start and the end of the run) and build the run."""
    log_extra = {"run_id": run_id, "dataset_id": dataset.dataset_id}
    logger.info(
        "Validation run %s started on dataset %s revision %s (%s plan, %d step(s))",
        run_id,
        dataset.dataset_id,
        dataset.revision,
        plan.planner.value,
        len(plan.steps),
        extra=log_extra,
    )
    began = time.monotonic()
    outcome = _checks(wb, dataset, profile, plan, source, run_id, answers, review)
    duration_ms = (time.monotonic() - began) * 1000
    run = ValidationRun(
        run_id=run_id,
        document_id=dataset.document_id,
        dataset_id=dataset.dataset_id,
        dataset_revision=dataset.revision,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        status=outcome.status,
        plan=plan,
        started_at=started_at,
        finished_at=wb.clock.now(),
        detector_reports=outcome.reports,
        issue_count=len(outcome.issues),
        warnings=outcome.warnings,
        inputs_digest=digest,
    )
    detectors = Counter(report.status.value for report in outcome.reports)
    logger.info(
        "Validation run %s finished on dataset %s revision %s: %s, %d finding(s), detectors %s, "
        "%.0f ms",
        run_id,
        dataset.dataset_id,
        dataset.revision,
        run.status.value,
        run.issue_count,
        ", ".join(f"{count} {status}" for status, count in sorted(detectors.items())) or "none",
        duration_ms,
        extra=log_extra
        | {"status": run.status.value, "issue_count": run.issue_count, "duration_ms": duration_ms},
    )
    return run, outcome


def _checks(
    wb: Workbench,
    dataset: Dataset,
    profile: DomainProfile,
    plan: ValidationPlan,
    source: PlannerKind,
    run_id: str,
    answers: MaterialAnswers | None,
    review: BillReview | None,
) -> PipelineOutcome:
    """Every check of ``plan`` on the dataset, with the stored answers of the models."""
    pipeline = ValidationPipeline(
        wb.detectors, ids=wb.ids, clock=wb.clock, limits=wb.settings.validation
    )
    return pipeline.execute(
        dataset=dataset,
        document_id=dataset.document_id,
        profile=profile,
        plan=plan,
        plan_source=source,
        run_id=run_id,
        model=documents.model_takeoff(wb, dataset.document_id),
        material_answers=answers,
        bill_review=review,
        tender=tenders.tender_for(wb, dataset),
    )


def _store_results(
    wb: Workbench,
    uow: UnitOfWork,
    run: ValidationRun,
    outcome: PipelineOutcome,
    *,
    store: Callable[[ValidationRun], None],
) -> None:
    """Store the finished run (``store``: add, or update a queued run) and its issues with
    earlier decisions carried forward, and record the audit events."""
    issues, carried = _carry_reviews(uow, run.document_id, outcome.issues)
    store(run)
    uow.issues.add_many(issues)
    for issue, prior in carried:
        wb.audit(
            uow,
            AuditAction.ISSUE_REVIEWED,
            EntityType.ISSUE,
            issue.issue_id,
            f"Review decision carried over from {prior.issue_id} (run {prior.validation_run_id})",
            before={"review_status": ReviewStatus.PENDING_REVIEW.value},
            after={"review_status": issue.review_status.value},
            context={
                "carried_from_issue_id": prior.issue_id,
                "carried_from_run_id": prior.validation_run_id,
            },
        )
    wb.audit(
        uow,
        AuditAction.VALIDATION_RUN_COMPLETED,
        EntityType.VALIDATION_RUN,
        run.run_id,
        f"Validation run {run.status.value} with {run.issue_count} findings",
        context={"dataset_id": run.dataset_id, "planner": run.plan.planner.value},
    )


def _fail(wb: Workbench, run_id: str, warning: str) -> None:
    """Mark an unfinished run as failed with ``warning`` (a finished one is left alone)."""
    try:
        with wb.uow() as uow:
            run = uow.runs.get(run_id)
            if run is None or run.status not in UNFINISHED_STATUSES:
                return
            _store_failure(wb, uow, run, warning)
    except Exception:
        logger.exception("Could not record that validation run %s failed", run_id)


def _store_failure(wb: Workbench, uow: UnitOfWork, run: ValidationRun, warning: str) -> None:
    failed = run.evolve(
        status=RunStatus.FAILED, finished_at=wb.clock.now(), warnings=[*run.warnings, warning]
    )
    uow.runs.update(failed)
    wb.audit(
        uow,
        AuditAction.VALIDATION_RUN_COMPLETED,
        EntityType.VALIDATION_RUN,
        run.run_id,
        f"Validation run failed: {warning}",
        context={"dataset_id": run.dataset_id, "planner": run.plan.planner.value},
    )
    logger.warning(
        "Validation run %s on dataset %s failed: %s",
        run.run_id,
        run.dataset_id,
        warning,
        extra={"run_id": run.run_id, "dataset_id": run.dataset_id},
    )


def recover_interrupted(wb: Workbench) -> list[str]:
    """At start-up: mark the runs a crash left queued or running as failed (unless
    ``Settings.jobs.recover_interrupted_runs`` is off); returns their ids."""
    if not wb.settings.jobs.recover_interrupted_runs:
        return []
    with wb.uow() as uow:
        stale = uow.runs.list_with_status(UNFINISHED_STATUSES)
        for run in stale:
            _store_failure(
                wb,
                uow,
                run,
                f"The server stopped while this run was {run.status.value}, so it did not "
                "finish; start it again.",
            )
    return [run.run_id for run in stale]


def _carry_reviews(
    uow: UnitOfWork, document_id: str, issues: list[ValidationIssue]
) -> tuple[list[ValidationIssue], list[tuple[ValidationIssue, ValidationIssue]]]:
    """The run's issues with earlier decisions applied, and each (carried, earlier) pair."""
    reviewed = uow.issues.reviewed_by_fingerprint(document_id, [i.fingerprint for i in issues])
    result: list[ValidationIssue] = []
    carried: list[tuple[ValidationIssue, ValidationIssue]] = []
    for issue in issues:
        prior = reviewed.get(issue.fingerprint)
        if prior is not None and prior.evidence_digest == issue.evidence_digest:
            issue = issue.evolve(
                review_status=prior.review_status,
                reviewer_comment=prior.reviewer_comment,
                reviewed_at=prior.reviewed_at,
            )
            carried.append((issue, prior))
        result.append(issue)
    return result, carried


def _carry_threads(wb: Workbench, run: ValidationRun) -> None:
    """Move the task, the thread (comments and task activity, with their notifications) and the
    clarifications of each earlier finding of the document to the run's finding with the same
    fingerprint, so they follow the finding from run to run. Of several earlier tasks, the one
    changed last moves. Collaboration is stored only with SQL persistence."""
    db = wb.database
    if db is None:
        return
    from sqlalchemy import select, union, update

    from app.repositories.sql.schema import clarifications, finding_comments, finding_tasks
    from app.repositories.sql.schema import issues as issue_table

    with db.connect() as c, db.begin(c):
        linked = union(
            select(finding_comments.c.issue_id),
            select(finding_tasks.c.issue_id),
            select(clarifications.c.issue_id).where(clarifications.c.issue_id.is_not(None)),
        ).subquery()
        earlier = c.execute(
            select(issue_table.c.issue_id, issue_table.c.fingerprint).where(
                issue_table.c.document_id == run.document_id,
                issue_table.c.validation_run_id != run.run_id,
                issue_table.c.issue_id.in_(select(linked.c.issue_id)),
            )
        ).all()
        if not earlier:
            return
        fingerprints = {row.fingerprint for row in earlier}
        current = {
            row.fingerprint: row.issue_id
            for row in c.execute(
                select(issue_table.c.issue_id, issue_table.c.fingerprint).where(
                    issue_table.c.validation_run_id == run.run_id,
                    issue_table.c.fingerprint.in_(fingerprints),
                )
            )
        }
        moves = {
            row.issue_id: current[row.fingerprint] for row in earlier if row.fingerprint in current
        }
        if not moves:
            return
        task_rows = c.execute(
            select(finding_tasks.c.issue_id, finding_tasks.c.updated_at)
            .where(finding_tasks.c.issue_id.in_(list(moves)))
            .order_by(finding_tasks.c.updated_at.desc())
        ).all()
        has_task: set[str] = set()
        for row in task_rows:
            target = moves[row.issue_id]
            if target not in has_task:
                has_task.add(target)
                c.execute(
                    update(finding_tasks)
                    .where(finding_tasks.c.issue_id == row.issue_id)
                    .values(issue_id=target)
                )
        for old, new in moves.items():
            c.execute(
                update(finding_comments)
                .where(finding_comments.c.issue_id == old)
                .values(issue_id=new)
            )
            c.execute(
                update(clarifications).where(clarifications.c.issue_id == old).values(issue_id=new)
            )


def detail(uow: UnitOfWork, run: ValidationRun) -> dict[str, Any]:
    """``ValidationRunDetail``: the canonical run plus its issue counts."""
    counts = uow.issues.counts(IssueQuery(run_id=run.run_id))
    return run.model_dump(mode="json") | {"issue_counts": asdict(counts)}


def get(wb: Workbench, run_id: str) -> dict[str, Any]:
    with wb.uow() as uow:
        run = uow.runs.get(run_id)
        if run is None:
            raise NotFoundError(f"Unknown validation run {run_id!r}.")
        return detail(uow, run)


def finish_review(wb: Workbench, run_id: str) -> dict[str, Any]:
    return _set_review_status(wb, run_id, target=RunReviewStatus.FINISHED)


def reopen_review(wb: Workbench, run_id: str) -> dict[str, Any]:
    return _set_review_status(wb, run_id, target=RunReviewStatus.IN_PROGRESS)


def _set_review_status(wb: Workbench, run_id: str, *, target: RunReviewStatus) -> dict[str, Any]:
    with wb.uow() as uow:
        run = uow.runs.get(run_id)
        if run is None:
            raise NotFoundError(f"Unknown validation run {run_id!r}.")
        if run.status in UNFINISHED_STATUSES:
            raise InvalidInputError(
                "A run review can be finished only after the run completed.",
                details={"run_id": run_id, "run_status": run.status.value},
            )
        counts = uow.issues.counts(IssueQuery(run_id=run_id))
        pending = counts.by_review_status.get(ReviewStatus.PENDING_REVIEW.value, 0)
        if target is RunReviewStatus.FINISHED and pending > 0:
            raise InvalidInputError(
                "Review is not finished: some findings are still pending review.",
                details={"run_id": run_id, "pending_review": pending},
            )
        if run.review_status is target:
            return detail(uow, run)
        updated = run.evolve(
            review_status=target,
            review_finished_at=wb.clock.now() if target is RunReviewStatus.FINISHED else None,
        )
        uow.runs.update(updated)
        action = (
            AuditAction.REVIEW_FINISHED
            if target is RunReviewStatus.FINISHED
            else AuditAction.REVIEW_REOPENED
        )
        summary = (
            "Run review finished" if target is RunReviewStatus.FINISHED else "Run review reopened"
        )
        wb.audit(
            uow,
            action,
            EntityType.VALIDATION_RUN,
            run_id,
            summary,
            before={
                "review_status": run.review_status.value,
                "review_finished_at": run.review_finished_at,
            },
            after={
                "review_status": updated.review_status.value,
                "review_finished_at": updated.review_finished_at,
            },
        )
        return detail(uow, updated)


def list_for_dataset(wb: Workbench, dataset_id: str) -> dict[str, Any]:
    with wb.uow() as uow:
        load(uow, dataset_id)
        runs = uow.runs.list_for_dataset(dataset_id)
    items = []
    for run in runs:
        statuses = Counter(report.status.value for report in run.detector_reports)
        items.append(
            run.model_dump(
                mode="json",
                include={
                    "run_id",
                    "dataset_id",
                    "dataset_revision",
                    "status",
                    "review_status",
                    "review_finished_at",
                    "started_at",
                    "finished_at",
                    "issue_count",
                },
            )
            | {
                "planner": run.plan.planner.value,
                "detectors": {
                    status.value: statuses.get(status.value, 0)
                    for status in DetectorExecutionStatus
                },
            }
        )
    return {"items": items}
