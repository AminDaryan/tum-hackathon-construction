"""Dataset responses: the dataset summary, pages of canonical rows and the workspace summary."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.dataset import (
    Column,
    ExtractionQuality,
    ExtractionReport,
    HeaderDetection,
    Row,
    RowKind,
)
from app.models.plan import PlannerKind
from app.models.run import RunReviewStatus, RunStatus
from app.models.source import SourceLocation
from app.schemas.base import Page, ResponseModel


class TableSummary(ResponseModel):
    """A canonical table without its rows."""

    table_id: str
    name: str
    source: SourceLocation
    header: HeaderDetection
    row_count: int = Field(ge=0)
    row_kind_counts: dict[RowKind, int]
    columns: list[Column]


class DatasetSummary(ResponseModel):
    """Everything about a dataset except its rows (the canonical ``Dataset`` with tables
    summarized), plus the required profile fields that no column of a table is mapped to."""

    dataset_id: str
    document_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    profile_id: str
    profile_version: str
    created_at: datetime
    extraction: ExtractionReport
    tables: list[TableSummary]
    required_fields_missing: dict[str, list[str]] = Field(
        description="Table id -> required profile fields without a mapped column."
    )


class RowPage(Page[Row]):
    """Canonical rows of one table, in source order."""


class CorrectionsResult(ResponseModel):
    """The dataset's revision after a correction request, and the rows it changed (in full).
    ``changed`` is 0 and the revision unchanged when every cell already had the given text."""

    dataset_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    changed: int = Field(ge=0, description="Cells whose text changed.")
    rows: list[Row] = Field(description="The changed rows of the new revision, in table order.")


class WorkspaceRun(ResponseModel):
    run_id: str
    status: RunStatus
    review_status: RunReviewStatus
    review_finished_at: datetime | None
    started_at: datetime
    planner: PlannerKind
    finished_at: datetime | None


class WorkspaceCounts(ResponseModel):
    """Finding counts of the run by *effective* evidence class (one field per
    ``EvidenceClass``), and the findings still pending review."""

    total: int = Field(ge=0)
    confirmed_rule_violation: int = Field(ge=0)
    suspected_anomaly: int = Field(ge=0)
    semantic_warning: int = Field(ge=0)
    extraction_uncertainty: int = Field(ge=0)
    needs_external_context: int = Field(ge=0)
    human_confirmed_error: int = Field(ge=0)
    pending_review: int = Field(ge=0)


class WorkspaceSummary(ResponseModel):
    dataset_id: str
    document_id: str
    revision: int = Field(ge=1)
    table_count: int = Field(ge=0)
    rows_processed: int = Field(ge=0)
    item_rows: int = Field(ge=0)
    columns_total: int = Field(ge=0)
    columns_mapped: int = Field(ge=0)
    required_fields_missing: list[str]
    extraction_quality: ExtractionQuality
    extraction_warning_count: int = Field(ge=0)
    run: WorkspaceRun | None = Field(description="The chosen or latest run; null before the first.")
    counts: WorkspaceCounts
