"""Excel workbooks (``.xlsx``) of the extracted tables, and of a validation run's findings.

Two exports share one writer (:func:`workbook`):

* ``GET /datasets/{dataset_id}/export/xlsx``: the extraction alone, available right after an
  upload: one sheet per canonical table and an ``Extraction`` sheet (document, format,
  extraction quality and warnings).
* ``GET /validation-runs/{run_id}/export/xlsx`` (format id ``xlsx``): the same for the dataset
  revision the run checked, plus an ``Issues`` sheet with the run's issue register.

A table sheet has the columns ``Source`` (where the row is: PDF page, file line, spreadsheet
row or CSV record) and ``Row kind`` (item, section, subtotal, text...), then the table's
columns under their original headers (a column empty in every row is left out). Number cells
are written as numbers with their exact decimal value and as many decimals as the source
showed; dates as dates; everything else as the text extracted. Section and total rows are
bold. The header row is frozen and filtered.

Safety: every text cell is typed as text, so a value such as ``=HYPERLINK(...)`` is shown, never
evaluated (no quote prefix is needed, unlike CSV, and none is added: the text stays as
extracted). Characters XML cannot hold are replaced with U+FFFD, and texts are clipped to
Excel's 32,767 characters.

Deterministic: the same input and ``generated_at`` give byte-identical files (workbook
properties and every ZIP timestamp come from ``generated_at``).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.exporters.bundle import ExportBundle, utc_timestamp
from app.exporters.csv_export import cell_reference, cell_source
from app.exporters.zip_export import zip_timestamp
from app.models.dataset import Cell, Dataset, Row, RowKind, Table
from app.models.document import Document
from app.models.issue import ValidationIssue
from app.models.run import ValidationRun
from app.models.source import SourceKind
from app.models.values import (
    BooleanValue,
    DataType,
    DateTimeValue,
    DateValue,
    NumberValue,
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_CELL_CHARS = 32_767  # Excel's limit for one cell
MAX_SHEET_NAME = 31
MAX_COLUMN_WIDTH = 60
LEADING_COLUMNS = ("Source", "Row kind")
EXTRACTION_SHEET = "Extraction"
ISSUES_SHEET = "Issues"
_SHEET_NAME_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")
_BOLD_ROWS = frozenset(
    {RowKind.SECTION, RowKind.SUBTOTAL, RowKind.GRAND_TOTAL, RowKind.GROSS_TOTAL}
)
_HEADER_FILL = PatternFill("solid", start_color="FFDDE3EA", end_color="FFDDE3EA")
_HEADER_FONT = Font(bold=True)
_TOTAL_BORDER = Border(top=Side(style="thin"))
_FILE_MODE = 0o100644
CORE_PROPERTIES = "docProps/core.xml"
_MODIFIED = re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")
_UNIX = 3

NOTES: tuple[str, ...] = (
    "Numbers are exact decimals with as many decimals as the source showed; texts are as "
    "extracted and are never evaluated as formulas.",
    "Source: where each row is in the uploaded document (PDF page, file line, spreadsheet row "
    "or CSV record). The original upload is stored unchanged.",
)


@dataclass(frozen=True, slots=True)
class WorkbookInput:
    document: Document
    dataset: Dataset
    generated_at: datetime
    run: ValidationRun | None = None
    issues: Sequence[ValidationIssue] = ()


def workbook(data: WorkbookInput) -> bytes:
    """The ``.xlsx`` file for ``data`` (see the module docstring)."""
    if data.generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    book = Workbook()
    default_sheet = book.active
    if not isinstance(default_sheet, Worksheet):
        raise TypeError("openpyxl created a workbook without a worksheet")
    book.remove(default_sheet)
    names: set[str] = set()
    for table in data.dataset.tables:
        sheet = book.create_sheet()
        sheet.title = _sheet_name(table.name, names)
        _table_sheet(sheet, table)
    if data.run is not None:
        _issues_sheet(book.create_sheet(_sheet_name(ISSUES_SHEET, names)), data)
    _extraction_sheet(book.create_sheet(_sheet_name(EXTRACTION_SHEET, names)), data)
    moment = data.generated_at.astimezone(UTC).replace(tzinfo=None)
    book.properties.creator = "Desvio"
    book.properties.lastModifiedBy = None
    book.properties.created = moment
    book.properties.modified = moment
    buffer = io.BytesIO()
    book.save(buffer)
    return _fixed_timestamps(buffer.getvalue(), data.generated_at.astimezone(UTC))


# --------------------------------------------------------------------------- cells
def _text(value: object) -> str | None:
    if value is None:
        return None
    text = ILLEGAL_CHARACTERS_RE.sub("�", str(value))
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"


def _put_text(sheet: Worksheet, row: int, column: int, value: object) -> None:
    text = _text(value)
    if text is None or text == "":
        return
    cell = sheet.cell(row=row, column=column)
    cell.value = text
    cell.data_type = "s"  # never a formula, whatever the text starts with


def _number_format(value: Decimal, *, percent: bool) -> str:
    exponent = value.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if percent:
        places = max(0, places - 2)
        return "0" + ("." + "0" * places if places else "") + "%"
    return "#,##0" + ("." + "0" * places if places else "")


def _put_cell(sheet: Worksheet, row: int, column: int, table_cell: Cell) -> None:
    value = table_cell.normalized_value or table_cell.parsed_value
    if table_cell.data_type is DataType.NUMBER and isinstance(value, NumberValue):
        cell = sheet.cell(row=row, column=column, value=value.value)
        cell.number_format = _number_format(value.value, percent=value.is_percent)
    elif isinstance(value, DateTimeValue):
        cell = sheet.cell(row=row, column=column, value=value.value.replace(tzinfo=None))
        cell.number_format = "yyyy-mm-dd hh:mm"
    elif isinstance(value, DateValue):
        cell = sheet.cell(row=row, column=column, value=value.value)
        cell.number_format = "yyyy-mm-dd"
    elif isinstance(value, BooleanValue) and table_cell.raw_value is None:
        sheet.cell(row=row, column=column, value=value.value)
    else:
        _put_text(sheet, row, column, table_cell.raw_value)


def _header(sheet: Worksheet, titles: Sequence[str]) -> None:
    for column, title in enumerate(titles, start=1):
        _put_text(sheet, 1, column, title)
        cell = sheet.cell(row=1, column=column)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"


def _widths(sheet: Worksheet, minimum: int = 8) -> None:
    widths: dict[int, int] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            length = len(str(cell.value)) if not isinstance(cell.value, Decimal) else 12
            widths[cell.column] = max(
                widths.get(cell.column, minimum), min(length + 2, MAX_COLUMN_WIDTH)
            )
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = width


# --------------------------------------------------------------------------- sheets
def _sheet_name(name: str, taken: set[str]) -> str:
    base = _SHEET_NAME_FORBIDDEN.sub("_", name).strip("' ") or "Table"
    base = base[:MAX_SHEET_NAME]
    candidate, number = base, 2
    while candidate.lower() in taken or candidate.lower() == "history":
        suffix = f" ({number})"
        candidate = base[: MAX_SHEET_NAME - len(suffix)] + suffix
        number += 1
    taken.add(candidate.lower())
    return candidate


def row_source(table: Table, row: Row) -> str:
    """Where a row is in the document: ``page 4``, ``line 345``, ``row 12``, ``record 14``,
    ``paragraph 31`` (a Word item list), ``Table 2, row 5`` (a Word table)."""
    for table_cell in row.cells.values():
        source = table_cell.source
        if table_cell.raw_value is None or source is None:
            continue
        if source.page_number is not None:
            return f"page {source.page_number}"
        if source.kind in (SourceKind.GAEB_XML, SourceKind.GAEB_90) and source.line_number:
            return f"line {source.line_number}"
        if source.kind is SourceKind.WORD and source.line_number:
            return f"paragraph {source.line_number}"
        break
    if table.source.kind is SourceKind.DELIMITED_TEXT:
        return f"record {row.source_row_number}"
    if table.source.kind is SourceKind.SPREADSHEET:
        return f"row {row.source_row_number}"
    if table.source.kind is SourceKind.WORD and table.source.sheet_name:
        return f"{table.source.sheet_name}, row {row.source_row_number}"
    return ""


def _table_sheet(sheet: Worksheet, table: Table) -> None:
    # Columns empty in every row (GAEB IDs of a PDF bill, say) are left out of the sheet.
    shown = [
        column
        for column in table.columns
        if any(row.cells[column.column_id].raw_value not in (None, "") for row in table.rows)
    ]
    headers = [
        column.original_header
        if column.original_header and column.original_header.strip()
        else column.normalized_name
        for column in shown
    ]
    _header(sheet, [*LEADING_COLUMNS, *headers])
    column_ids = [column.column_id for column in shown]
    for offset, row in enumerate(table.rows, start=2):
        _put_text(sheet, offset, 1, row_source(table, row))
        _put_text(sheet, offset, 2, row.kind.value)
        for position, column_id in enumerate(column_ids, start=3):
            _put_cell(sheet, offset, position, row.cells[column_id])
        if row.kind in _BOLD_ROWS:
            for cell in sheet[offset]:
                cell.font = Font(bold=True)
                if row.kind is not RowKind.SECTION:
                    cell.border = _TOTAL_BORDER
    if table.rows:
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(column_ids) + 2)}{len(table.rows) + 1}"
    _widths(sheet)


ISSUE_TITLES = (
    "Severity",
    "Category",  # the finding category; empty for a finding about reading the file
    "Evidence",
    "Review status",
    "Check",
    "Table",
    "Source row",
    "Cells",
    "Title",
    "Observed",
    "Expected",
    "Financial impact",
    "Currency",
    "Explanation",
    "Suggested action",
    "Reviewer comment",
    "Issue ID",
)
_IMPACT_COLUMN = ISSUE_TITLES.index("Financial impact") + 1
_WRAPPED_COLUMNS = tuple(ISSUE_TITLES.index(title) + 1 for title in ("Title", "Explanation"))


def _put_issue(
    sheet: Worksheet, row: int, issue: ValidationIssue, dataset: Dataset, first_column: int = 1
) -> None:
    """The :data:`ISSUE_TITLES` cells of one issue in ``row``, from ``first_column``."""
    table = next((t for t in dataset.tables if t.table_id == issue.table_id), None)
    source_row = None
    if table is not None and issue.row_id is not None and table.has_row(issue.row_id):
        source_row = row_source(table, table.row(issue.row_id))
    impact = issue.estimated_financial_impact
    cells = " ".join(cell_reference(cell_source(ref, dataset)) for ref in issue.affected_cells)
    category = issue.finding_category
    values = (
        issue.severity.value,
        category.value if category is not None else None,
        issue.effective_evidence_class.value,
        issue.review_status.value,
        issue.detector_id,
        table.name if table is not None else None,
        source_row,
        cells,
        issue.title,
        issue.observed_value,
        issue.expected_value,
        None,
        impact.currency if impact is not None else None,
        issue.explanation,
        issue.suggested_action,
        issue.reviewer_comment,
        issue.issue_id,
    )
    for column, value in enumerate(values, start=first_column):
        _put_text(sheet, row, column, value)
    if impact is not None:
        cell = sheet.cell(row=row, column=_IMPACT_COLUMN + first_column - 1, value=impact.amount)
        cell.number_format = _number_format(impact.amount, percent=False)
    for column in _WRAPPED_COLUMNS:
        sheet.cell(row=row, column=column + first_column - 1).alignment = Alignment(wrap_text=True)


def _issues_sheet(sheet: Worksheet, data: WorkbookInput) -> None:
    _header(sheet, ISSUE_TITLES)
    for offset, issue in enumerate(data.issues, start=2):
        _put_issue(sheet, offset, issue, data.dataset)
    if data.issues:
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(ISSUE_TITLES))}{len(data.issues) + 1}"
    _widths(sheet)


def project_workbook(bundles: Sequence[ExportBundle], generated_at: datetime) -> bytes:
    """The findings of several bills (a project's last validation) in one ``Issues`` sheet: a
    leading ``File`` column with the bill's file name, then the run export's issue columns."""
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    book = Workbook()
    sheet = book.active
    if not isinstance(sheet, Worksheet):
        raise TypeError("openpyxl created a workbook without a worksheet")
    sheet.title = ISSUES_SHEET
    _header(sheet, ("File", *ISSUE_TITLES))
    row = 2
    for bundle in bundles:
        for issue in bundle.issues:
            _put_text(sheet, row, 1, bundle.document.original_filename)
            _put_issue(sheet, row, issue, bundle.dataset, first_column=2)
            row += 1
    if row > 2:
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(ISSUE_TITLES) + 1)}{row - 1}"
    _widths(sheet)
    moment = generated_at.astimezone(UTC).replace(tzinfo=None)
    book.properties.creator = "Desvio"
    book.properties.lastModifiedBy = None
    book.properties.created = moment
    book.properties.modified = moment
    buffer = io.BytesIO()
    book.save(buffer)
    return _fixed_timestamps(buffer.getvalue(), generated_at.astimezone(UTC))


def _extraction_sheet(sheet: Worksheet, data: WorkbookInput) -> None:
    dataset, document = data.dataset, data.document
    report = dataset.extraction
    facts: list[tuple[str, object]] = [
        ("Document", document.original_filename),
        ("Format", document.format.value),
        ("Document ID", document.document_id),
        ("Profile", f"{dataset.profile_id} {dataset.profile_version}"),
        ("Dataset", f"{dataset.dataset_id} (revision {dataset.revision})"),
        ("Extraction quality", report.quality.value),
        ("Extracted by", f"{report.adapter_id} {report.adapter_version}"),
        *((f"Detail: {key}", value) for key, value in sorted(report.details.items())),
    ]
    if data.run is not None:
        facts.append(("Validation run", data.run.run_id))
    facts.append(("Generated at", utc_timestamp(data.generated_at)))
    _header(sheet, ("Item", "Value"))
    row = 2
    for label, value in facts:
        if value is None:
            continue
        _put_text(sheet, row, 1, label)
        _put_text(sheet, row, 2, value)
        row += 1
    row += 1
    for column, title in enumerate(("Warning", "Needs review", "Count", "Message"), start=1):
        _put_text(sheet, row, column, title)
        sheet.cell(row=row, column=column).font = _HEADER_FONT
    for warning in report.warnings:
        row += 1
        _put_text(sheet, row, 1, warning.code)
        _put_text(sheet, row, 2, "yes" if warning.needs_review else "no")
        if warning.count is not None:
            sheet.cell(row=row, column=3, value=warning.count)
        _put_text(sheet, row, 4, warning.message)
        sheet.cell(row=row, column=4).alignment = Alignment(wrap_text=True)
    row += 2
    for note in NOTES:
        _put_text(sheet, row, 1, note)
        row += 1
    _widths(sheet)
    sheet.column_dimensions["D"].width = MAX_COLUMN_WIDTH


# --------------------------------------------------------------------------- determinism
def _fixed_timestamps(content: bytes, moment: datetime) -> bytes:
    """``content`` (a ZIP) re-packed with every entry dated ``moment`` and fixed attributes.
    openpyxl writes the time of saving as the workbook's "modified" property, whatever the
    workbook says; it is set to ``moment`` here."""
    stamp = zip_timestamp(moment)
    modified = moment.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(content)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as target,
    ):
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == CORE_PROPERTIES:
                data = _MODIFIED.sub(rb"\g<1>" + modified + rb"\g<2>", data)
            entry = zipfile.ZipInfo(info.filename, date_time=stamp)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = _FILE_MODE << 16
            entry.create_system = _UNIX
            target.writestr(entry, data)
    return out.getvalue()


class XlsxExporter:
    """``GET /validation-runs/{run_id}/export/xlsx``: tables and issues of one run."""

    format_id = "xlsx"
    media_type = XLSX_MEDIA_TYPE
    filename_suffix = " issues.xlsx"

    def export(self, bundle: ExportBundle) -> bytes:
        return workbook(
            WorkbookInput(
                document=bundle.document,
                dataset=bundle.dataset,
                generated_at=bundle.generated_at,
                run=bundle.run,
                issues=bundle.issues,
            )
        )
