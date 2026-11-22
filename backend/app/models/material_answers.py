"""What the local language model answered when asked to match bill positions to a product of
the price reference (``statistical.open_price_reference``), stored per dataset.

Written by :mod:`app.services.material_matches` only when a validation run asks for it; every
run reads it through ``ValidationContext.material_answers`` and never calls a model. An answer is
kept as the model wrote it: the check parses and verifies it again on each run, so a stricter
check applies to stored answers without asking again. ``key`` is the hash of the model and the
exact prompt (bill text, unit, catalogue and prompt version), so a changed text is a new key.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import FrozenModel

AnswerStatus = Literal["answered", "request_failed", "not_sent"]
JobStatus = Literal["completed", "partial", "unavailable", "not_configured"]


class MaterialAnswer(FrozenModel):
    """One position's answer. ``raw`` is the model's text (``answered`` only); ``error`` names
    the failure, never document content."""

    table_id: str
    row_id: str
    item_code: str | None = None
    status: AnswerStatus
    raw: str | None = Field(default=None, max_length=8000)
    error: str | None = Field(default=None, max_length=200)
    duration_ms: float | None = Field(default=None, ge=0)


class MaterialAnswers(FrozenModel):
    """The stored answers of one dataset and how the last request for them went."""

    dataset_id: str
    model: str | None = None
    model_licence: str | None = None
    prompt_version: str
    status: JobStatus
    detail: str
    answers: dict[str, MaterialAnswer] = Field(default_factory=dict)  # by key
