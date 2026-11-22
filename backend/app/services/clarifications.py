"""A project's clarifications: the questions to settle before the bid decision.

A reminder of the risk report that cannot be decided yet becomes a clarification: a question to
the client (a bidder question), a request to a subcontractor, or a decision for management. Each
says how far it is and the day its answer is needed. One reminder can have several, one for each
party asked.

A risk report is computed on request and never stored, so a clarification keeps what it needs
from its reminder: the bill (``document_id``), the reminder's id (stable across the runs of that
bill) and its review priority when the clarification was raised (``tier``).

An email drafted about a reminder (by a reviewer or by Desvio) is a bidder question too: it is
listed as a draft with the email's recipient, subject and body, and becomes "sent" with the
time once someone opens it in their email app or copies it. Nobody can know whether it really
went out; that click is the closest the workbench sees.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date

from sqlalchemy import insert, select, update

from app.core.errors import InvalidInputError, NotFoundError
from app.models.issue import SEVERITY_RANK
from app.models.project import Project
from app.repositories.sql.database import Database
from app.repositories.sql.schema import clarifications as table
from app.risk.service import clarification_questions
from app.schemas.clarifications import (
    Clarification,
    ClarificationInput,
    ClarificationItem,
    ClarificationPage,
    EmailClarification,
    ItemStatus,
    Kind,
    NewClarification,
    Phase,
)
from app.services import projects
from app.services.workbench import Workbench

# A year typed short (2, 26) or half-typed reads as a day in antiquity: no bill runs that long.
EARLIEST_DUE_DATE = date(2000, 1, 1)
LATEST_DUE_DATE = date(2100, 12, 31)


def check_due_date(due: date | None) -> None:
    """Reject (422) a clarification's or a finding task's due date that is not between 2000
    and 2100."""
    if due is not None and not EARLIEST_DUE_DATE <= due <= LATEST_DUE_DATE:
        raise InvalidInputError(
            f"Use a due date between {EARLIEST_DUE_DATE.isoformat()} and "
            f"{LATEST_DUE_DATE.isoformat()}; {due.isoformat()} is not one.",
            details={"due_date": due.isoformat()},
        )


def _database(wb: Workbench) -> Database:
    if wb.database is None:
        raise InvalidInputError("Clarifications require SQL persistence.")
    return wb.database


def _project(wb: Workbench, project_id: str) -> Project:
    """The project, or 404. Its unit of work ends here: SQLite allows one connection a thread."""
    with wb.uow() as uow:
        return projects.load(uow, project_id)


@dataclass(frozen=True, slots=True)
class ClarificationQuery:
    """What a listing keeps: each field left empty keeps everything."""

    search: str = ""  # words found in the item, its bill's name, its recipient or its answer
    phase: Phase | None = None
    kind: Kind | None = None
    status: ItemStatus | None = None
    due_by: date | None = None  # not decided, and its answer needed by this day


def _fold(text: str) -> str:
    """Lower case without accents: "Müller" and "muller" read alike."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _keeps(query: ClarificationQuery, item: ClarificationItem, bill: str) -> bool:
    status = "suggested" if item.clarification_id is None else item.status
    if (query.phase and item.phase != query.phase) or (query.kind and item.kind != query.kind):
        return False
    if query.status and status != query.status:
        return False
    if query.due_by and (item.status == "decided" or item.due is None or item.due > query.due_by):
        return False
    text = _fold("\n".join([item.title, bill, item.recipient or "", item.answer]))
    return all(word in text for word in _fold(query.search).split())


def list_clarifications(
    wb: Workbench,
    project_id: str,
    query: ClarificationQuery | None = None,
    *,
    offset: int = 0,
    limit: int = 10,
) -> ClarificationPage:
    """One page of what meets ``query``: the project's clarifications and the questions the
    reminders of its last validation ask that are not raised yet (draft bidder questions
    without an id). The most urgent priority comes first; within one, the clarifications in
    the order they were raised, then the questions in the order of the project's files and
    their risk reports."""
    query = query or ClarificationQuery()
    project = _project(wb, project_id)
    db = _database(wb)
    with db.connect() as c, db.begin(c):
        rows = c.execute(
            select(table)
            .where(table.c.project_id == project_id)
            .order_by(table.c.created_at, table.c.clarification_id)
        ).mappings()
        items: list[ClarificationItem] = [Clarification.model_validate(dict(row)) for row in rows]
    raised = {(item.document_id, item.risk_id) for item in items}
    items += [
        ClarificationItem(
            project_id=project_id,
            document_id=q.document_id,
            risk_id=q.risk_id,
            tier=q.tier,
            title=q.question[:300],
        )
        for q in clarification_questions(wb, project)
        if (q.document_id, q.risk_id) not in raised
    ]
    bills: dict[str, str] = {}
    if query.search.strip():
        with wb.uow() as uow:
            for file in project.files:
                document = uow.documents.get(file.document_id)
                bills[file.document_id] = document.original_filename if document else ""
    kept = [item for item in items if _keeps(query, item, bills.get(item.document_id, ""))]
    kept.sort(key=lambda item: -SEVERITY_RANK[item.tier])  # stable: each keeps its order
    return ClarificationPage(
        items=kept[offset : offset + limit], total=len(kept), offset=offset, limit=limit
    )


def raise_clarification(
    wb: Workbench, project_id: str, data: NewClarification
) -> tuple[Clarification, bool]:
    """Raise a clarification on a reminder of one of the project's bills, and say whether it is
    new. While the reminder has an undecided clarification of the same kind, that one is
    returned instead, so asking for clarification twice does not list the question twice.
    Raised as sent, it is sent now."""
    project = _project(wb, project_id)
    if data.document_id not in {file.document_id for file in project.files}:
        raise InvalidInputError(
            "This file is not part of the project.", details={"document_id": data.document_id}
        )
    check_due_date(data.due)
    db = _database(wb)
    now = wb.clock.now().isoformat()
    with db.connect() as c, db.begin(c):
        # shortcut: SQLite's write lock makes this check and the insert one step; on PostgreSQL
        # two requests at the same instant can both insert. Add a unique index if that shows.
        existing = (
            c.execute(
                select(table).where(
                    table.c.project_id == project_id,
                    table.c.document_id == data.document_id,
                    table.c.risk_id == data.risk_id,
                    table.c.kind == data.kind,
                    table.c.status != "decided",
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            return Clarification.model_validate(dict(existing)), False
        row = {
            **data.model_dump(mode="json"),
            "clarification_id": wb.ids.new("clr"),
            "project_id": project_id,
            "sent_at": now if data.status == "sent" else None,
            "created_at": now,
            "updated_at": now,
        }
        c.execute(insert(table).values(**row))
        return Clarification.model_validate(row), True


def record_email(wb: Workbench, project_id: str, data: EmailClarification) -> Clarification:
    """List an email about a reminder as its bidder question: the undecided one the reminder
    has, else a new draft. It takes the email's text, and the recipient once one is known; a
    ``sent`` email moves a draft to sent and keeps the first time it was sent."""
    with wb.uow() as uow:
        project = projects.load(uow, project_id)
    if data.document_id not in {file.document_id for file in project.files}:
        raise InvalidInputError(
            "This file is not part of the project.", details={"document_id": data.document_id}
        )
    db = _database(wb)
    now = wb.clock.now().isoformat()
    email = {"subject": data.subject, "body": data.body}
    if data.recipient.strip():
        email["recipient"] = data.recipient.strip()
    if data.issue_id:
        email["issue_id"] = data.issue_id
    with db.connect() as c, db.begin(c):
        existing = (
            c.execute(
                select(table).where(
                    table.c.project_id == project_id,
                    table.c.document_id == data.document_id,
                    table.c.risk_id == data.risk_id,
                    table.c.kind == "bidder_question",
                    table.c.status != "decided",
                )
            )
            .mappings()
            .first()
        )
        if existing is None:
            row = {
                **NewClarification(
                    document_id=data.document_id,
                    risk_id=data.risk_id,
                    tier=data.tier,
                    title=data.title,
                    status="sent" if data.sent else "draft",
                ).model_dump(mode="json"),
                **email,
                "clarification_id": wb.ids.new("clr"),
                "project_id": project_id,
                "sent_at": now if data.sent else None,
                "created_at": now,
                "updated_at": now,
            }
            c.execute(insert(table).values(**row))
            return Clarification.model_validate(row)
        values: dict[str, object] = {**email, "updated_at": now}
        if data.sent and existing["status"] == "draft":
            values["status"] = "sent"
        if data.sent and existing["sent_at"] is None:
            values["sent_at"] = now
        found = table.c.clarification_id == existing["clarification_id"]
        c.execute(update(table).where(found).values(**values))
        return Clarification.model_validate(
            dict(c.execute(select(table).where(found)).mappings().one())
        )


def update_clarification(
    wb: Workbench, clarification_id: str, data: ClarificationInput
) -> Clarification:
    """Replace what a reviewer sets on a clarification: who is asked, its wording, how far it
    is, the day the answer is needed, the phase and the answer. Its email stays; set to sent
    for the first time, it is sent now."""
    check_due_date(data.due)
    db = _database(wb)
    with db.connect() as c, db.begin(c):
        found = table.c.clarification_id == clarification_id
        now = wb.clock.now().isoformat()
        values = {**data.model_dump(mode="json"), "updated_at": now}
        if c.execute(update(table).where(found).values(**values)).rowcount == 0:
            raise NotFoundError("Clarification not found.")
        if data.status == "sent":
            c.execute(update(table).where(found, table.c.sent_at.is_(None)).values(sent_at=now))
        return Clarification.model_validate(
            dict(c.execute(select(table).where(found)).mappings().one())
        )
