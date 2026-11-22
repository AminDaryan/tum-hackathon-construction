"""CSV exports: the issue register (``issues.csv``) and one file per canonical table.

Format (``docs/api/rest-api.md``, section Exports): UTF-8 with a byte-order mark (so
spreadsheet applications detect the encoding), comma-separated, RFC 4180 quoting
(``QUOTE_MINIMAL``: fields with a comma, a quote or a line break are quoted, quotes doubled)
and ``\\r\\n`` line endings. Every value goes through :func:`app.exporters.safety.csv_value`:
text that a spreadsheet could read as a formula gets a ``'`` prefix, numbers are written in
plain notation without one.

``issues.csv`` has one row per issue, in the bundle's order, with the columns of
:data:`ISSUE_COLUMNS`. ``finding_category`` is the computed category (``error``,
``omission``, ``inconsistency``, ``ambiguity``, ``risk``, ``change_order_opportunity``), empty
for a finding about reading the file. ``cells`` lists the highlighted cells as A1 references
(``C12``) or, for delimited text sources, as ``CSV record N field M``, separated by spaces.

A table CSV has the columns ``source_row``, ``row_kind`` and then one column per table column
under its original header (its normalized name when the header is empty), one row per
canonical row in table order (excluded and hidden rows included, as extracted). Cell values
are the raw text as extracted (``None`` = empty); a number cell whose raw text is a plain
decimal literal is written as a number.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence

from app.exporters.bundle import ExportBundle
from app.exporters.safety import csv_value
from app.models.dataset import CellRef, Dataset, Table
from app.models.issue import ValidationIssue
from app.models.source import SourceKind, SourceLocation
from app.models.values import DataType

ISSUE_COLUMNS: tuple[str, ...] = (
    "validation_run_id",
    "dataset_id",
    "dataset_revision",
    "issue_id",
    "severity",
    "finding_category",
    "evidence_class",
    "effective_evidence_class",
    "review_status",
    "detector_id",
    "detector_version",
    "rule_id",
    "issue_category",
    "table",
    "sheet",
    "source_row",
    "cells",
    "title",
    "observed_value",
    "expected_value",
    "financial_impact_amount",
    "financial_impact_currency",
    "explanation",
    "suggested_action",
    "reviewer_comment",
)
TABLE_LEADING_COLUMNS: tuple[str, ...] = ("source_row", "row_kind")
UNKNOWN_LOCATION = "?"


def write_csv(rows: Iterable[Sequence[str]]) -> bytes:
    """Rows of already safe cell texts as UTF-8 (with BOM) CSV with ``\\r\\n`` line endings."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def cell_reference(source: SourceLocation | None) -> str:
    """``C12`` for spreadsheet cells, ``CSV record 14 field 3`` for delimited text, the
    location's description for other sources, ``?`` when there is no location."""
    if source is None:
        return UNKNOWN_LOCATION
    if source.kind is SourceKind.SPREADSHEET and source.a1 is not None:
        return source.a1
    if (
        source.kind is SourceKind.DELIMITED_TEXT
        and source.row_number is not None
        and source.column_number is not None
    ):
        return f"CSV record {source.row_number} field {source.column_number}"
    return source.describe()


def cell_source(ref: CellRef, dataset: Dataset) -> SourceLocation | None:
    """Where the cell ``ref`` points to sits in the source file: its own source, else the
    source of the dataset cell it names."""
    if ref.source is not None:
        return ref.source
    for table in dataset.tables:
        if table.table_id == ref.table_id and table.has_row(ref.row_id):
            cell = table.row(ref.row_id).cells.get(ref.column_id)
            return cell.source if cell is not None else None
    return None


def _text(value: str | None) -> str:
    return csv_value(value, is_number=False)


def issue_row(issue: ValidationIssue, dataset: Dataset) -> list[str]:
    """The ``issues.csv`` cells of one issue, in :data:`ISSUE_COLUMNS` order."""
    table: Table | None = None
    if issue.table_id is not None:
        table = next((t for t in dataset.tables if t.table_id == issue.table_id), None)
    source_row = None
    if table is not None and issue.row_id is not None and table.has_row(issue.row_id):
        source_row = table.row(issue.row_id).source_row_number
    impact = issue.estimated_financial_impact
    category = issue.finding_category
    cells = " ".join(cell_reference(cell_source(ref, dataset)) for ref in issue.affected_cells)
    return [
        _text(issue.validation_run_id),
        _text(issue.dataset_id),
        csv_value(issue.dataset_revision, is_number=True),
        _text(issue.issue_id),
        _text(issue.severity.value),
        _text(category.value if category is not None else None),
        _text(issue.evidence_class.value),
        _text(issue.effective_evidence_class.value),
        _text(issue.review_status.value),
        _text(issue.detector_id),
        _text(issue.detector_version),
        _text(issue.rule_id),
        _text(issue.issue_category),
        _text(table.name if table is not None else None),
        _text(table.source.sheet_name if table is not None else None),
        csv_value(source_row, is_number=True),
        _text(cells),
        _text(issue.title),
        _text(issue.observed_value),
        _text(issue.expected_value),
        csv_value(impact.amount if impact is not None else None, is_number=True),
        _text(impact.currency if impact is not None else None),
        _text(issue.explanation),
        _text(issue.suggested_action),
        _text(issue.reviewer_comment),
    ]


def issues_csv(bundle: ExportBundle) -> bytes:
    """The issue register of the bundle's run."""
    rows = (issue_row(issue, bundle.dataset) for issue in bundle.issues)
    return write_csv([list(ISSUE_COLUMNS), *rows])


def table_header(table: Table) -> list[str]:
    """``source_row``, ``row_kind``, then each column's original header (or normalized name)."""
    headers = [
        column.original_header
        if column.original_header and column.original_header.strip()
        else column.normalized_name
        for column in table.columns
    ]
    return [*TABLE_LEADING_COLUMNS, *(_text(header) for header in headers)]


def table_csv(table: Table) -> bytes:
    """One canonical table with its raw cell values as extracted."""
    column_ids = [column.column_id for column in table.columns]
    rows: list[list[str]] = [table_header(table)]
    for row in table.rows:
        cells = [row.cells[column_id] for column_id in column_ids]
        rows.append(
            [
                csv_value(row.source_row_number, is_number=True),
                _text(row.kind.value),
                *(
                    csv_value(cell.raw_value, is_number=cell.data_type is DataType.NUMBER)
                    for cell in cells
                ),
            ]
        )
    return write_csv(rows)


class IssuesCsvExporter:
    """``GET /validation-runs/{run_id}/export/issues.csv``."""

    format_id = "issues.csv"
    media_type = "text/csv; charset=utf-8"
    filename_suffix = " issues.csv"

    def export(self, bundle: ExportBundle) -> bytes:
        return issues_csv(bundle)
