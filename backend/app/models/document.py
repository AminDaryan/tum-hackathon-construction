"""Uploaded documents and their stored originals."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.base import FrozenModel


class DocumentFormat(StrEnum):
    XLSX = "xlsx"
    CSV = "csv"
    # GAEB DA XML, one member per exchange phase (the file extension names the phase).
    GAEB_X81 = "gaeb_x81"
    GAEB_X83 = "gaeb_x83"
    GAEB_X84 = "gaeb_x84"
    GAEB_X86 = "gaeb_x86"
    # GAEB 90, the fixed-column predecessor of DA XML (.d81 ... .d86), one member per phase.
    GAEB_D81 = "gaeb_d81"
    GAEB_D83 = "gaeb_d83"
    GAEB_D84 = "gaeb_d84"
    GAEB_D86 = "gaeb_d86"
    # A printed bill of quantities, read from the PDF's text layer.
    PDF = "pdf"
    # A Word document (.docx): its tables, and a bill written as a list of item paragraphs.
    DOCX = "docx"
    # Planned adapters register new members here: XLS, IMAGE (OCR).


class ProcessingStatus(StrEnum):
    STORED = "stored"  # original saved, extraction not finished
    PROCESSED = "processed"  # canonical dataset created, extraction quality OK
    NEEDS_REVIEW = "needs_review"  # dataset created, but extraction warnings need a reviewer
    FAILED = "failed"  # stored, but extraction failed; see failure_reason


class StoredFile(FrozenModel):
    """Reference to the unchanged original in the file store (content-addressed)."""

    storage_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str


class AttachedModel(FrozenModel):
    """A building or infrastructure model (IFC) attached to a bill, with what its takeoff
    found when it was attached (``app.ingestion.ifc``)."""

    file: StoredFile
    filename: str  # sanitized display name
    schema_name: str  # FILE_SCHEMA, e.g. IFC4X3_ADD2
    project: str | None = None
    elements: int = Field(ge=0)
    unlinked_elements: int = Field(ge=0)
    linked_positions: int = Field(ge=0)


class Document(FrozenModel):
    document_id: str
    original_filename: str  # sanitized display name; never used to build a filesystem path
    format: DocumentFormat
    uploaded_at: datetime
    source_file: StoredFile
    processing_status: ProcessingStatus
    failure_reason: str | None = None
    profile_id: str
    model: AttachedModel | None = None  # an IFC whose quantities the bill is checked against
