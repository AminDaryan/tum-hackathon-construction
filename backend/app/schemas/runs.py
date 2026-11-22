"""Validation run responses.

:class:`ValidationRunDetail` is the one shape of a run: ``GET /validation-runs/{run_id}``, the
``201`` of a synchronous start and the ``202`` of a background start (``Prefer:
respond-async``, whose run is still ``queued`` or ``running``) all return it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.finding_category import FindingCategoryKey
from app.models.issue import EvidenceClass, ReviewStatus, Severity
from app.models.plan import PlannerKind
from app.models.run import DetectorExecutionStatus, RunReviewStatus, RunStatus, ValidationRun
from app.schemas.base import ResponseModel


class IssueCountsSummary(ResponseModel):
    total: int = Field(default=0, ge=0)
    by_evidence_class: dict[EvidenceClass, int] = Field(
        default_factory=dict, description="By effective evidence class."
    )
    by_severity: dict[Severity, int] = Field(default_factory=dict)
    by_review_status: dict[ReviewStatus, int] = Field(default_factory=dict)
    by_detector: dict[str, int] = Field(default_factory=dict)
    by_finding_category: dict[FindingCategoryKey, int] = Field(
        default_factory=dict,
        description=(
            "By finding category; `none` counts the findings without one: those about reading "
            "the file, and those of a detector the category tables do not know."
        ),
    )


class ValidationRunDetail(ValidationRun):
    """The canonical ``ValidationRun`` plus the counts of its findings."""

    issue_counts: IssueCountsSummary


class ValidationRunSummary(ResponseModel):
    run_id: str
    dataset_id: str
    dataset_revision: int = Field(ge=1)
    status: RunStatus
    review_status: RunReviewStatus
    review_finished_at: datetime | None
    started_at: datetime
    finished_at: datetime | None
    issue_count: int = Field(ge=0)
    planner: PlannerKind
    detectors: dict[DetectorExecutionStatus, int] = Field(
        description="How many detectors ended in each status."
    )


class ValidationRunList(ResponseModel):
    items: list[ValidationRunSummary] = Field(description="Newest first.")
