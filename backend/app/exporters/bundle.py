"""What every exporter receives (:class:`ExportBundle`), what every exporter provides
(:class:`Exporter`), and the registry that maps a format id to its exporter.

Adding a format (XLSX review workbook, PDF report in Phase 2) means one new module with an
exporter class and one ``register_exporter(...)`` line in ``app/exporters/__init__.py``; the
API looks exporters up by format id (``get_exporter``) and does not change. Exporter modules
import from this module, never from the ``app.exporters`` package, so registration cannot
create an import cycle.

Exporters are pure functions of the bundle: no I/O, no clock, no randomness. The same bundle
(including ``generated_at``) always produces byte-identical output.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.core.errors import NotFoundError
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.issue import ValidationIssue
from app.models.run import ValidationRun
from app.validation.contracts.detector import DetectorSpec

# A format id is also a URL path segment (``/validation-runs/{run_id}/export/{format_id}``).
FORMAT_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")


def utc_timestamp(value: datetime) -> str:
    """ISO 8601 in UTC with a ``Z`` suffix, as the API and the models write timestamps."""
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ExportBundle:
    """One validation run with everything its exports show.

    Checked on construction so an export can never name a run, dataset revision or document
    other than the one its content comes from: the run, the dataset revision and every issue
    must belong together, and every issue's table and row must exist in the dataset.
    ``issues`` keeps the given order (the API passes the issue register order); it is stored
    as a tuple. ``generated_at`` must be timezone-aware and is stored in UTC.
    """

    document: Document
    dataset: Dataset
    run: ValidationRun
    issues: Sequence[ValidationIssue]
    detectors: Sequence[DetectorSpec]
    generated_at: datetime

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        object.__setattr__(self, "generated_at", self.generated_at.astimezone(UTC))
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "detectors", tuple(self.detectors))
        self._check_links()

    def _check_links(self) -> None:
        document_id = self.document.document_id
        dataset, run = self.dataset, self.run
        if dataset.document_id != document_id or run.document_id != document_id:
            raise ValueError("the dataset and the run must belong to the document")
        if (run.dataset_id, run.dataset_revision) != (dataset.dataset_id, dataset.revision):
            raise ValueError("the run must have validated this dataset revision")
        tables = {table.table_id: table for table in dataset.tables}
        for issue in self.issues:
            identity = (issue.validation_run_id, issue.document_id, issue.dataset_id)
            if identity != (run.run_id, document_id, dataset.dataset_id):
                raise ValueError(f"issue {issue.issue_id!r} does not belong to this run")
            if issue.dataset_revision != dataset.revision:
                raise ValueError(f"issue {issue.issue_id!r} examined another dataset revision")
            if issue.table_id is None:
                continue
            table = tables.get(issue.table_id)
            if table is None or (issue.row_id is not None and not table.has_row(issue.row_id)):
                raise ValueError(f"issue {issue.issue_id!r} points outside the dataset")

    @property
    def generated_at_text(self) -> str:
        """``generated_at`` as written into exports (ISO 8601, UTC)."""
        return utc_timestamp(self.generated_at)


class Exporter(Protocol):
    """An export format. ``format_id`` is the URL segment of the export endpoint,
    ``media_type`` the response content type, and ``filename_suffix`` what
    :func:`app.exporters.filenames.export_filename` appends to ``<stem> <run start>``."""

    @property
    def format_id(self) -> str: ...

    @property
    def media_type(self) -> str: ...

    @property
    def filename_suffix(self) -> str: ...

    def export(self, bundle: ExportBundle) -> bytes:
        """The complete file content."""
        ...


EXPORTERS: dict[str, Exporter] = {}


def register_exporter(exporter: Exporter) -> Exporter:
    """Add ``exporter`` to :data:`EXPORTERS`; a malformed or already registered format id is a
    programming error (``ValueError``)."""
    format_id = exporter.format_id
    if FORMAT_ID_PATTERN.fullmatch(format_id) is None:
        raise ValueError(f"invalid export format id {format_id!r}")
    if format_id in EXPORTERS:
        raise ValueError(f"export format {format_id!r} is already registered")
    EXPORTERS[format_id] = exporter
    return exporter


def get_exporter(format_id: str) -> Exporter:
    """The exporter for ``format_id``; :class:`NotFoundError` (HTTP 404) when there is none."""
    exporter = EXPORTERS.get(format_id)
    if exporter is None:
        raise NotFoundError(
            "Unknown export format.",
            details={"format": format_id[:64], "available": sorted(EXPORTERS)},
        )
    return exporter
