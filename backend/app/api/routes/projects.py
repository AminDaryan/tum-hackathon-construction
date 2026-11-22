"""Projects reuse the existing document upload, review and validation contracts."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes._deps import content_disposition, workbench
from app.models.issue import ReviewStatus
from app.models.project import (
    MAX_ASSIGNEES,
    Project,
    ProjectReport,
    ProjectStatus,
    ReportFormat,
    ReviewerName,
)
from app.repositories.base import IssueQuery
from app.schemas.documents import DocumentSummary
from app.schemas.issues import IssueView
from app.services import exports, issues, projects

router = APIRouter(tags=["projects"])


class CreateProject(BaseModel):
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")
    description: str = Field(default="", max_length=2000)
    assignees: list[ReviewerName] = Field(default_factory=list, max_length=MAX_ASSIGNEES)


class UpdateProject(BaseModel):
    """The details to change; a field left out stays as it is."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"\S")
    description: str | None = Field(default=None, max_length=2000)
    assignees: list[ReviewerName] | None = Field(default=None, max_length=MAX_ASSIGNEES)
    status: ProjectStatus | None = None
    decision_cutoff: date | None = None  # the only field that null clears


class ProjectMember(BaseModel):
    document_id: str
    role: Literal["bill", "reference"] = "bill"


class ProjectFileGroup(BaseModel):
    group: Literal["bill", "support"]


class ProjectReviewCounts(BaseModel):
    """The findings of one bill in the project's validation: those still to review, the high or
    critical ones among them, all of them (``findings``), decided or not, and all of them by
    priority (``by_severity``)."""

    to_review: int
    high_priority: int
    findings: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)


class TopIssues(BaseModel):
    items: list[IssueView]
    total: int


class NewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: ReportFormat
    document_id: str | None = None  # a bill of the last validation; null for the whole project


class ReportList(BaseModel):
    items: list[ProjectReport]  # newest first


class ProjectDetail(BaseModel):
    project: Project
    documents: list[DocumentSummary]
    review_counts: dict[str, ProjectReviewCounts]
    # Each file's group: "bill" (table view, validated) or "support" (opened as the document).
    groups: dict[str, Literal["bill", "support"]]


@router.get("/projects")
def list_projects(request: Request) -> list[Project]:
    with workbench(request).uow() as uow:
        return uow.projects.list()


@router.post("/projects", status_code=201)
def create_project(request: Request, body: CreateProject) -> Project:
    return projects.create(
        workbench(request), body.name.strip(), body.description.strip(), body.assignees
    )


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> ProjectDetail:
    wb = workbench(request)
    with wb.uow() as uow:
        project = projects.load(uow, project_id)
        review_counts = {}
        for document_id, run_id in (project.validation.runs if project.validation else {}).items():
            counts = uow.issues.counts(
                IssueQuery(run_id=run_id, review_statuses=frozenset({ReviewStatus.PENDING_REVIEW}))
            )
            every = uow.issues.counts(IssueQuery(run_id=run_id))
            review_counts[document_id] = ProjectReviewCounts(
                to_review=counts.total,
                high_priority=counts.by_severity.get("high", 0)
                + counts.by_severity.get("critical", 0),
                findings=every.total,
                by_severity=dict(every.by_severity),
            )
    docs = projects.summaries(wb, project)
    return ProjectDetail(
        project=project,
        documents=docs,
        review_counts=review_counts,
        groups=projects.groups(project, docs),
    )


@router.patch("/projects/{project_id}")
def update_project(request: Request, project_id: str, body: UpdateProject) -> Project:
    """Rename the project, change its description or assigned users, mark it finished
    (``status``: ``in_progress`` or ``finished``), or set the day of the bid decision
    (``decision_cutoff``; null clears it)."""
    changes = {
        field: value.strip() if isinstance(value, str) and field != "status" else value
        for field, value in body.model_dump(exclude_unset=True).items()
        if value is not None or field == "decision_cutoff"
    }
    return projects.update(workbench(request), project_id, changes)


@router.put("/projects/{project_id}/documents")
def add_document(request: Request, project_id: str, body: ProjectMember) -> Project:
    """Add a file to the project. Its bills are checked again where this changes their inputs
    (a bid is compared with the tender in its project)."""
    wb = workbench(request)
    project = projects.membership(wb, project_id, body.document_id, role=body.role)
    projects.check_bills_soon(wb, project, body.document_id)
    return project


@router.patch("/projects/{project_id}/documents/{document_id}")
def move_document(
    request: Request, project_id: str, document_id: str, body: ProjectFileGroup
) -> Project:
    """Put a file among the project's bills or its supporting documents."""
    wb = workbench(request)
    project = projects.move(wb, project_id, document_id, body.group)
    projects.check_bills_soon(wb, project, document_id)
    return project


@router.delete("/projects/{project_id}/documents/{document_id}")
def remove_document(request: Request, project_id: str, document_id: str) -> Project:
    wb = workbench(request)
    project = projects.membership(wb, project_id, document_id, remove=True)
    projects.check_bills_soon(wb, project, document_id)
    return project


@router.post("/projects/{project_id}/validation", status_code=202)
def validate_project(request: Request, project_id: str) -> Project:
    return projects.start(workbench(request), project_id)


@router.get(
    "/projects/{project_id}/export/{format_id}",
    response_class=Response,
    responses={
        200: {
            "description": "The findings of every bill in the project's last validation, as an "
            "attachment (`Content-Disposition`): `pdf` a findings report, one section per bill; "
            "`xlsx` an Excel workbook with one Issues sheet and a File column; `issues.csv` the "
            "issue register with a leading `file` column.",
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            },
        },
    },
)
def export_project(request: Request, project_id: str, format_id: str) -> Response:
    file = exports.export_project(workbench(request), project_id, format_id)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": content_disposition(file.filename)},
    )


@router.get("/projects/{project_id}/top-issues")
def top_issues(
    request: Request,
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=100, description="Findings to list.")] = 5,
    offset: Annotated[int, Query(ge=0, description="Findings to skip.")] = 0,
) -> TopIssues:
    """A page of the findings still to review over every bill of the project's last
    validation, and how many there are: the most severe first, then the largest financial
    impact (by size). 409 before the project is validated or while it runs."""
    items, total = issues.top_for_project(
        workbench(request), project_id, limit=limit, offset=offset
    )
    return TopIssues(items=items, total=total)


@router.get("/projects/{project_id}/reports")
def list_reports(request: Request, project_id: str) -> ReportList:
    """The reports generated for the project, newest first."""
    with workbench(request).uow() as uow:
        project = projects.load(uow, project_id)
    return ReportList(items=list(reversed(project.reports)))


@router.post("/projects/{project_id}/reports", status_code=201)
def create_report(request: Request, project_id: str, body: NewReport) -> ProjectReport:
    """Generate a report on the findings of the project's last validation, of every bill or of
    one (``document_id``), and keep it: ``pdf`` a findings report, ``xlsx`` an Excel workbook,
    ``issues.csv`` the issue register, ``bid-risk.pdf`` the bid risk report (the whole project
    only; 422 with a ``document_id``). 409 before the project is validated; 404 for a bill not
    in that validation."""
    return exports.create_report(workbench(request), project_id, body.format, body.document_id)


@router.get(
    "/projects/{project_id}/reports/{report_id}/file",
    response_class=Response,
    responses={
        200: {
            "description": "The report's file, as an attachment (`Content-Disposition`).",
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            },
        },
    },
)
def report_file(request: Request, project_id: str, report_id: str) -> Response:
    file = exports.report_file(workbench(request), project_id, report_id)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": content_disposition(file.filename)},
    )
