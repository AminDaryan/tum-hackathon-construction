"""HTTP routes of a project's clarifications (see :mod:`app.services.clarifications`)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.routes._deps import Offset, workbench
from app.schemas.clarifications import (
    Clarification,
    ClarificationInput,
    ClarificationPage,
    EmailClarification,
    ItemStatus,
    Kind,
    NewClarification,
    Phase,
)
from app.services import clarifications

router = APIRouter(tags=["clarifications"])


@router.get("/projects/{project_id}/clarifications")
def list_clarifications(
    request: Request,
    project_id: str,
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    search: Annotated[str, Query(max_length=200)] = "",
    phase: Phase | None = None,
    kind: Kind | None = None,
    status: ItemStatus | None = None,
    due_by: Annotated[
        date | None, Query(description="Not decided, and the answer needed by this day.")
    ] = None,
) -> ClarificationPage:
    """One page of the project's clarifications and of the questions the reminders of its last
    validation ask that are not raised yet (no ``clarification_id``), that meet the search and
    filters; the most urgent priority first (see
    :func:`app.services.clarifications.list_clarifications`)."""
    query = clarifications.ClarificationQuery(
        search=search, phase=phase, kind=kind, status=status, due_by=due_by
    )
    return clarifications.list_clarifications(
        workbench(request), project_id, query, offset=offset, limit=limit
    )


@router.post(
    "/projects/{project_id}/clarifications",
    status_code=201,
    responses={
        200: {
            "model": Clarification,
            "description": "The reminder already has an undecided clarification of this kind: "
            "it is returned and nothing is added.",
        }
    },
)
def raise_clarification(
    request: Request, response: Response, project_id: str, data: NewClarification
) -> Clarification:
    """Raise a clarification on a reminder of one of the project's bills. While the reminder has
    an undecided clarification of the same kind, that one is returned (200), so asking for
    clarification twice does not list the question twice. Raised as sent, it is sent now."""
    clarification, created = clarifications.raise_clarification(
        workbench(request), project_id, data
    )
    if not created:
        response.status_code = 200
    return clarification


@router.post("/projects/{project_id}/clarifications/emails")
def post_email_clarification(
    request: Request, project_id: str, data: EmailClarification
) -> Clarification:
    """An email drafted about a reminder, listed as its bidder question (see
    :func:`app.services.clarifications.record_email`): drafted, or ``sent`` once opened in an
    email app or copied."""
    return clarifications.record_email(workbench(request), project_id, data)


@router.put("/clarifications/{clarification_id}")
def put_clarification(
    request: Request, clarification_id: str, data: ClarificationInput
) -> Clarification:
    """Replace what a reviewer sets on a clarification: who is asked, its wording, how far it
    is, the day the answer is needed, the phase and the answer. Its email stays; set to sent
    for the first time, it is sent now."""
    return clarifications.update_clarification(workbench(request), clarification_id, data)
