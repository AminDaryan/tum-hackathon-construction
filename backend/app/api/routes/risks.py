"""``/validation-runs/{run_id}/risks``: the ranked risk reminders of a finished run (risk grading,
:mod:`app.risk`), computed on request and never stored, and the stored discovery runs that a
report can apply. Reading or sorting a report never calls a model: the old ``model_review=true``
is refused with a migration note."""

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.api.routes._deps import content_disposition, workbench
from app.core.errors import InvalidInputError
from app.exporters.filenames import project_export_filename
from app.exporters.pdf_report import PDF_MEDIA_TYPE
from app.risk.bid_report import BidReport
from app.risk.bid_report_pdf import render as render_bid_report
from app.risk.models import DiscoveryRun, DiscoveryRunList, RiskReport, SortBy, SortOrder
from app.risk.service import (
    bid_report,
    discovery_run,
    discovery_runs,
    risk_report,
    start_discovery,
)
from app.services.jobs import prefers_respond_async
from app.services.risk_reviews import (
    RiskReview,
    RiskReviewList,
    RiskReviewRequest,
    list_risk_reviews,
    review_risk,
)

router = APIRouter(tags=["risks"])


class StartDiscovery(BaseModel):
    """``paths`` (default): known doubts, differing positions and an exploration sample;
    ``sample``: a stratified sample of the same size, the control. ``rerun``: start a new run
    even when one for the same inputs has finished."""

    strategy: Literal["paths", "sample"] = "paths"
    rerun: bool = False


@router.get("/validation-runs/{run_id}/risks")
def get_risks(
    request: Request,
    run_id: str,
    sort_by: SortBy = "priority",
    sort_order: SortOrder = "desc",
    discovery_run_id: Annotated[
        str | None,
        Query(description="Apply this stored discovery run (no model is called)."),
    ] = None,
    model_review: Annotated[
        bool,
        Query(
            deprecated=True,
            description="Removed: only false is accepted. Reading a report never calls a model; "
            "the model review of open reminders has no HTTP entry in this version.",
        ),
    ] = False,
    discovery: Annotated[
        str | None,
        Query(
            deprecated=True,
            description="Removed: only 'off' is accepted. Start discovery with POST "
            "/validation-runs/{run_id}/risks/discovery-runs and read it with discovery_run_id.",
        ),
    ] = None,
) -> RiskReport:
    """Reminders worth reviewing, with the bill's own text as evidence, the review priority and
    its basis, the money basis or "unknown", and a clarification question. ``sort_by``
    (``priority``, ``price_impact``, ``confidence``) and ``sort_order`` (``desc``, ``asc``)
    only reorder ``risks`` and ``record``, each on its own; ``priority_rank`` keeps the default
    position, ``rank`` is the displayed one. ``discovery_run_id`` applies a stored discovery run
    without calling a model (shown as ``outdated`` when its inputs changed)."""
    if model_review:
        raise InvalidInputError(
            "model_review=true is no longer accepted: reading or sorting a report never calls a "
            "model. Leave the parameter out for the same report without model hints. The model "
            "review of open reminders has no HTTP entry in this version. It is not discovery: to "
            "have the local model propose new hypotheses, start a discovery run with POST "
            f"/api/v1/validation-runs/{run_id}/risks/discovery-runs and pass the returned "
            "discovery_run_id."
        )
    if discovery not in (None, "off"):
        raise InvalidInputError(
            "Discovery no longer runs while a report is read: start it with POST "
            f"/api/v1/validation-runs/{run_id}/risks/discovery-runs and pass the returned "
            "discovery_run_id."
        )
    return risk_report(
        workbench(request),
        run_id,
        discovery_run_id=discovery_run_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/projects/{project_id}/risk-report")
def get_bid_report(
    request: Request,
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=100, description="Positions to list.")] = 20,
) -> BidReport:
    """The bid risk report of the project's last validation, to print and hand over: one row
    per position that a reminder names, the positions that drive price and risk first, each
    with its line total and its reminders' money. A reminder about more positions, or about a
    row that is not a position, is listed once below the rows. Computed on request from each
    bill's risk report; 409 before the project is validated or while it runs."""
    return bid_report(workbench(request), project_id, limit=limit)


@router.get(
    "/projects/{project_id}/risk-report/pdf",
    response_class=Response,
    responses={
        200: {
            "description": "The bid risk report as a PDF attachment (`Content-Disposition`), "
            "the same content and order as the JSON report.",
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def get_bid_report_pdf(
    request: Request,
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=100, description="Positions to list.")] = 20,
) -> Response:
    """The bid risk report of the project's last validation as a PDF to hand over; the same
    errors as the JSON report."""
    report = bid_report(workbench(request), project_id, limit=limit)
    filename = project_export_filename(report.project_name, "-bid-risk-report.pdf")
    return Response(
        content=render_bid_report(report),
        media_type=PDF_MEDIA_TYPE,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post(
    "/validation-runs/{run_id}/risks/discovery-runs",
    status_code=201,
    response_model=DiscoveryRun,
    responses={
        200: {
            "model": DiscoveryRun,
            "description": "A run for the same inputs already exists (queued, running, or "
            "finished without `rerun`): it is returned and nothing new is started.",
        },
        202: {
            "model": DiscoveryRun,
            "description": "Accepted for a background run (request header "
            "`Prefer: respond-async`): poll its Location until its status is finished or "
            "failed.",
            "headers": {
                "Location": {"description": "Path of the run.", "schema": {"type": "string"}},
                "Preference-Applied": {
                    "description": "`respond-async` (RFC 7240).",
                    "schema": {"type": "string"},
                },
            },
        },
    },
)
def start_risk_discovery(
    request: Request, run_id: str, body: Annotated[StartDiscovery | None, Body()] = None
) -> DiscoveryRun | JSONResponse:
    """Run budgeted discovery by the local model once and store its result, bound to the run's
    inputs. A second request for the same inputs returns the stored or running run."""
    wanted = body or StartDiscovery()
    background = prefers_respond_async(request.headers.getlist("prefer"))
    run, started = start_discovery(
        workbench(request), run_id, wanted.strategy, rerun=wanted.rerun, background=background
    )
    location = request.url_for(
        "get_risk_discovery_run", run_id=run_id, discovery_run_id=run.discovery_run_id
    ).path
    headers = {"Location": location}
    code = 200
    if started:
        code = 202 if background else 201
        if background:
            headers["Preference-Applied"] = "respond-async"
    return JSONResponse(content=run.model_dump(mode="json"), status_code=code, headers=headers)


@router.get("/validation-runs/{run_id}/risks/discovery-runs")
def list_risk_discovery_runs(request: Request, run_id: str) -> DiscoveryRunList:
    """The stored discovery runs of a validation run, newest first."""
    return discovery_runs(workbench(request), run_id)


@router.get("/validation-runs/{run_id}/risks/discovery-runs/{discovery_run_id}")
def get_risk_discovery_run(request: Request, run_id: str, discovery_run_id: str) -> DiscoveryRun:
    """One stored discovery run: its status, every checked hypothesis and rejection with its
    reason, each request as sent with the raw answer, the times and the inputs it is bound to.
    Reading it never calls a model."""
    return discovery_run(workbench(request), run_id, discovery_run_id)


@router.get("/validation-runs/{run_id}/risk-reviews")
def get_risk_reviews(request: Request, run_id: str) -> RiskReviewList:
    """The latest decision on each reminder without a finding in the run's document. Reminders
    with findings are decided through their findings (``PATCH /issues/{issue_id}/review``)."""
    return list_risk_reviews(workbench(request), run_id)


@router.put("/validation-runs/{run_id}/risk-reviews/{risk_id}")
def put_risk_review(
    request: Request, run_id: str, risk_id: str, body: RiskReviewRequest
) -> RiskReview:
    """Record a decision (``open``, ``in_review``, ``approved``, ``rejected``) on a reminder
    without a finding. It is kept in the audit trail and carries over to later runs of the
    same document; ``open`` takes it back."""
    return review_risk(workbench(request), run_id, risk_id, body)
