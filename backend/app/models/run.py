"""Validation runs and per-detector execution reports."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from app.models.base import FrozenModel
from app.models.plan import ValidationPlan


class RunStatus(StrEnum):
    QUEUED = "queued"  # started in the background (Prefer: respond-async), waiting for a worker
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # at least one detector failed
    FAILED = "failed"  # the run itself could not execute


class RunReviewStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class DetectorExecutionStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"  # not applicable to this dataset; see skipped_reasons
    FAILED = "failed"  # raised an error; other detectors still ran
    STOPPED = "stopped"  # stopped by its time limit; the findings made so far are kept


class DetectorRunReport(FrozenModel):
    detector_id: str
    detector_version: str
    status: DetectorExecutionStatus
    config: dict[str, Any] = Field(default_factory=dict)  # effective, validated parameters
    rationale: str | None = None
    issues_found: int = Field(default=0, ge=0)
    issues_dropped: int = Field(default=0, ge=0)  # over the per-detector cap; never silent
    duration_ms: float = Field(default=0.0, ge=0)
    skipped_reasons: list[str] = Field(default_factory=list)
    # Set when a run limit stopped the detector early: "issues" (finding cap) or "time".
    limit_reached: Literal["issues", "time"] | None = None
    # Sanitized: exception type and a reference to the server log, never document content.
    error: str | None = None
    notes: list[str] = Field(default_factory=list)
    coverage: dict[str, int] = Field(default_factory=dict)


class ValidationRun(FrozenModel):
    run_id: str
    document_id: str
    dataset_id: str
    dataset_revision: int = Field(ge=1)
    profile_id: str
    profile_version: str | None = None  # the profile version the run validated against
    status: RunStatus
    plan: ValidationPlan
    started_at: datetime
    finished_at: datetime | None = None
    detector_reports: list[DetectorRunReport] = Field(default_factory=list)
    issue_count: int = Field(default=0, ge=0)
    review_status: RunReviewStatus = RunReviewStatus.IN_PROGRESS
    review_finished_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    # A digest of what the run checked (revision, profile, plan, detector versions, attached
    # model, material answers): a new run with the same inputs reuses this one instead.
    inputs_digest: str | None = None

    @model_validator(mode="after")
    def _review_marker_matches_status(self) -> ValidationRun:
        finished_marker = self.review_finished_at is not None
        finished_status = self.review_status is RunReviewStatus.FINISHED
        if finished_marker == finished_status:
            return self
        raise ValueError("review_finished_at must be set exactly when review_status is 'finished'")
