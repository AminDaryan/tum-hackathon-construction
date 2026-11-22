"""A bid's shared documents and the latest project-wide validation."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from app.models.base import FrozenModel

# The rule of the reviewer names people sign in with (collaboration), so an assigned user can
# sign in under the same name and be @mentioned.
ReviewerName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
]
ProjectStatus = Literal["in_progress", "finished"]
# The findings as a PDF, Excel or CSV file, or the bid risk report (whole project only) as a PDF.
ReportFormat = Literal["pdf", "xlsx", "issues.csv", "bid-risk.pdf"]
MAX_ASSIGNEES = 20


FileGroup = Literal["bill", "support"]


class ProjectFile(FrozenModel):
    document_id: str
    role: Literal["bill", "reference"] = "bill"
    # Where a person put the file: "bill" (the table view) or "support" (drawings, reports,
    # specs, opened as the document itself). None: decided by ``projects.group_of``.
    group: FileGroup | None = None


class ProjectCheck(FrozenModel):
    item_code: str
    field: str
    documents: list[str]
    values: list[str]
    note: str = "Different source values; verify scope and revision before treating as an error."


class ProjectValidation(FrozenModel):
    status: Literal["running", "completed", "failed"] = "running"
    started_at: datetime
    finished_at: datetime | None = None
    runs: dict[str, str] = Field(default_factory=dict)
    skipped: dict[str, str] = Field(default_factory=dict)
    comparisons: list[ProjectCheck] = Field(default_factory=list)
    error: str | None = None


class ProjectReport(FrozenModel):
    """A report generated on the Reports page: the findings of the project's last validation
    (``document_id`` null) or of one of its bills, as a file kept in the file store."""

    report_id: str
    created_at: datetime
    format: ReportFormat
    document_id: str | None = None
    filename: str
    media_type: str
    size_bytes: int = Field(ge=0)
    storage_key: str
    validated_at: datetime | None = None  # when the validation it reports on finished


class Project(FrozenModel):
    project_id: str
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    created_at: datetime
    status: ProjectStatus = "in_progress"
    assignees: list[ReviewerName] = Field(default_factory=list, max_length=MAX_ASSIGNEES)
    decision_cutoff: date | None = None  # the day the bid decision is made, set by hand
    files: list[ProjectFile] = Field(default_factory=list)
    demo_key: str | None = None
    preparation: Literal["ready", "preparing", "failed"] = "ready"
    preparation_error: str | None = None
    validation: ProjectValidation | None = None
    reports: list[ProjectReport] = Field(default_factory=list)  # oldest first

    @field_validator("assignees")
    @classmethod
    def _unique_assignees(cls, names: list[str]) -> list[str]:
        """One entry per person: names that differ only in case are the same reviewer."""
        seen: set[str] = set()
        unique = []
        for name in names:
            if name.casefold() not in seen:
                seen.add(name.casefold())
                unique.append(name)
        return unique
