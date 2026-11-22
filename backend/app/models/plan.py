"""Validation plans: which registered detectors run, with which parameters, in which order.

A plan is data, never code. Plans come from the baseline planner (no LLM), from a user, or, in a
later phase, from an LLM planner. Every plan is validated against the detector registry before
execution (unknown detector ids, unknown or invalid parameters and oversized plans are rejected).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, StringConstraints

from app.models.base import FrozenModel

DETECTOR_ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"

# Free text in plans is bounded: an adaptive (LLM) planner reads untrusted documents, so its
# prose must not be able to flood reviewers or exports. The UI labels planner text by source.
PlanText = Annotated[str, StringConstraints(max_length=1000)]


class PlannerKind(StrEnum):
    BASELINE = "baseline"  # deterministic fallback planner, always available
    USER = "user"
    LLM = "llm"


class PlanStep(FrozenModel):
    detector_id: str = Field(pattern=DETECTOR_ID_PATTERN, max_length=128)
    config: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = Field(default=None, max_length=2000)


class SkippedCheck(FrozenModel):
    detector_id: str = Field(max_length=128)
    reasons: list[PlanText] = Field(max_length=20)


class ValidationPlan(FrozenModel):
    """``planner`` records which code path produced the plan. It is set by the server, never
    taken from a client: a plan received over the API is always ``user``."""

    planner: PlannerKind
    planner_detail: PlanText | None = None
    steps: list[PlanStep] = Field(max_length=256)
    skipped_checks: list[SkippedCheck] = Field(default_factory=list, max_length=256)
    missing_information: list[PlanText] = Field(default_factory=list, max_length=50)
    human_review_requirements: list[PlanText] = Field(default_factory=list, max_length=50)
    notes: list[PlanText] = Field(default_factory=list, max_length=50)
