"""HTTP routes of reviewer names, finding discussions and tasks (see
:mod:`app.services.collaboration`).

The reviewer chosen is bound to an opaque HttpOnly cookie, so clients cannot supply an author
id. Desvio's answer is written in a background task after the comment is stored, and can be
followed as server-sent events while it is written.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import StreamingResponse

from app.api.routes._deps import workbench
from app.schemas.collaboration import CommentInput, ReviewerChoice, TaskInput
from app.services import collaboration
from app.services import issues as issue_service

router = APIRouter(prefix="/collaboration", tags=["collaboration"])
COOKIE = "twb_reviewer"
STREAM_POLL_SECONDS = 0.1
STREAM_HEARTBEAT_SECONDS = 15.0
STREAM_MAX_SECONDS = 300.0


def _token(request: Request) -> str:
    return request.cookies.get(COOKIE, "")


@router.get("/session")
def get_session(request: Request) -> dict[str, Any]:
    return collaboration.session(workbench(request), _token(request))


@router.post("/session")
def choose_reviewer(request: Request, response: Response, choice: ReviewerChoice) -> dict[str, Any]:
    wb = workbench(request)
    reviewer, token = collaboration.choose_reviewer(wb, choice.name, _token(request))
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=request.url.scheme == "https" or wb.settings.environment == "production",
        samesite="lax",
        max_age=collaboration.SESSION_DAYS * 86400,
    )
    return reviewer


@router.get("/issues/{issue_id}/comments")
def list_comments(request: Request, issue_id: str) -> dict[str, Any]:
    return collaboration.list_comments(workbench(request), issue_id)


@router.post("/issues/{issue_id}/comments", status_code=201)
def post_comment(
    request: Request, issue_id: str, data: CommentInput, background: BackgroundTasks
) -> dict[str, Any]:
    wb = workbench(request)
    comment = collaboration.post_comment(wb, _token(request), issue_id, data.body)
    if comment["bot_replying"]:
        background.add_task(collaboration.answer_mention, wb, issue_id, comment["author"])
    return comment


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get(
    "/issues/{issue_id}/assistant-stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Desvio's answer as server-sent events: text, then done.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream_answer(request: Request, issue_id: str) -> StreamingResponse:
    """Desvio's answer on this finding as server-sent events while it is written: ``text``
    events carry new text, ``done`` says the answer is stored in the thread (read the thread
    for the final reply, its task changes and attachments). With no answer under way, ``done``
    comes at once. Comment lines keep proxies from closing a quiet stream."""
    issue_service.get(workbench(request), issue_id)

    async def events() -> AsyncIterator[str]:
        sent = 0
        quiet = 0.0
        waited = 0.0
        while waited < STREAM_MAX_SECONDS:
            text, done = collaboration.live_answer(issue_id)
            if len(text) > sent:
                yield _sse("text", {"text": text[sent:]})
                sent, quiet = len(text), 0.0
            if done:
                yield _sse("done", {})
                return
            if await request.is_disconnected():
                return
            if quiet >= STREAM_HEARTBEAT_SECONDS:
                yield ": keep-alive\n\n"
                quiet = 0.0
            await asyncio.sleep(STREAM_POLL_SECONDS)
            quiet += STREAM_POLL_SECONDS
            waited += STREAM_POLL_SECONDS
        yield _sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.put("/issues/{issue_id}/task")
def put_task(request: Request, issue_id: str, data: TaskInput) -> dict[str, Any]:
    """Set the finding's task. Each change is logged in the thread; a new assignee other than
    the editor is notified, in the same transaction."""
    return collaboration.put_task(workbench(request), _token(request), issue_id, data)


@router.get("/validation-runs/{run_id}/tasks")
def list_run_tasks(request: Request, run_id: str) -> dict[str, Any]:
    """The tasks on a run's findings, for the risk list."""
    return collaboration.run_tasks(workbench(request), run_id)


@router.get("/notifications")
def list_notifications(request: Request) -> dict[str, Any]:
    return collaboration.list_notifications(workbench(request), _token(request))


@router.post("/notifications/{notification_id}/read")
def mark_read(request: Request, notification_id: str) -> dict[str, bool]:
    """Opening a notification opens its finding, so every unread notification of the
    recipient on that finding (a mention and an assignment, say) is read with it."""
    collaboration.mark_read(workbench(request), _token(request), notification_id)
    return {"read": True}
