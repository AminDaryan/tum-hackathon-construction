"""Document responses: the document summary, the document list and the document detail."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.document import DocumentFormat, ProcessingStatus
from app.models.run import RunStatus
from app.schemas.base import Page, ResponseModel
from app.schemas.datasets import DatasetSummary


class ModelInfo(ResponseModel):
    """The model (IFC) attached to a bill: its quantities are compared with the bill's."""

    filename: str
    sha256: str
    size_bytes: int = Field(ge=0)
    schema_name: str = Field(description="IFC schema, e.g. IFC4X3_ADD2.")
    project: str | None
    elements: int = Field(ge=0)
    unlinked_elements: int = Field(
        ge=0, description="Elements without a link to a bill position (item number)."
    )
    linked_positions: int = Field(ge=0, description="Item numbers the model's elements name.")


class DocumentInfo(ResponseModel):
    """The canonical ``Document`` without its storage reference, plus the stored file's size
    and digest and the counts of its latest dataset (as the JSON export describes it)."""

    document_id: str
    original_filename: str = Field(description="Sanitized display name.")
    format: DocumentFormat
    uploaded_at: datetime
    processing_status: ProcessingStatus
    failure_reason: str | None
    profile_id: str
    model: ModelInfo | None = Field(
        default=None, description="The attached model (IFC); null when none is attached."
    )
    size_bytes: int = Field(ge=0)
    sha256: str
    dataset_id: str | None
    table_count: int = Field(ge=0)
    row_count: int = Field(ge=0)


class LastRunSummary(ResponseModel):
    run_id: str
    status: RunStatus
    finished_at: datetime | None
    issue_count: int = Field(ge=0)


class DocumentSummary(DocumentInfo):
    last_run: LastRunSummary | None = Field(description="Null until a validation run exists.")


class DocumentPage(Page[DocumentSummary]):
    """Documents, newest first."""


class DocumentDetail(ResponseModel):
    document: DocumentSummary
    dataset: DatasetSummary | None = Field(
        description="The latest dataset; null when the extraction failed."
    )
