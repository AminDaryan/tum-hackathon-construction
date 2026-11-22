"""Issues: one finding with its history, and review decisions."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes._deps import workbench
from app.models.issue import ReviewStatus
from app.schemas.issues import IssueCorrectionResult, IssueDetail
from app.services import issues

router = APIRouter(tags=["issues"])


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus
    comment: str | None = Field(default=None, max_length=4000)
    expected_version: int = Field(ge=1)


class CorrectedCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str
    row_id: str
    column_id: str
    value: str | None = Field(default=None, max_length=4000)


class CorrectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cells: list[CorrectedCell] = Field(min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=4000)
    expected_version: int = Field(ge=1)
    rerun_validation: bool = True


@router.get("/issues/{issue_id}")
def get_issue(request: Request, issue_id: str) -> IssueDetail:
    return issues.get(workbench(request), issue_id)


@router.post("/issues/{issue_id}/review")
def review_issue(request: Request, issue_id: str, decision: ReviewDecision) -> IssueDetail:
    return issues.review(
        workbench(request),
        issue_id,
        status=decision.status,
        comment=decision.comment,
        expected_version=decision.expected_version,
    )


@router.post("/issues/{issue_id}/corrections")
def correct_issue(
    request: Request, issue_id: str, decision: CorrectionDecision
) -> IssueCorrectionResult:
    return issues.correct(
        workbench(request),
        issue_id,
        cells=[
            issues.CellCorrectionInput(
                table_id=cell.table_id,
                row_id=cell.row_id,
                column_id=cell.column_id,
                value=cell.value,
            )
            for cell in decision.cells
        ],
        comment=decision.comment,
        expected_version=decision.expected_version,
        rerun_validation=decision.rerun_validation,
    )
