"""Ingestion adapter for Word documents (.docx).

A bill of quantities in Word is written in one of two ways, and both are read:

* **as a table** (the common case): every table of the document becomes a table here, named
  after its place in the document (``Table 2``), with Word's rows and columns. Normalization
  then finds its header and columns exactly as for a spreadsheet: nothing about bills is
  assumed here. Cell texts are kept as written (numbers are parsed by normalization, which
  knows German and English notation and reports ambiguous ones);
* **as a list of item paragraphs** (``2.3.10 – Straßendecke schneiden [m]``): read into the
  bill model by :mod:`app.ingestion.docx.items` and flattened like a GAEB bill, so its item
  rows, sections and columns are declared. Cells carry their paragraph number.

What is not read is said in a warning: numbers Word adds automatically to numbered paragraphs
(they are not stored in the text), text boxes, and content imported from other files.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import IngestionLimits
from app.core.errors import ExtractionError
from app.ingestion.base import RawCell, RawSheet, RawValueType, RawWorkbook
from app.ingestion.docx.document import Body, Table, read_body
from app.ingestion.docx.items import ItemList, item_line, read_item_list
from app.ingestion.gaeb.flatten import flatten
from app.ingestion.security import TableLimitGuard, WorkbookCellBudget
from app.models.dataset import ExtractionWarning
from app.models.document import DocumentFormat
from app.models.source import SourceKind

MAX_LISTED = 12


class DocxAdapter:
    adapter_id = "docx.ooxml"
    adapter_version = "1.0.0"
    format = DocumentFormat.DOCX
    formats = frozenset({DocumentFormat.DOCX})

    def extract(self, path: Path, limits: IngestionLimits) -> RawWorkbook:
        body = read_body(path)
        bill = read_item_list(body.paragraphs)
        tables = [table for table in body.tables if table.cells]
        count = len(tables) + (1 if bill is not None else 0)
        if count == 0:
            raise ExtractionError(
                "No table and no list of items was found in the Word document. A bill in Word "
                "is read from its tables, or from paragraphs that start with an item number "
                "and state a unit, like '2.3.10 – Straßendecke schneiden [m]'.",
                details={"reason": "docx_no_bill"},
            )
        if count > limits.max_sheets:
            raise ExtractionError(
                f"The Word document has {count:,} tables; the limit is {limits.max_sheets:,}.",
                details={"limit": "max_sheets", "maximum": limits.max_sheets},
            )
        sheets: list[RawSheet] = []
        warnings: list[ExtractionWarning] = []
        if bill is not None:
            sheet, flattened = flatten(bill.document, limits)
            sheets.append(sheet)  # index 0, as its declared structure says
            warnings += [_list_warning(bill), *flattened]
        budget = WorkbookCellBudget("The Word document", limits)
        for table in tables:
            sheets.append(_table_sheet(table, len(sheets), limits, budget))
        if tables:
            warnings.append(_tables_warning(tables))
        warnings += _unread(body)
        details: dict[str, str | int | float | bool | None] = {
            "paragraphs": len(body.paragraphs),
            "tables": len(body.tables),
            "item_paragraphs": bill.items if bill is not None else 0,
        }
        return RawWorkbook(
            format=self.format,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            sheets=sheets,
            details=details,
            warnings=warnings,
        )


def _table_sheet(
    table: Table, index: int, limits: IngestionLimits, budget: WorkbookCellBudget
) -> RawSheet:
    name = f"Table {table.number}"
    guard = TableLimitGuard(f"Word table {table.number}", limits, budget)
    sheet = RawSheet(
        name=name,
        index=index,
        source_kind=SourceKind.WORD,
        max_row=table.rows,
        max_column=table.columns,
        merged_ranges=list(table.merged),
    )
    for (row, column), text in sorted(table.cells.items()):
        guard.admit(row, column)
        guard.check_text(text, row, column)
        sheet.cells[(row, column)] = RawCell(row, column, RawValueType.STRING, text)
    if table.nested:
        sheet.warnings.append(
            ExtractionWarning(
                code="docx_nested_tables",
                message=(
                    f"Word table {table.number} has {table.nested} table(s) inside its cells; "
                    "they were read as the text of their cell (cells separated by tabs, rows "
                    "by line breaks)."
                ),
                count=table.nested,
                needs_review=True,
            )
        )
    return sheet


def _listed(numbers: list[int]) -> str:
    shown = ", ".join(str(n) for n in numbers[:MAX_LISTED])
    return shown + (" …" if len(numbers) > MAX_LISTED else "")


def _tables_warning(tables: list[Table]) -> ExtractionWarning:
    return ExtractionWarning(
        code="docx_tables_read",
        message=(
            f"Read {len(tables)} table(s) of the Word document (tables "
            f"{_listed([t.number for t in tables])}), each as a table named after its place in "
            "the document. Rows and columns are counted as in Word; merged cells keep their "
            "text in their first cell."
        ),
        count=len(tables),
        needs_review=False,
    )


def _list_warning(bill: ItemList) -> ExtractionWarning:
    return ExtractionWarning(
        code="docx_list_read",
        message=(
            f"The bill was read from {bill.items} item paragraph(s) of the Word document "
            "(an item number, a text, and a unit in brackets or tab-separated columns), with "
            f"{bill.sections} section(s) and {bill.notes} note(s). Which lines are section "
            "headings and which belong to an item's long text was inferred from the layout; "
            "check the structure in the table preview."
        ),
        count=bill.items,
        needs_review=False,
    )


def _unread(body: Body) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    automatic = [
        p.number
        for p in body.paragraphs
        if p.auto_numbered and p.text.strip() and item_line(p) is None
    ]
    if automatic:
        warnings.append(
            ExtractionWarning(
                code="docx_automatic_numbering",
                message=(
                    f"{len(automatic)} paragraph(s) are numbered automatically by Word "
                    f"(paragraphs {_listed(automatic)}). Word does not store those numbers in "
                    "the text, so they were not read; if they are item numbers, type them, or "
                    "save the document as PDF and upload that."
                ),
                count=len(automatic),
                needs_review=True,
            )
        )
    if body.text_boxes:
        warnings.append(
            ExtractionWarning(
                code="docx_text_boxes_ignored",
                message="The Word document has text boxes or shapes with text; they are not read.",
                count=body.text_boxes,
                needs_review=False,
            )
        )
    if body.imported_parts:
        warnings.append(
            ExtractionWarning(
                code="docx_imported_content_ignored",
                message=(
                    f"The Word document imports content from {body.imported_parts} other "
                    "file(s) (altChunk); it is not read."
                ),
                count=body.imported_parts,
                needs_review=True,
            )
        )
    return warnings
