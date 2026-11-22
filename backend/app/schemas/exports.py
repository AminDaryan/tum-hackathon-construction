"""The JSON export (``GET /validation-runs/{run_id}/export/json``), described for the API docs.

``app.exporters.json_export`` writes the file; ``tests/unit/api/test_schemas.py`` checks that
an export validates against :class:`JsonExport`, so this description cannot drift from it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.dataset import Dataset
from app.models.issue import ValidationIssue
from app.models.run import ValidationRun
from app.schemas.base import ResponseModel
from app.schemas.documents import DocumentInfo
from app.validation.contracts.detector import DetectorSpec


class ExportedProfile(ResponseModel):
    profile_id: str
    version: str | None


class ExportHeader(ResponseModel):
    format: Literal["tabular-integrity-workbench/json"]
    format_version: int = Field(ge=1)
    generated_at: datetime
    validation_run_id: str
    dataset_id: str
    dataset_revision: int = Field(ge=1)
    document: DocumentInfo
    profile: ExportedProfile


class JsonExport(ResponseModel):
    export: ExportHeader
    dataset: Dataset = Field(description="The dataset revision the run checked, with its rows.")
    validation_run: ValidationRun
    detectors: list[DetectorSpec]
    issues: list[ValidationIssue]
