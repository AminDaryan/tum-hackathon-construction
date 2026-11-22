"""Shared reviewer names and real finding discussions behind the existing access gate.

Names are deliberately selectable, not verified accounts. The opaque HttpOnly cookie binds
subsequent writes/inbox reads to the chosen reviewer; clients cannot supply an author id.

A finding can also carry one task: who follows it up (a reviewer), how far that work is and
what kind of work it is. The task is separate from the review decision (is this a real risk?):
a finding can be approved and still have a fix in progress. Task changes appear in the
finding's thread as activity entries, and assigning someone notifies them like a mention.

Tagging ``@desvio`` asks the review assistant (:mod:`app.services.decivio_bot`) to answer in
the thread. It answers after the comment is stored, in a background task, so posting stays
fast; the thread reports ``bot_working`` meanwhile. Its task changes are activity entries
authored by Desvio that name who asked. Desvio has a reviewer row (created on first use) so
its entries join like any other, but nobody can choose its name.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, delete, func, insert, select, update

from app.core.errors import InvalidInputError, NotFoundError
from app.repositories.sql.database import Database
from app.repositories.sql.schema import (
    assistant_replies,
    issues,
    reviewers,
)
from app.repositories.sql.schema import (
    finding_comments as comments,
)
from app.repositories.sql.schema import (
    finding_tasks as tasks,
)
from app.repositories.sql.schema import (
    mention_notifications as notifications,
)
from app.repositories.sql.schema import (
    reviewer_sessions as sessions,
)
from app.risk.service import risk_report
from app.schemas.clarifications import EmailClarification
from app.schemas.collaboration import TaskInput
from app.services import decivio_bot
from app.services import issues as issue_service
from app.services.clarifications import check_due_date, record_email
from app.services.workbench import Workbench

logger = logging.getLogger(__name__)

MENTION = re.compile(r"(?<![\w@])@([a-zA-Z][a-zA-Z0-9_]{0,31})(?![\w])")
STATUS_LABELS = {
    "todo": "To do",
    "in_progress": "In progress",
    "waiting": "Waiting",
    "done": "Done",
}
TYPE_LABELS = {
    "check": "Check",
    "fix": "Fix",
    "ask_client": "Ask client",
    "discussion": "Discussion",
}
SESSION_DAYS = 7
BOT = decivio_bot.HANDLE
BOT_HANDLES = {BOT, *decivio_bot.LEGACY_HANDLES}
# Findings Desvio is answering on, with how many answers are under way (this process only).
_working: dict[str, int] = {}
_working_lock = threading.Lock()
# The answer being written on each finding, as streamed so far: the text, and whether it has
# been stored in the thread (``done``). One uvicorn worker, so one process holds every answer.
_live: dict[str, dict[str, Any]] = {}


# The team's names exist from the start (the preview's /data is wiped on every deploy), so
# they can be picked, switched to and @mentioned at once; anyone can still join with a new name.
TEAM_REVIEWERS = ("Imants", "Larissa", "Amin", "Muhammad", "Ziyu", "Johan")


def seed_reviewers(wb: Workbench) -> None:
    """Add the :data:`TEAM_REVIEWERS` that are missing; existing reviewers are left as they are."""
    db = wb.database
    if db is None:
        return
    with db.connect() as c, db.begin(c):
        known = set(c.execute(select(reviewers.c.handle)).scalars())
        missing = [name for name in TEAM_REVIEWERS if name.lower() not in known]
        if missing:
            c.execute(insert(reviewers), [{"handle": n.lower(), "name": n} for n in missing])


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current(connection: Connection, token: str) -> dict[str, Any] | None:
    """The reviewer whose unexpired session the cookie ``token`` opens, if any."""
    row = (
        connection.execute(
            select(reviewers)
            .join(sessions)
            .where(
                sessions.c.token_hash == token_hash(token),
                sessions.c.expires_at > datetime.now(UTC).isoformat(),
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def require_reviewer(connection: Connection, token: str) -> dict[str, Any]:
    person = current(connection, token)
    if person is None or person["handle"] == BOT:
        raise InvalidInputError("Choose your reviewer name first.")
    return person


def ensure_bot(connection: Connection) -> None:
    if not connection.execute(select(reviewers.c.handle).where(reviewers.c.handle == BOT)).first():
        connection.execute(insert(reviewers).values(handle=BOT, name=decivio_bot.NAME))
    connection.execute(
        update(reviewers)
        .where(reviewers.c.handle.in_(decivio_bot.LEGACY_HANDLES))
        .values(name=decivio_bot.NAME)
    )


def people(connection: Connection) -> list[dict[str, Any]]:
    """The reviewers people can choose, mention and assign: everyone but Desvio."""
    return [
        dict(row)
        for row in connection.execute(
            select(reviewers).where(~reviewers.c.handle.in_(BOT_HANDLES)).order_by(reviewers.c.name)
        ).mappings()
    ]


def task_of(connection: Connection, issue_id: str) -> dict[str, Any] | None:
    assignee = reviewers.alias("assignee_reviewer")
    row = (
        connection.execute(
            select(tasks, assignee.c.name.label("assignee_name"))
            .outerjoin(assignee, tasks.c.assignee == assignee.c.handle)
            .where(tasks.c.issue_id == issue_id)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def add_entry(
    connection: Connection, issue_id: str, author: str, kind: str, body: str
) -> dict[str, Any]:
    entry = {
        "comment_id": str(uuid4()),
        "issue_id": issue_id,
        "author": author,
        "kind": kind,
        "body": body,
        "created_at": datetime.now(UTC).isoformat(),
    }
    connection.execute(insert(comments).values(**entry))
    return entry


def apply_task(
    connection: Connection,
    issue_id: str,
    editor: str,
    *,
    assignee: str | None,
    status: str,
    task_type: str | None,
    due_date: str | None,
    asked_by: str | None = None,
) -> list[str]:
    """Set the finding's task and return the changes. The changes are logged in the thread as
    one activity entry by ``editor`` (naming ``asked_by`` when Desvio acts for someone), and a
    new assignee other than the person behind the change is notified."""
    names = {person["handle"]: person["name"] for person in people(connection)}
    if assignee is not None and assignee not in names:
        raise InvalidInputError(f"Unknown reviewer: {assignee}")
    old = task_of(connection, issue_id) or {
        "assignee": None,
        "status": "todo",
        "task_type": None,
        "due_date": None,
    }
    changes = []
    if assignee != old["assignee"]:
        changes.append(f"assigned {names[assignee]}" if assignee else "removed the assignee")
    if status != old["status"]:
        changes.append(f"set status to {STATUS_LABELS[status]}")
    if task_type != old["task_type"]:
        changes.append(f"set type to {TYPE_LABELS[task_type]}" if task_type else "cleared the type")
    if due_date != old["due_date"]:
        changes.append(f"set due date to {due_date}" if due_date else "cleared the due date")
    if not changes:
        return changes
    values = {
        "assignee": assignee,
        "status": status,
        "task_type": task_type,
        "due_date": due_date,
        "updated_by": editor,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if (
        connection.execute(
            update(tasks).where(tasks.c.issue_id == issue_id).values(**values)
        ).rowcount
        == 0
    ):
        connection.execute(insert(tasks).values(issue_id=issue_id, **values))
    body = ", ".join(changes)
    if asked_by:
        body += f" (asked by {names.get(asked_by, asked_by)})"
    entry = add_entry(connection, issue_id, editor, "activity", body)
    if assignee and assignee != old["assignee"] and assignee != (asked_by or editor):
        notify(connection, {assignee}, entry["comment_id"])
    return changes


def notify(connection: Connection, recipients: set[str], comment_id: str) -> None:
    for handle in recipients:
        connection.execute(
            insert(notifications).values(
                notification_id=str(uuid4()),
                recipient=handle,
                comment_id=comment_id,
                is_read=0,
            )
        )


def database(wb: Workbench) -> Database:
    if wb.database is None:
        raise InvalidInputError("Collaboration requires SQL persistence.")
    return wb.database


def session(wb: Workbench, token: str) -> dict[str, Any]:
    """Who the cookie ``token`` signs in (None for nobody), the people to choose from, and
    Desvio."""
    db = database(wb)
    with db.connect() as c, db.begin(c):
        ensure_bot(c)
        person = current(c, token)
        return {
            "reviewer": person if person and person["handle"] != BOT else None,
            "reviewers": people(c),
            "bot": {
                "handle": BOT,
                "name": decivio_bot.NAME,
                "connected": decivio_bot.connected(),
            },
        }


def choose_reviewer(wb: Workbench, name: str, old_token: str) -> tuple[dict[str, Any], str]:
    """Sign in as ``name`` (added when new) and return the reviewer with the new session's
    token. The session behind ``old_token`` and every expired one end."""
    db = database(wb)
    handle = name.lower()
    if handle == BOT:
        raise InvalidInputError(f"{decivio_bot.NAME} is the assistant's name. Choose another.")
    token = secrets.token_urlsafe(32)
    with db.connect() as c, db.begin(c):
        person = c.execute(select(reviewers).where(reviewers.c.handle == handle)).mappings().first()
        if person is None:
            c.execute(insert(reviewers).values(handle=handle, name=name))
        c.execute(
            delete(sessions).where(
                (sessions.c.token_hash == token_hash(old_token))
                | (sessions.c.expires_at <= datetime.now(UTC).isoformat())
            )
        )
        c.execute(
            insert(sessions).values(
                token_hash=token_hash(token),
                handle=handle,
                expires_at=(datetime.now(UTC) + timedelta(days=SESSION_DAYS)).isoformat(),
            )
        )
        result = dict(
            c.execute(select(reviewers).where(reviewers.c.handle == handle)).mappings().one()
        )
    return result, token


def list_comments(wb: Workbench, issue_id: str) -> dict[str, Any]:
    issue_service.get(wb, issue_id)
    db = database(wb)
    with db.connect() as c, db.begin(c):
        rows = c.execute(
            select(
                comments,
                reviewers.c.name.label("author_name"),
                assistant_replies.c.payload.label("assistant"),
            )
            .join(reviewers)
            .outerjoin(assistant_replies)
            .where(comments.c.issue_id == issue_id)
            .order_by(comments.c.created_at, comments.c.comment_id)
        ).mappings()
        return {
            "items": [dict(row) for row in rows],
            "task": task_of(c, issue_id),
            "bot_working": _working.get(issue_id, 0) > 0,
        }


def post_comment(wb: Workbench, token: str, issue_id: str, text: str) -> dict[str, Any]:
    """Store a comment and notify the reviewers it mentions. When it tags Desvio,
    ``bot_replying`` is true and the finding counts as being answered until
    :func:`answer_mention`, which the caller starts, ends."""
    issue_service.get(wb, issue_id)
    body = text.strip()
    if not body:
        raise InvalidInputError("Write a comment before sending.")
    db = database(wb)
    with db.connect() as c, db.begin(c):
        person = require_reviewer(c, token)
        handles = {match.lower() for match in MENTION.findall(body)} - {person["handle"]}
        bot_tagged = bool(handles & BOT_HANDLES)
        handles -= BOT_HANDLES
        known = set(
            c.execute(select(reviewers.c.handle).where(reviewers.c.handle.in_(handles))).scalars()
        )
        if handles - known:
            raise InvalidInputError(
                "Unknown reviewer mention: " + ", ".join(sorted(handles - known))
            )
        comment = add_entry(c, issue_id, person["handle"], "comment", body)
        notify(c, known, comment["comment_id"])
    if bot_tagged:
        with _working_lock:
            _working[issue_id] = _working.get(issue_id, 0) + 1
        with _working_lock:
            _live[issue_id] = {"text": "", "done": False}
    return {**comment, "author_name": person["name"], "bot_replying": bot_tagged}


def put_task(wb: Workbench, token: str, issue_id: str, data: TaskInput) -> dict[str, Any]:
    """Set the finding's task. Each change is logged in the thread; a new assignee other than
    the editor is notified, in the same transaction."""
    issue_service.get(wb, issue_id)
    check_due_date(data.due_date)
    db = database(wb)
    with db.connect() as c, db.begin(c):
        person = require_reviewer(c, token)
        apply_task(
            c,
            issue_id,
            person["handle"],
            assignee=data.assignee.lower() if data.assignee else None,
            status=data.status,
            task_type=data.task_type,
            due_date=data.due_date.isoformat() if data.due_date else None,
        )
        return {"task": task_of(c, issue_id)}


def run_tasks(wb: Workbench, run_id: str) -> dict[str, Any]:
    """The tasks on a run's findings, for the risk list."""
    db = database(wb)
    assignee = reviewers.alias("assignee_reviewer")
    with db.connect() as c, db.begin(c):
        rows = c.execute(
            select(tasks, assignee.c.name.label("assignee_name"))
            .join(issues, tasks.c.issue_id == issues.c.issue_id)
            .outerjoin(assignee, tasks.c.assignee == assignee.c.handle)
            .where(issues.c.validation_run_id == run_id)
        ).mappings()
        return {"items": [dict(row) for row in rows]}


def list_notifications(wb: Workbench, token: str) -> dict[str, Any]:
    db = database(wb)
    with db.connect() as c, db.begin(c):
        person = require_reviewer(c, token)
        rows = c.execute(
            select(
                notifications,
                comments.c.kind,
                comments.c.author,
                comments.c.body,
                comments.c.created_at,
                comments.c.issue_id,
                reviewers.c.name.label("author_name"),
                issues.c.document_id,
                issues.c.validation_run_id,
                issues.c.payload,
            )
            .select_from(
                notifications.join(comments)
                .join(reviewers, comments.c.author == reviewers.c.handle)
                .join(issues, comments.c.issue_id == issues.c.issue_id)
            )
            .where(notifications.c.recipient == person["handle"])
            .order_by(
                notifications.c.is_read,
                comments.c.created_at.desc(),
                notifications.c.notification_id,
            )
            .limit(100)
        ).mappings()
        items = []
        for row in rows:
            item = dict(row)
            item["issue_title"] = item.pop("payload")["title"]
            items.append(item)
        unread = c.execute(
            select(func.count())
            .select_from(notifications)
            .where(notifications.c.recipient == person["handle"], notifications.c.is_read == 0)
        ).scalar_one()
        return {"items": items, "unread_count": unread}


def mark_read(wb: Workbench, token: str, notification_id: str) -> None:
    """Opening a notification opens its finding, so every unread notification of the
    recipient on that finding (a mention and an assignment, say) is read with it."""
    db = database(wb)
    with db.connect() as c, db.begin(c):
        person = require_reviewer(c, token)
        issue_id = c.execute(
            select(comments.c.issue_id)
            .join(notifications)
            .where(
                notifications.c.notification_id == notification_id,
                notifications.c.recipient == person["handle"],
            )
        ).scalar_one_or_none()
        if issue_id is None:
            raise NotFoundError("Notification not found.")
        c.execute(
            update(notifications)
            .where(
                notifications.c.recipient == person["handle"],
                notifications.c.comment_id.in_(
                    select(comments.c.comment_id).where(comments.c.issue_id == issue_id)
                ),
            )
            .values(is_read=1)
        )


def live_answer(issue_id: str) -> tuple[str, bool]:
    """Desvio's answer on the finding as written so far, and whether it is stored in the
    thread (also true when no answer is under way)."""
    with _working_lock:
        live = _live.get(issue_id)
        return (live["text"] if live else ""), (live is None or live["done"])


def _bot_task_change(db: Database, issue_id: str, asker: str, change: dict[str, Any]) -> str:
    """Apply one ``update_task`` call of Desvio; unknown values raise for the model to see."""
    with db.connect() as c, db.begin(c):
        old = task_of(c, issue_id) or {
            "assignee": None,
            "status": "todo",
            "task_type": None,
            "due_date": None,
        }
        assignee = change.get("assignee", old["assignee"])
        if isinstance(assignee, str):
            assignee = None if assignee.lower() in ("none", "") else assignee.lstrip("@").lower()
        status = change.get("status", old["status"])
        if status not in STATUS_LABELS:
            raise InvalidInputError(f"Unknown status: {status}")
        task_type = change.get("task_type", old["task_type"])
        task_type = None if task_type in ("none", "") else task_type
        if task_type is not None and task_type not in TYPE_LABELS:
            raise InvalidInputError(f"Unknown type: {task_type}")
        due_date = change.get("due_date", old["due_date"])
        if due_date is not None:
            try:
                parsed = date.fromisoformat(due_date)
            except (TypeError, ValueError) as exc:
                raise InvalidInputError(
                    "Use a due date in YYYY-MM-DD format, or null to clear it."
                ) from exc
            check_due_date(parsed)
            due_date = parsed.isoformat()
        ensure_bot(c)
        changes = apply_task(
            c,
            issue_id,
            BOT,
            assignee=assignee,
            status=status,
            task_type=task_type,
            due_date=due_date,
            asked_by=asker,
        )
        outcome = "Done: " + ", ".join(changes) if changes else "Nothing to change."
        return f"{outcome}. {decivio_bot.DONE_NOTE}"


def answer_mention(wb: Workbench, issue_id: str, asker: str) -> None:
    """Desvio's answer to a comment by ``asker`` that tagged it, posted in the thread. The
    model is called outside any transaction, so the database is never locked while it thinks."""
    db = database(wb)
    try:
        with db.connect() as c, db.begin(c):
            names = {person["handle"]: person["name"] for person in people(c)}
            names[BOT] = decivio_bot.NAME
            task = task_of(c, issue_id)
            entries = list(
                c.execute(
                    select(comments)
                    .where(comments.c.issue_id == issue_id)
                    .order_by(comments.c.created_at.desc(), comments.c.comment_id.desc())
                    .limit(decivio_bot.MAX_THREAD_ENTRIES)
                ).mappings()
            )[::-1]
        thread = "\n".join(
            f"[{entry['created_at'][:16]}] {names.get(entry['author'], entry['author'])}"
            + (f" {entry['body']}" if entry["kind"] == "activity" else f": {entry['body']}")
            for entry in entries
        )
        task_text = (
            f"Assignee: {task['assignee_name'] or 'none'} ({task['assignee'] or 'none'}); "
            f"status: {STATUS_LABELS[task['status']]}; "
            f"type: {TYPE_LABELS[task['task_type']] if task['task_type'] else 'none'}; "
            f"due date: {task['due_date'] or 'none'}"
            if task
            else "No task yet (status To do, no assignee, no type, no due date)."
        )
        answer = decivio_bot.reply(
            finding=decivio_bot.finding_context(wb, issue_id),
            task=task_text,
            reviewers={h: n for h, n in names.items() if h != BOT},
            thread=thread,
            asked_by=f"{names.get(asker, asker)} ({asker})",
            act=lambda change: _bot_task_change(db, issue_id, asker, change),
            on_text=lambda piece: _stream_piece(issue_id, piece),
        )
    except decivio_bot.BotError as error:
        logger.warning("Desvio could not answer on finding %s: %s", issue_id, error)
        answer = decivio_bot.Reply(f"Sorry, I couldn't answer: {error}. Tag me again to retry.")
    except Exception:
        logger.exception("Desvio failed on finding %s", issue_id)
        answer = decivio_bot.Reply("Sorry, something went wrong on my side. Tag me again to retry.")
    if answer.email_draft is not None:
        try:
            answer.clarification = _list_email(wb, issue_id, answer.email_draft)
        except Exception:  # the draft still shows; only the clarifications list misses it
            logger.exception("Desvio's email on finding %s was not listed", issue_id)
    try:
        with db.connect() as c, db.begin(c):
            ensure_bot(c)
            entry = add_entry(c, issue_id, BOT, "comment", answer.text)
            if (extras := answer.extras()) is not None:
                c.execute(
                    insert(assistant_replies).values(comment_id=entry["comment_id"], payload=extras)
                )
            notify(c, {asker}, entry["comment_id"])
    finally:
        with _working_lock:
            _working[issue_id] -= 1
            if not _working[issue_id]:
                del _working[issue_id]
            live = _live.get(issue_id)
            if live is not None:
                live["done"] = True


def _list_email(wb: Workbench, issue_id: str, draft: dict[str, str]) -> dict[str, str] | None:
    """List Desvio's email draft among the clarifications of the finding's project, as a draft
    bidder question on the risk the finding is part of (on the finding itself when no risk of
    its run has it). None when the finding's bill is in no project. Returns what the interface
    needs to mark it sent: the project, the clarification and its risk."""
    issue = issue_service.get(wb, issue_id).issue
    with wb.uow() as uow:
        project = next(
            (
                p
                for p in uow.projects.list()
                if any(f.document_id == issue.document_id for f in p.files)
            ),
            None,
        )
    if project is None:
        return None
    report = risk_report(wb, issue.validation_run_id)
    risks = [*report.risks, *report.record]
    risk = next((r for r in risks if issue_id in r.source_issue_ids), None)
    listed = record_email(
        wb,
        project.project_id,
        EmailClarification(
            document_id=issue.document_id,
            risk_id=risk.risk_id if risk else issue_id,
            tier=risk.tier if risk else issue.severity,
            title=(risk.title if risk else issue.title)[:300],
            issue_id=issue_id,
            recipient=draft.get("to", ""),
            subject=draft["subject"],
            body=draft["body"],
        ),
    )
    return {
        "project_id": listed.project_id,
        "clarification_id": listed.clarification_id,
        "document_id": listed.document_id,
        "risk_id": listed.risk_id,
        "tier": listed.tier.value,
        "issue_id": issue_id,
        "title": listed.title,
    }


def _stream_piece(issue_id: str, piece: str) -> None:
    with _working_lock:
        live = _live.get(issue_id)
        if live is not None:
            live["text"] += piece
