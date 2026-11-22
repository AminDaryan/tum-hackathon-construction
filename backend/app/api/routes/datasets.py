"""Datasets: summary, rows, workspace summary, and the validation runs started on a dataset."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes._deps import Offset, content_disposition, workbench
from app.exporters.xlsx_export import XLSX_MEDIA_TYPE
from app.normalization.revise import CellCorrection
from app.schemas.datasets import CorrectionsResult, DatasetSummary, RowPage, WorkspaceSummary
from app.schemas.runs import ValidationRunDetail, ValidationRunList
from app.services import datasets, exports, runs
from app.services.jobs import prefers_respond_async

router = APIRouter(tags=["datasets"])


class CellCorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str = Field(max_length=200)
    row_id: str = Field(max_length=200)
    column_id: str = Field(max_length=200)
    raw_value: str = Field(max_length=32767, description="The new text; empty clears the cell.")


class StartRun(BaseModel):
    """``match_materials``: before the checks, ask the local model to suggest a product of the
    price reference for priced rows its keywords cannot match
    (``statistical.open_price_reference``).
    Without it, a run uses the answers stored earlier and calls no model. ``bill_review``:
    before the checks, send the bill to Claude for review (``llm.bill_review`` lists its
    claims); only on a server set up for it (``bill_review_available`` of ``/health``), else
    409 ``conflict``. Without it, a run lists the claims stored earlier and calls no model.
    Other fields (a ``plan``) are ignored as before: clients cannot choose checks."""

    match_materials: bool = False
    bill_review: bool = False


class CorrectionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1, description="The revision the change was made on.")
    corrections: list[CellCorrectionIn] = Field(min_length=1, max_length=200)


@router.get("/datasets/{dataset_id}")
def get_dataset(request: Request, dataset_id: str) -> DatasetSummary:
    return datasets.summary(workbench(request), dataset_id)


@router.get("/datasets/{dataset_id}/tables/{table_id}/rows")
def get_rows(
    request: Request,
    dataset_id: str,
    table_id: str,
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    row_id: Annotated[
        str | None,
        Query(max_length=200, description="Return the page that holds this row (offset ignored)."),
    ] = None,
) -> RowPage:
    return datasets.rows(
        workbench(request), dataset_id, table_id, offset=offset, limit=limit, row_id=row_id
    )


@router.post("/datasets/{dataset_id}/corrections")
def correct_cells(request: Request, dataset_id: str, body: CorrectionsRequest) -> CorrectionsResult:
    """Store corrected cell texts as the dataset's next revision (the uploaded file is never
    changed); 409 ``conflict`` when ``expected_revision`` is not the latest revision."""
    corrections = [
        CellCorrection(c.table_id, c.row_id, c.column_id, c.raw_value) for c in body.corrections
    ]
    return datasets.correct(
        workbench(request),
        dataset_id,
        expected_revision=body.expected_revision,
        corrections=corrections,
    )


@router.get("/datasets/{dataset_id}/summary")
def get_summary(request: Request, dataset_id: str, run_id: str | None = None) -> WorkspaceSummary:
    return datasets.workspace_summary(workbench(request), dataset_id, run_id)


@router.get(
    "/datasets/{dataset_id}/export/xlsx",
    response_class=Response,
    responses={
        200: {
            "description": "The extracted tables as an Excel workbook (attachment): one sheet "
            "per table and an Extraction sheet with the document, format and warnings.",
            "content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def export_dataset(request: Request, dataset_id: str) -> Response:
    file = exports.export_dataset(workbench(request), dataset_id)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": content_disposition(file.filename)},
    )


@router.post(
    "/datasets/{dataset_id}/validation-runs",
    status_code=201,
    response_model=ValidationRunDetail,
    responses={
        202: {
            "model": ValidationRunDetail,
            "description": "Accepted for a background run (request header "
            "`Prefer: respond-async`): the run is queued; poll its Location until it ends.",
            "headers": {
                "Location": {
                    "description": "Path of the run (GET /validation-runs/{run_id}).",
                    "schema": {"type": "string"},
                },
                "Preference-Applied": {
                    "description": "`respond-async` (RFC 7240).",
                    "schema": {"type": "string"},
                },
            },
        }
    },
)
def start_run(
    request: Request, dataset_id: str, body: Annotated[StartRun | None, Body()] = None
) -> ValidationRunDetail | JSONResponse:
    """Run every registered check on the dataset (ADR 0010); clients cannot choose checks.
    ``match_materials`` first asks the local model to suggest price-reference products for the
    rows the keywords cannot match (stored, then used by every later run without asking).
    ``bill_review`` first sends the bill to Claude for review (stored the same way); 409
    ``conflict`` when the server is not set up for it."""
    match = bool(body and body.match_materials)
    review = bool(body and body.bill_review)
    if prefers_respond_async(request.headers.getlist("prefer")):  # K3: 202, then poll the run
        queued = ValidationRunDetail.model_validate(
            runs.start_in_background(
                workbench(request), dataset_id, match_materials=match, bill_review=review
            )
        )
        location = request.url_for("get_run", run_id=queued.run_id).path
        headers = {"Location": location, "Preference-Applied": "respond-async"}
        content = queued.model_dump(mode="json", by_alias=True)
        return JSONResponse(content=content, status_code=202, headers=headers)
    return ValidationRunDetail.model_validate(
        runs.start(workbench(request), dataset_id, match_materials=match, bill_review=review)
    )


@router.get("/datasets/{dataset_id}/validation-runs")
def list_runs(request: Request, dataset_id: str) -> ValidationRunList:
    return ValidationRunList.model_validate(runs.list_for_dataset(workbench(request), dataset_id))
