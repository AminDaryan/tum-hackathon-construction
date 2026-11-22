"""Validation runs: detail, the run's issues (filtered) and its exports."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.api.routes._deps import Offset, content_disposition, workbench
from app.exporters.xlsx_export import XLSX_MEDIA_TYPE
from app.models.finding_category import FindingCategoryKey
from app.models.issue import EvidenceClass, ReviewStatus, Severity
from app.schemas.exports import JsonExport
from app.schemas.issues import IssuePage
from app.schemas.runs import ValidationRunDetail
from app.services import exports, issues, problems, runs

router = APIRouter(tags=["validation runs"])
_EXPORT_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The export as an attachment (`Content-Disposition`): `issues.csv` is "
        "text/csv, `tables.zip` application/zip, `json` application/json, `xlsx` an Excel "
        "workbook (tables, issues, extraction report), and `questions.md` a Markdown "
        "questions document for findings in `needs_more_information`.",
        "model": JsonExport,
        "content": {
            "text/csv": {"schema": {"type": "string"}},
            "application/zip": {"schema": {"type": "string", "format": "binary"}},
            "text/markdown": {"schema": {"type": "string"}},
            XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


@router.get("/validation-runs/{run_id}")
def get_run(request: Request, run_id: str) -> ValidationRunDetail:
    return ValidationRunDetail.model_validate(runs.get(workbench(request), run_id))


@router.post("/validation-runs/{run_id}/review-finish")
def finish_review(request: Request, run_id: str) -> ValidationRunDetail:
    return ValidationRunDetail.model_validate(runs.finish_review(workbench(request), run_id))


@router.delete("/validation-runs/{run_id}/review-finish")
def reopen_review(request: Request, run_id: str) -> ValidationRunDetail:
    return ValidationRunDetail.model_validate(runs.reopen_review(workbench(request), run_id))


@router.get("/validation-runs/{run_id}/issues")
def list_issues(
    request: Request,
    run_id: str,
    severity: Annotated[list[Severity] | None, Query()] = None,
    evidence_class: Annotated[list[EvidenceClass] | None, Query()] = None,
    review_status: Annotated[list[ReviewStatus] | None, Query()] = None,
    detector_id: Annotated[list[str] | None, Query()] = None,
    category: Annotated[list[str] | None, Query()] = None,
    finding_category: Annotated[
        list[FindingCategoryKey] | None,
        Query(
            description=(
                "Finding category; `none` selects the findings without one: those about "
                "reading the file, and those of a detector the category tables do not know."
            )
        ),
    ] = None,
    table_id: str | None = None,
    row_id: str | None = None,
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> IssuePage:
    return issues.list_for_run(
        workbench(request),
        run_id,
        severities=severity or (),
        evidence_classes=evidence_class or (),
        review_statuses=review_status or (),
        detector_ids=detector_id or (),
        categories=category or (),
        finding_categories=finding_category or (),
        table_id=table_id,
        row_id=row_id,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/validation-runs/{run_id}/export/{format_id}",
    response_class=Response,
    responses=_EXPORT_RESPONSES,
)
def export_run(request: Request, run_id: str, format_id: str) -> Response:
    file = exports.export(workbench(request), run_id, format_id)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": content_disposition(file.filename)},
    )


@router.get("/validation-runs/{run_id}/problems")
def list_problems(request: Request, run_id: str) -> problems.ProblemList:
    """The run's findings joined into problems (same cell, same position, or the same difference
    carried into a total), the most money at stake first. Computed on request, never stored."""
    return problems.list_for_run(workbench(request), run_id)
