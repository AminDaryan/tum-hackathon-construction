"""Review decisions on the reminders of the risk report that no finding carries.

A reminder found by a text check of the risk report (a vague quality word, a quantity marked
"ca.") has no finding, so the issue review cannot hold a decision on it. Its decision is an
audit event (``risk_reviewed``) on the run's document: the reminder id is stable across runs
(:func:`app.risk.grading.reminder_id`), so a decision carries over to the next run of the same
document, as a finding's decision does. The latest event for a reminder wins.

The reminder id is checked for its form only: the report is computed on request, and computing
it to check one id would cost more than the decision itself.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import InvalidInputError, NotFoundError
from app.models.audit import AuditAction, EntityType
from app.services.workbench import Workbench

RiskReviewStatus = Literal["open", "in_review", "approved", "rejected"]

_RISK_ID = re.compile(r"^risk_[0-9a-f]{16}$")
COMMENT_LIMIT = 4000


class RiskReviewRequest(BaseModel):
    status: RiskReviewStatus
    comment: str = Field(default="", max_length=COMMENT_LIMIT)


class RiskReview(BaseModel):
    risk_id: str
    status: RiskReviewStatus
    comment: str = ""
    reviewed_at: datetime | None = None
    run_id: str | None = None  # the run the decision was made on


class RiskReviewList(BaseModel):
    run_id: str
    items: list[RiskReview]


def _document_of(wb: Workbench, run_id: str) -> str:
    with wb.uow() as uow:
        run = uow.runs.get(run_id)
        if run is None:
            raise NotFoundError(f"Unknown validation run {run_id!r}.")
        return run.document_id


def list_risk_reviews(wb: Workbench, run_id: str) -> RiskReviewList:
    """The latest decision of every reminder decided in the run's document."""
    document_id = _document_of(wb, run_id)
    with wb.uow() as uow:
        events = uow.audit.list_for_entity(EntityType.DOCUMENT, document_id)
    latest: dict[str, RiskReview] = {}
    for event in events:
        if event.action is not AuditAction.RISK_REVIEWED or not event.after:
            continue
        review = RiskReview(
            risk_id=event.after["risk_id"],
            status=event.after["status"],
            comment=event.after.get("comment", ""),
            reviewed_at=event.occurred_at,
            run_id=event.context.get("run_id"),
        )
        latest.pop(review.risk_id, None)
        latest[review.risk_id] = review
    return RiskReviewList(run_id=run_id, items=list(latest.values()))


def review_risk(wb: Workbench, run_id: str, risk_id: str, request: RiskReviewRequest) -> RiskReview:
    """Record a decision on a reminder; ``open`` takes a decision back."""
    if not _RISK_ID.match(risk_id):
        raise InvalidInputError(
            "A reminder id is 'risk_' followed by 16 hexadecimal digits.",
            details={"risk_id": risk_id},
        )
    document_id = _document_of(wb, run_id)
    before = next((r for r in list_risk_reviews(wb, run_id).items if r.risk_id == risk_id), None)
    with wb.uow() as uow:
        wb.audit(
            uow,
            AuditAction.RISK_REVIEWED,
            EntityType.DOCUMENT,
            document_id,
            f"Reminder {risk_id} marked {request.status}",
            before={"risk_id": risk_id, "status": before.status if before else "open"},
            after={"risk_id": risk_id, "status": request.status, "comment": request.comment},
            context={"run_id": run_id},
        )
    reviewed = next(r for r in list_risk_reviews(wb, run_id).items if r.risk_id == risk_id)
    return reviewed
