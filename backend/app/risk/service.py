"""The risk report of one finished validation run, computed on request, and the stored
discovery runs that can be applied to it.

read the bill -> run the text checks -> take over the stored findings -> merge, tier and
order -> (with a stored discovery run, off by default) apply its checked hypotheses: they are
placed, de-duplicated and graded with the rest -> (only when an in-process caller asks for it)
a bounded local-model look at a few open reminders -> report with the coverage of every risk
type -> display order.

Reading a report never starts discovery: :func:`start_discovery` runs it once, explicitly, and
stores what came of it, bound to its inputs (``_BOUND``: the bill, the tables, the prompt and
what the run chose and sent, which reviews change); :func:`risk_report` with that run's id
applies the stored result without calling a model, or shows it as outdated when the inputs
changed. The report itself is not stored: it changes when reviewers decide findings (a rejected
one no longer counts and is listed after the rest, and the track record of its check
changes).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass
from functools import partial
from typing import Any

from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.models.issue import Severity
from app.models.project import Project
from app.models.run import RunStatus, ValidationRun
from app.repositories import IssueQuery
from app.risk.bid_report import BidReport, BidSkipped, BillPart, build
from app.risk.bill import Bill, read_bill
from app.risk.checks import run_checks
from app.risk.checks.base import Outcome
from app.risk.context import derive_context
from app.risk.coverage import coverage
from app.risk.discovery import (
    MAX_LISTED,
    PROMPT_VERSION,
    Placement,
    Strategy,
    attach,
    candidates,
    context_key,
    discover,
)
from app.risk.discovery_runs import ACTIVE, LOCK, DiscoveryRunStore
from app.risk.display import arrange
from app.risk.findings import from_findings, rejected_findings
from app.risk.grading import grade
from app.risk.model_review import Generator, review
from app.risk.models import (
    FORMAT_VERSION,
    Candidate,
    Discovery,
    DiscoveryRun,
    DiscoveryRunList,
    DiscoveryRunSummary,
    ProjectContext,
    Risk,
    RiskReport,
    SortBy,
    SortOrder,
    SourceCoverage,
    State,
)
from app.risk.tables import RiskTables, load_tables
from app.risk.text import clip
from app.risk.triage import funnel, triage
from app.services.jobs import JobRefusedError
from app.services.risk_reviews import list_risk_reviews
from app.services.runs import UNFINISHED_STATUSES
from app.services.workbench import Workbench
from app.validation.contracts.context import build_validation_context

# The inputs a stored result is bound to: when one changed, the result is not applied.
# "selection_and_context" is what a run would choose and send: the reminders decide it, and
# reviews change the reminders (a rejected finding is left out, track records change).
_BOUND = (
    "validation_run",
    "dataset",
    "profile",
    "bill_text",
    "tables",
    "report_format",
    "prompt_and_checks",
    "selection_and_context",
)


@dataclass(frozen=True, slots=True)
class _Base:
    """The rule checks and stored findings of a run, merged and graded (no model involved)."""

    run: ValidationRun
    tables: RiskTables
    bill: Bill
    project: ProjectContext
    candidates: list[Candidate]
    outcomes: list[Outcome]  # of the checks and the stored findings
    check_outcomes: list[Outcome]  # of the checks alone
    findings: int  # stored findings taken over
    graded: list[Risk]
    rejected: list[Candidate]  # findings a reviewer rejected, kept out of ``graded``
    clipped_texts: int  # long texts shortened by the reader, which names no position


def _base(wb: Workbench, run_id: str) -> _Base:
    with wb.uow() as uow:
        run = uow.runs.get(run_id)
        if run is None:
            raise NotFoundError(f"Unknown validation run {run_id!r}.")
        if run.status in UNFINISHED_STATUSES:
            raise ConflictError(f"Validation run {run_id!r} has not finished yet.")
        dataset = uow.datasets.get(run.dataset_id, run.dataset_revision)
        if dataset is None:
            raise NotFoundError(f"The dataset of run {run_id!r} no longer exists.")
        issues = list(uow.issues.iter_all(IssueQuery(run_id=run_id)))
    tables = load_tables(run.profile_id)  # InvalidInputError for a profile without risk tables
    context = build_validation_context(
        dataset=dataset,
        document_id=run.document_id,
        profile=wb.profiles.get(run.profile_id),
        run_id=run_id,
        limits=wb.settings.validation,
        ids=wb.ids,
        clock=wb.clock,
    )
    bill = read_bill(context, tables.components)
    project = derive_context(bill, tables)
    result = run_checks(bill, tables, project)
    findings = from_findings(run, issues, dataset, bill, tables)
    check_outcomes = list(result.outcomes)
    result.extend(findings)
    return _Base(
        run=run,
        tables=tables,
        bill=bill,
        project=project,
        candidates=list(result.candidates),
        outcomes=list(result.outcomes),
        check_outcomes=check_outcomes,
        findings=len(findings.candidates),
        graded=grade(result.candidates, bill, tables),
        rejected=rejected_findings(issues, dataset, bill, tables),
        clipped_texts=sum(
            w.count or 1 for w in dataset.extraction.warnings if w.code == "gaeb_long_text_clipped"
        ),
    )


def risk_report(
    wb: Workbench,
    run_id: str,
    *,
    model_review: bool = False,
    generator: Generator | None = None,
    discovery_run_id: str | None = None,
    sources: SourceCoverage | None = None,
    sort_by: SortBy = "priority",
    sort_order: SortOrder = "desc",
) -> RiskReport:
    """``discovery_run_id`` applies a stored discovery run (see :func:`start_discovery`)
    without calling a model. ``model_review`` asks the configured local model, during this
    call, to look at a few open reminders: for explicit in-process callers only (the HTTP report
    refuses it, so reading a report never calls a model). ``sources`` states which parts of the
    source were read, when the caller knows it. ``sort_by`` and ``sort_order`` only reorder the
    finished lists."""
    base = _base(wb, run_id)
    graded = base.graded
    stored: DiscoveryRun | None = None
    placement: Placement | None = None
    shown = Discovery(
        status="not_enabled", detail="Not asked for: no position was sent to a model."
    )
    if discovery_run_id is not None:
        stored, shown = _stored(wb, base, discovery_run_id)
    if stored is not None:
        placement = candidates(stored.findings, base.bill, graded)
        if placement.candidates:
            graded = grade([*base.candidates, *placement.candidates], base.bill, base.tables)
        graded = attach(graded, stored.findings, placement.merged)
    risks, model = review(
        graded,
        base.bill,
        wb.settings.llm,
        requested=model_review,
        generator=generator,
    )
    tables, bill, run = base.tables, base.bill, base.run
    rows = coverage(base.outcomes, tables)
    main, record, questions = triage(risks, tables)
    tiers = Counter(r.tier.value for r in main)
    states = Counter(r.state.value for r in [*main, *record])
    # Rejected findings are no reminders (not counted, no question), but each list shows its
    # own after them, so a reviewer can still find the decision and undo it.
    rejected_main, rejected_record, _ = triage(grade(base.rejected, bill, tables), tables)
    # The catch-all "other" has a coverage row only when something landed there; counting it
    # made the catalogue 136 risk types on one bill and 135 on another.
    catalogued = [row for row in rows if row.risk_type != tables.catalogue.other.id]
    checked = sum(1 for row in catalogued if row.state is not State.NOT_CHECKABLE)
    notes = [
        "Only this bill was searched: drawings, the soil report and documents of other trades "
        "were not available, so missing work is asked about, not reported as an omission.",
        "No cost classification came with the bill (for example DIN 276 cost groups): none is "
        "assigned or inferred. Sections and trades are read from section titles as context "
        "clues; they are not cost groups and say nothing about contract responsibility.",
    ]
    if sources is None:
        notes.append(
            "It is not known which pages, attachments and preliminary text of the source were "
            "read, so 'not found' means not found in the positions and notes that were read."
        )
    else:
        notes.append(_coverage_note(sources))
    if base.clipped_texts:
        n = base.clipped_texts
        notes.append(
            f"The reader cut {n} long text{'s' if n != 1 else ''} at its length limit and names "
            f"no position: the checks read only the beginning of {'them' if n != 1 else 'it'}, "
            "so 'not found' there may be wrong. The stored original file keeps the whole text."
        )
    if stored is not None and placement is not None:
        shown = _discovery(stored, placement)
        d = shown
        notes.append(
            f"Discovery run {stored.discovery_run_id} by the local model ({d.status}): "
            f"{d.processed} of {d.positions_total} positions looked at"
            + (f" ({d.partly_read} only in part)" if d.partly_read else "")
            + f", {d.not_selected + d.not_processed} not looked at (not passed). Its {d.kept} "
            "hypotheses of their own are experimental supplements to verify (open_questions "
            "with experimental true, and the record after the reminders of the checks): never "
            "in the main list, never confirmed risks, and without money; they change no order, "
            f"tier, evidence or money of the base tasks. {d.merged} joined a reminder the model "
            "named as the same cause, listed there as a model hint, not as a confirmation."
        )
    elif discovery_run_id is not None:
        notes.append(f"Discovery run {discovery_run_id}: {shown.detail}")
    if not tables.grading.thresholds_validated:
        notes.append(
            "The size limits that raise a reminder's priority (1 % and 5 % of the bill's total) "
            "are first guesses, not measured."
        )
    if not bill.priced:
        notes.append("The bill has no prices: money is unknown for every reminder.")
    if run.status is not RunStatus.COMPLETED:
        notes.append(
            f"The run ended as {run.status.value}: findings of detectors that did not finish "
            "are missing."
        )
    from_model = [q for q in questions if q.source != "checks"]
    report = RiskReport(
        run_id=run_id,
        profile_id=run.profile_id,
        tables_version=tables.versions,
        context=base.project,
        counts={
            "reminders": len(main),
            "in_record": len(record),
            **{tier.value: tiers[tier.value] for tier in Severity},
            **{state: states[state] for state in (State.RISK.value, State.CANNOT_TELL.value)},
            "open_questions": len(questions),
            "open_questions_from_discovery": len(from_model),
            "risk_types": len(catalogued),
            "risk_types_checked": checked,
        },
        risks=_after(main, rejected_main),
        open_questions=questions,
        record=_after(record, rejected_record),
        funnel=funnel(
            base.check_outcomes,
            base.findings,
            len(risks),
            main,
            record,
            questions,
            rows,
        ),
        coverage=rows,
        model_review=model,
        discovery=shown,
        sources=sources,
        notes=notes,
    )
    return arrange(report, sort_by, sort_order)


def _after(listed: list[Risk], rejected: list[Risk]) -> list[Risk]:
    """``rejected`` ranked on after ``listed``."""
    return [
        *listed,
        *(
            risk.model_copy(update={"rank": rank, "priority_rank": rank})
            for rank, risk in enumerate(rejected, start=len(listed) + 1)
        ),
    ]


def bid_report(wb: Workbench, project_id: str, *, limit: int = 20) -> BidReport:
    """The bid risk report of a project's latest validation (:mod:`app.risk.bid_report`): the
    main list of each bill's risk report, without the reminders reviewers rejected. Computed on
    request like the risk report: nothing is stored and no model is called."""
    with wb.uow() as uow:
        project = uow.projects.get(project_id)
        if project is None:
            raise NotFoundError(f"Unknown project {project_id!r}.")
        validation = project.validation
        if validation is None:
            raise ConflictError(
                f"Project {project_id!r} has not been validated: validate it first."
            )
        if validation.status == "running":
            raise ConflictError(f"Project {project_id!r} is being validated: ask again when done.")
        names: dict[str, str] = {}
        for file in project.files:
            document = uow.documents.get(file.document_id)
            names[file.document_id] = document.original_filename if document else file.document_id
    skipped = {d: why for d, why in validation.skipped.items() if d in names}
    notes: list[str] = []
    if validation.status == "failed":
        notes.append(
            f"The project's last validation failed ({validation.error or 'no reason given'}): "
            "only the bills validated before it stopped are here."
        )
    parts: list[BillPart] = []
    for file in project.files:
        run_id = validation.runs.get(file.document_id)
        if run_id is None:
            skipped.setdefault(file.document_id, "Not in the last validation: validate again.")
            continue
        try:
            base = _base(wb, run_id)
        except (ConflictError, InvalidInputError, NotFoundError) as exc:
            skipped[file.document_id] = exc.message
            continue
        main, _, _ = triage(base.graded, base.tables)  # the report's main list, default order
        reviews = list_risk_reviews(wb, run_id).items
        rejected = {r.risk_id for r in reviews if r.status == "rejected"}
        kept = [r for r in main if r.risk_id not in rejected]
        parts.append(
            BillPart(
                document_id=file.document_id,
                document_name=names[file.document_id],
                run_id=run_id,
                run_status=base.run.status.value,
                bill=base.bill,
                tables=base.tables,
                reminders=kept,
                rejected=len(main) - len(kept),
            )
        )
    return build(
        project_id=project_id,
        project_name=project.name,
        generated_at=wb.clock.now(),
        parts=parts,
        limit=limit,
        skipped=[
            BidSkipped(document_id=d, document_name=names[d], reason=why)
            for d, why in skipped.items()
        ],
        notes=notes,
    )


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    """A question a reminder of a bill's risk report asks the client."""

    document_id: str
    risk_id: str
    tier: Severity
    question: str


# (the mark of the run's findings they were built at, the questions)
RunQuestions = tuple[tuple[int, int], tuple[ClarificationQuestion, ...]]


def _run_questions(
    wb: Workbench, document_id: str, run_id: str
) -> tuple[ClarificationQuestion, ...]:
    """The questions of the run's main list, before the reminders reviewers rejected are left
    out. Raises like :func:`_base` when the report cannot be computed.

    A finished run's questions only change when a reviewer decides on one of its findings (a
    rejected finding leaves the report, a confirmed one changes its track record). Building
    them reads the bill and runs every check, about 0.3 s a bill, so they are kept with the
    mark of the run's findings and built again once that mark moves."""
    with wb.uow() as uow:
        mark = uow.issues.change_mark(IssueQuery(run_id=run_id))
    cached = wb.run_questions.get(run_id)
    if cached is not None and cached[0] == mark:
        return cached[1]
    base = _base(wb, run_id)
    main, _, _ = triage(base.graded, base.tables)
    questions = tuple(
        ClarificationQuestion(document_id, risk.risk_id, risk.tier, risk.question)
        for risk in main
        if risk.question
    )
    wb.run_questions.put(run_id, (mark, questions))
    return questions


def clarification_questions(wb: Workbench, project: Project) -> list[ClarificationQuestion]:
    """The questions the reminders of the project's last validation ask the client: the main
    list of each bill's risk report, as :func:`bid_report` reads it, without the reminders
    reviewers rejected; in the order of the project's files, then of each list. A bill whose
    report cannot be computed, or a project not validated or still validating, gives none."""
    validation = project.validation
    if validation is None or validation.status == "running":
        return []
    questions: list[ClarificationQuestion] = []
    for file in project.files:
        run_id = validation.runs.get(file.document_id)
        if run_id is None:
            continue
        try:
            asked = _run_questions(wb, file.document_id, run_id)
        except (ConflictError, InvalidInputError, NotFoundError):
            continue
        rejected = {
            r.risk_id for r in list_risk_reviews(wb, run_id).items if r.status == "rejected"
        }
        questions.extend(q for q in asked if q.risk_id not in rejected)
    return questions


# ----------------------------------------------------------------------------- discovery runs
def start_discovery(
    wb: Workbench,
    run_id: str,
    strategy: Strategy,
    *,
    rerun: bool = False,
    generator: Generator | None = None,
    background: bool = False,
) -> tuple[DiscoveryRun, bool]:
    """(the run, whether it was started now). A run for the same inputs that is queued or
    running is returned, never started twice; a finished or failed one is returned unless
    ``rerun`` asks for a new one. ``background`` queues it on the job runner (poll it);
    otherwise it runs within the call."""
    base = _base(wb, run_id)
    inputs = _inputs(wb, base, strategy, generator)
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:24]
    store = _store(wb)
    with LOCK:
        for existing in store.for_run(run_id):
            settled = _settled(wb, existing)
            if settled.fingerprint == fingerprint and (
                settled.status in ("queued", "running") or not rerun
            ):
                return settled, False
        if background:
            wb.jobs.ensure_capacity()  # refuse (503) before anything is stored
        run = DiscoveryRun(
            discovery_run_id=wb.ids.new("disc"),
            run_id=run_id,
            strategy=strategy,
            status="queued",
            inputs=inputs,
            fingerprint=fingerprint,
            requested_at=wb.clock.now(),
        )
        store.save(run)
        ACTIVE.add(run.discovery_run_id)
    if not background:
        return _execute(wb, base, run, generator), True
    try:
        wb.jobs.submit(
            run.discovery_run_id,
            partial(_work, wb, base, run, generator),
            on_cancelled=partial(_end, wb, run, "the server shut down before the run started"),
        )
    except JobRefusedError:
        _end(wb, run, "the server refused background work")
        raise
    return run, True


def discovery_run(wb: Workbench, run_id: str, discovery_run_id: str) -> DiscoveryRun:
    found = _store(wb).get(discovery_run_id)
    if found is None or found.run_id != run_id:
        raise NotFoundError(
            f"Unknown discovery run {discovery_run_id!r} for validation run {run_id!r}."
        )
    return _settled(wb, found)


def discovery_runs(wb: Workbench, run_id: str) -> DiscoveryRunList:
    with wb.uow() as uow:
        if uow.runs.get(run_id) is None:
            raise NotFoundError(f"Unknown validation run {run_id!r}.")
    items = [_settled(wb, r) for r in _store(wb).for_run(run_id)]
    return DiscoveryRunList(
        items=[
            DiscoveryRunSummary(
                discovery_run_id=r.discovery_run_id,
                strategy=r.strategy,
                status=r.status,
                discovery_status=r.discovery.status if r.discovery else None,
                fingerprint=r.fingerprint,
                requested_at=r.requested_at,
                finished_at=r.finished_at,
                findings=len(r.findings),
            )
            for r in items
        ]
    )


def _execute(
    wb: Workbench, base: _Base, run: DiscoveryRun, generator: Generator | None
) -> DiscoveryRun:
    store = _store(wb)
    began = time.monotonic()
    running = run.model_copy(update={"status": "running", "started_at": wb.clock.now()})
    store.save(running)
    try:
        try:
            found = discover(
                base.bill,
                base.graded,
                base.tables,
                wb.settings.llm,
                strategy=run.strategy,
                generator=generator,
            )
        except Exception as exc:
            done = running.model_copy(
                update={
                    "status": "failed",
                    "error": clip(f"{type(exc).__name__}: {exc}", 600),
                    "finished_at": wb.clock.now(),
                    "seconds_total": round(time.monotonic() - began, 3),
                }
            )
        else:
            record = found.discovery.model_copy(update={"discovery_run_id": run.discovery_run_id})
            done = running.model_copy(
                update={
                    "status": "finished",
                    "discovery": record,
                    "findings": list(found.findings),
                    "rejected": list(found.rejected),
                    "repeats": list(found.repeats),
                    "exchanges": list(found.exchanges),
                    "finished_at": wb.clock.now(),
                    "seconds_total": round(time.monotonic() - began, 3),
                    "seconds_model": round(sum(c.seconds for c in record.calls), 3),
                }
            )
        with LOCK:
            store.save(done)
            ACTIVE.discard(run.discovery_run_id)
    finally:
        ACTIVE.discard(run.discovery_run_id)
    return done


def _work(wb: Workbench, base: _Base, run: DiscoveryRun, generator: Generator | None) -> None:
    _execute(wb, base, run, generator)  # a background job keeps its result on the run


def _end(wb: Workbench, run: DiscoveryRun, why: str) -> None:
    with LOCK:
        failed = run.model_copy(
            update={
                "status": "failed",
                "error": f"{why}; start it again with rerun",
                "finished_at": wb.clock.now(),
            }
        )
        _store(wb).save(failed)
        ACTIVE.discard(run.discovery_run_id)


def _settled(wb: Workbench, run: DiscoveryRun) -> DiscoveryRun:
    """``run`` as it stands; one left queued or running by a stopped server is failed."""
    if run.status not in ("queued", "running"):
        return run
    with LOCK:
        current = _store(wb).get(run.discovery_run_id) or run  # read again under the lock
        if current.status not in ("queued", "running") or current.discovery_run_id in ACTIVE:
            return current
        _end(wb, current, "interrupted: the server stopped before this run finished")
        return _store(wb).get(run.discovery_run_id) or current


def _stored(
    wb: Workbench, base: _Base, discovery_run_id: str
) -> tuple[DiscoveryRun | None, Discovery]:
    """(the run to apply, or None, and the discovery record the report shows)."""
    run = discovery_run(wb, base.run.run_id, discovery_run_id)
    common: dict[str, Any] = {
        "discovery_run_id": run.discovery_run_id,
        "strategy": run.strategy,
        "positions_total": len(base.bill.positions),
    }
    if run.status in ("queued", "running"):
        detail = (
            "This discovery run has not finished: nothing is applied yet. Poll it at its own "
            "address; reading the report never starts or repeats it."
        )
        return None, Discovery(status=run.status, detail=detail, **common)
    if run.status == "failed" or run.discovery is None:
        detail = f"This discovery run failed ({run.error or 'no record'}): nothing is applied."
        return None, Discovery(status="failed", detail=detail, **common)
    now = _inputs(wb, base, run.strategy, None)
    changed = [key for key in _BOUND if run.inputs.get(key) != now.get(key)]
    if changed:
        detail = (
            f"Made for other inputs ({', '.join(changed)} changed since; it was made for "
            f"{json.dumps({k: run.inputs.get(k) for k in changed}, sort_keys=True)}): its "
            "hypotheses are not applied. It stays readable at its own address; start a new "
            "run to check the current inputs."
        )
        record = run.discovery
        return None, Discovery(
            status="outdated",
            detail=clip(detail, 2000),
            model=record.model,
            prompt_version=record.prompt_version,
            table_version=record.table_version,
            **common,
        )
    return run, run.discovery


def _discovery(stored: DiscoveryRun, placement: Placement) -> Discovery:
    """The stored record with each finding tied to the reminder it became or joined, and every
    finding not kept on its own listed with its reason."""
    record = stored.discovery
    assert record is not None  # a finished run has its record
    reminder_of = dict(placement.reminder_of)
    for repeat in stored.repeats:  # a repeat goes where the finding it repeats went
        if repeat.finding_id and repeat.same_as and repeat.same_as[0] in reminder_of:
            reminder_of[repeat.finding_id] = reminder_of[repeat.same_as[0]]
    findings = [
        f.model_copy(update={"reminder_id": reminder_of.get(f.finding_id)}) for f in stored.findings
    ]
    merges = [n for n in placement.notes if n.stage == "same_cause"]
    others = [n for n in placement.notes if n.stage != "same_cause"]
    rejected = [*stored.rejected, *others]
    duplicates = [*merges, *stored.repeats]
    return record.model_copy(
        update={
            "discovery_run_id": stored.discovery_run_id,
            "rejected": rejected[:MAX_LISTED],
            "rejected_total": len(rejected),
            "duplicates": duplicates[:MAX_LISTED],
            "kept": len(placement.candidates),
            "merged": len(placement.merged),
            "findings": findings[:MAX_LISTED],
            "findings_total": len(findings),
            "reminder_ids": list(dict.fromkeys(placement.reminder_of.values())),
        }
    )


def _inputs(
    wb: Workbench, base: _Base, strategy: Strategy, generator: Generator | None
) -> dict[str, str]:
    """What a stored result is bound to (``_BOUND``), and the strategy and model that made it."""
    run, settings = base.run, wb.settings.llm
    return {
        "validation_run": run.run_id,
        "dataset": f"{run.dataset_id}@{run.dataset_revision}",
        "profile": f"{run.profile_id}@{run.profile_version}",
        "bill_text": _digest(base.bill),
        "tables": json.dumps(base.tables.versions, sort_keys=True),
        "report_format": FORMAT_VERSION,
        "prompt_and_checks": PROMPT_VERSION,
        "selection_and_context": context_key(
            base.bill, base.graded, base.tables, strategy=strategy
        ),
        "strategy": strategy,
        "model": "injected generator"
        if generator is not None
        else f"{settings.provider}:{settings.model}",
    }


def _digest(bill: Bill) -> str:
    """A digest of the texts the model may be shown: positions (with unit and quantity) and
    notes."""
    digest = hashlib.sha256()
    for p in bill.positions:
        fields = [p.key, p.label, p.original, p.unit or "", str(p.quantity)]
        digest.update(("\x1f".join(fields) + "\x1e").encode())
    for note in bill.notes:
        digest.update(f"{note.section_id}\x1f{note.source}\x1f{note.text}\x1e".encode())
    return digest.hexdigest()[:24]


def _store(wb: Workbench) -> DiscoveryRunStore:
    return DiscoveryRunStore(wb.settings.data_dir / "risk_discovery")


def _coverage_note(sources: SourceCoverage) -> str:
    preface = {True: "read", False: "not read", None: "unknown"}[sources.preface_read]
    parts = [f"Source coverage as stated by {sources.stated_by}: preliminary text {preface}"]
    if sources.not_read:
        parts.append("not read: " + ", ".join(sources.not_read[:10]))
    if sources.not_provided:
        parts.append("not provided: " + ", ".join(sources.not_provided[:10]))
    return "; ".join(parts) + ". 'Not found' covers only what was read."
