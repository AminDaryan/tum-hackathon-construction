"""The response models mirror the canonical models they summarize, so a field added to a
canonical model cannot silently go missing from the API."""

from __future__ import annotations

from app.models.dataset import Dataset
from app.models.document import Document
from app.models.issue import EvidenceClass
from app.models.run import ValidationRun
from app.schemas.datasets import DatasetSummary, WorkspaceCounts
from app.schemas.documents import DocumentInfo, DocumentSummary
from app.schemas.runs import ValidationRunDetail


def test_the_document_summary_is_the_document_without_its_storage_reference() -> None:
    canonical = [name for name in Document.model_fields if name != "source_file"]
    extra = ["size_bytes", "sha256", "dataset_id", "table_count", "row_count"]
    assert list(DocumentInfo.model_fields) == canonical + extra
    assert list(DocumentSummary.model_fields) == [*canonical, *extra, "last_run"]


def test_the_dataset_summary_is_the_dataset_with_summarized_tables() -> None:
    canonical = [name for name in Dataset.model_fields if name != "tables"]
    assert list(DatasetSummary.model_fields) == [*canonical, "tables", "required_fields_missing"]


def test_workspace_counts_have_one_field_per_evidence_class() -> None:
    classes = [evidence_class.value for evidence_class in EvidenceClass]
    assert list(WorkspaceCounts.model_fields) == ["total", *classes, "pending_review"]


def test_the_run_detail_is_the_canonical_run_plus_its_counts() -> None:
    assert list(ValidationRunDetail.model_fields) == [*ValidationRun.model_fields, "issue_counts"]
