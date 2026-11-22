"""The API shapes of a project's clarifications (see :mod:`app.services.clarifications`)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.issue import Severity

Kind = Literal["bidder_question", "subcontractor", "management"]
Status = Literal["draft", "sent", "answered", "decided"]
Phase = Literal["bid", "after_award"]
# How far a listed item is: "suggested" is a question nobody has raised yet.
ItemStatus = Literal["suggested", "draft", "sent", "answered", "decided"]


class ClarificationInput(BaseModel):
    """What a reviewer sets on a clarification. A PUT replaces all of it."""

    model_config = ConfigDict(extra="forbid")
    kind: Kind = "bidder_question"
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    status: Status = "draft"
    due: date | None = None  # the day the answer is needed
    phase: Phase = "bid"
    answer: str = Field(default="", max_length=4000)


class NewClarification(ClarificationInput):
    document_id: str = Field(min_length=1, max_length=100)
    risk_id: str = Field(min_length=1, max_length=100)
    # shortcut: copied when raised, so a later regrading of the reminder does not change it;
    # read the tier from the risk report instead once that costs the cutoff count its meaning.
    tier: Severity


class ClarificationItem(NewClarification):
    """A listed clarification, or (no ``clarification_id``) a question a reminder of the
    project's last validation asks the client that is not raised yet: a draft bidder question
    until a reviewer saves it."""

    clarification_id: str | None = None
    project_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # The email it was drafted as, when it was (see the module docstring).
    issue_id: str | None = None
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None
    sent_at: datetime | None = None


class Clarification(ClarificationItem):
    clarification_id: str
    created_at: datetime
    updated_at: datetime


class EmailClarification(BaseModel):
    """An email drafted about a reminder. ``sent``: it was opened in an email app or copied."""

    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=100)
    risk_id: str = Field(min_length=1, max_length=100)
    tier: Severity
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    issue_id: str | None = Field(default=None, max_length=100)  # the finding it is about
    recipient: str = Field(default="", max_length=500)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    sent: bool = False


class ClarificationPage(BaseModel):
    """One page of a project's clarifications and the questions not raised yet."""

    items: list[ClarificationItem]
    total: int  # how many meet the query, on every page
    offset: int
    limit: int
