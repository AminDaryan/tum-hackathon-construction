"""What Claude answered when a reviewer sent it a bill to review, stored per dataset.

Written by :mod:`app.services.bill_reviews` only when a validation run asks for it; every run
reads it through ``ValidationContext.bill_review`` and never calls a model (the check
``llm.bill_review`` lists its claims). A claim is kept as the model made it, already checked
against the bill: its position exists and its issue type was asked for. Which claims are listed
is decided by the check on each run, so a stricter check applies to a stored review without
asking again.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import FrozenModel

BillReviewStatus = Literal["completed", "partial", "failed"]


class BillReviewClaim(FrozenModel):
    """One issue the model names on one position. ``position_digest`` is the position as the
    model read it (:func:`app.agents.bill_review.position_digest`): the claim says nothing
    about a position that was changed since. ``grounded``: the quote's words or numbers stand
    in the position."""

    table_id: str
    row_id: str
    oz: str
    position_digest: str
    focus: str = Field(description="The pass that made the claim: numbers, basis or text.")
    issue_type: str | None = Field(description='The catalogue number, e.g. "081".')
    issue_name: str | None
    certainty: str | None = Field(description="high, medium or low, as the model rates it.")
    quote: str = Field(max_length=300)
    grounded: bool
    why: str = Field(max_length=600)
    related_oz: list[str] = Field(default_factory=list)


class BillReview(FrozenModel):
    """The last review of one dataset and how its request went. ``failed``: no pass answered,
    so there are no claims; ``partial``: at least one pass answered and one did not
    (``failed_passes``). ``detail`` names counts and failures, never bill content."""

    dataset_id: str
    dataset_revision: int = Field(ge=1, description="The revision of the bill the model read.")
    model: str
    prompt_version: str
    status: BillReviewStatus
    detail: str
    positions: int = Field(ge=0, description="Positions the model read.")
    failed_passes: list[str] = Field(default_factory=list)
    claims: list[BillReviewClaim] = Field(default_factory=list)
