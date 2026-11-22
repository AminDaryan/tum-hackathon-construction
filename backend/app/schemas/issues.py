"""Issue responses: pages of a run's findings and one finding with its history."""

from __future__ import annotations

from pydantic import Field

from app.models.audit import AuditEvent
from app.models.issue import ReviewStatus, ValidationIssue
from app.models.values import DataType, ParseStatus
from app.schemas.base import Page, ResponseModel
from app.schemas.datasets import DatasetSummary
from app.schemas.runs import ValidationRunDetail


class IssueView(ValidationIssue):
    """The canonical ``ValidationIssue`` as the API returns it: with the review statuses that a
    plain review decision may set from its current ``review_status``."""

    allowed_review_actions: list[ReviewStatus] = Field(
        description="Sorted; empty when no review decision is possible. Computed from "
        "ALLOWED_REVIEW_TRANSITIONS and REVIEW_DECISION_TARGETS (app/models/issue.py)."
    )


class IssuePage(Page[IssueView]):
    """Findings ordered by severity (critical first), table, source row and issue id."""


class IssueDetail(ResponseModel):
    issue: IssueView
    history: list[AuditEvent]


class CorrectedCell(ResponseModel):
    table_id: str
    row_id: str
    column_id: str
    previous_raw_value: str | None
    corrected_raw_value: str | None
    previous_data_type: DataType
    corrected_data_type: DataType
    previous_parse_status: ParseStatus
    corrected_parse_status: ParseStatus


class IssueCorrectionResult(ResponseModel):
    issue: IssueView
    history: list[AuditEvent]
    dataset: DatasetSummary
    validation_run: ValidationRunDetail | None
    corrected_cells: list[CorrectedCell] = Field(default_factory=list)
