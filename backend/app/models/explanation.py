"""Explanations: a local language model's account of one problem, stored with how it was made.

The model writes no numbers: its claims name slots such as ``{F1.unit_price}``, and the
workbench fills them in from the stored findings (``Claim.rendered``). A claim that cannot be
verified is kept out of the explanation and recorded in ``dropped`` with the reason. The record
keeps what is needed to judge and repeat the answer: provider, model and digest, server
version, prompt version, a digest of the input, and the prompt and raw output themselves, each
capped at :data:`MAX_TEXT_BYTES` (:func:`capped` shortens a text to fit).

Status: ``queued`` and ``running`` have no result yet; ``completed`` has its claims and a finish
time; ``failed`` has an ``error`` (fixed text, never document content) and a finish time.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.base import FrozenModel
from app.models.problem import PROBLEM_ID_PATTERN

MAX_TEXT_BYTES = 64 * 1024  # prompt and raw output, UTF-8 encoded
_TRUNCATED = "\n[truncated]"


def capped(text: str, limit: int = MAX_TEXT_BYTES) -> str:
    """``text`` if its UTF-8 encoding fits ``limit`` bytes; otherwise its longest prefix that
    fits together with a trailing ``[truncated]`` mark (never a split character)."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    mark = _TRUNCATED.encode("utf-8")
    if limit < len(mark):
        raise ValueError(f"limit must be at least {len(mark)} bytes")
    return data[: limit - len(mark)].decode("utf-8", errors="ignore") + _TRUNCATED


class ExplanationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Claim(FrozenModel):
    """One statement of an explanation. ``text`` is the model's sentence with its slots,
    ``rendered`` the sentence shown, with the stored values filled in, and ``cites`` the ids
    of the findings whose facts it uses."""

    section: Literal["summary", "next_check"]
    text: str = Field(min_length=1, max_length=4000)
    rendered: str = Field(min_length=1, max_length=8000)
    cites: list[str] = Field(default_factory=list)


class DroppedClaim(FrozenModel):
    """A statement the verification removed, and why (fixed text)."""

    text: str = Field(max_length=4000)
    reason: str = Field(min_length=1, max_length=500)


class Explanation(FrozenModel):
    explanation_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1)
    problem_id: str = Field(pattern=PROBLEM_ID_PATTERN)
    status: ExplanationStatus
    created_at: datetime
    finished_at: datetime | None = None
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    model_digest: str | None = Field(default=None, max_length=200)
    server_version: str | None = Field(default=None, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=64)
    input_digest: str = Field(min_length=1, max_length=128)
    claims: list[Claim] = Field(default_factory=list)
    dropped: list[DroppedClaim] = Field(default_factory=list)
    prompt: str | None = None
    raw_output: str | None = None
    error: str | None = Field(default=None, max_length=2000)
    duration_ms: int | None = Field(default=None, ge=0)

    @field_validator("prompt", "raw_output")
    @classmethod
    def _within_the_cap(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError(f"at most {MAX_TEXT_BYTES} bytes (UTF-8); shorten it with capped()")
        return value

    @model_validator(mode="after")
    def _status_fits(self) -> Explanation:
        finished = self.status in (ExplanationStatus.COMPLETED, ExplanationStatus.FAILED)
        if finished != (self.finished_at is not None):
            raise ValueError("finished_at is set exactly when the explanation is finished")
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise ValueError("finished_at cannot precede created_at")
        if (self.status is ExplanationStatus.FAILED) != (self.error is not None):
            raise ValueError("error is set exactly when the explanation failed")
        if not finished and (self.claims or self.dropped or self.raw_output is not None):
            raise ValueError("an unfinished explanation has no claims and no output yet")
        return self
