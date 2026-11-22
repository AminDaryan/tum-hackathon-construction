"""XLSX adapter built on openpyxl. Reads typed values, formulas with their cached results,
number formats, merged ranges, sheet visibility and hidden rows and columns; never evaluates
formulas, never runs macros (``keep_vba=False``) and never follows external links
(``keep_links=False``).

Hostile input is handled in three layers:

1. Upload checks (:mod:`app.ingestion.security`) reject OLE2 containers (encrypted packages,
   legacy ``.xls``), zip bombs, encrypted entries and unsafe entry names before the file is
   stored.
2. :func:`_scan_archive` streams every archive part through a defused, tree-less XML parser
   before openpyxl runs. openpyxl materializes one object for every cell element, for every
   cell of a merged, hyperlinked or commented range (a 40-byte
   ``<mergeCell ref="A1:XFD1048576"/>`` would mean 17 billion objects) and for every formatted
   ``<row>`` element, and re-creates the full text of a shared formula for every cell that uses
   it. The scan counts those objects per sheet (``max_cells_per_sheet``) and for the whole
   workbook (``max_cells_per_workbook``), charges re-created formula text to the byte budget
   (``max_uncompressed_bytes``), rejects shared strings longer than ``max_cell_chars``, and
   refuses DTDs and entities. The ``<dimension>`` tag is never trusted, neither to accept nor
   to reject: formatting legitimately inflates it.
3. openpyxl itself parses XML through defusedxml, which the constructor insists on.

While cells are stored, :class:`~app.ingestion.security.TableLimitGuard` enforces the
per-sheet limits and a :class:`~app.ingestion.security.WorkbookCellBudget` the workbook limit.
Only cells present in the file are visited (``worksheet._cells``): the sheet dimension and
``max_row`` can be inflated by formatting to millions of empty cells.

Values follow the :class:`~app.ingestion.base.RawCell` contract. A float that is not finite
(``<v>1E999</v>`` becomes infinity) is not a number: it is stored as the error ``#NUM!``, which
is what Excel shows for a number it cannot represent, with the per-sheet warning
``non_finite_number``; cached formula results are treated the same way. (openpyxl itself
replaces a value in a date-formatted cell that is out of the date range, infinity included,
by ``#VALUE!`` before this module sees it.) Text is an ERROR cell
only when the file types it as an error (``t="e"``): the text ``"#N/A"`` stays text.

Number formats longer than ``max_number_format_chars`` (Excel's own limit, so no Excel file
has one) and formats that a malformed style sheet references without defining are not read
(``number_format=None``, warnings ``number_format_too_long`` / ``number_format_invalid``).

Visibility (ADR 0002: the format layer never drops data). Hidden and very hidden sheets are
extracted with ``RawSheet.hidden``; chart sheets hold no cells and are skipped with the warning
``chartsheet_skipped``. Rows and columns are listed in ``hidden_rows`` / ``hidden_columns``
when the file hides them or gives them zero (or negative) height or width, which Excel also
cannot display; their cells are extracted like any other. openpyxl reads the flag leniently
(``hidden="False"`` counts as hidden), which errs on the side of flagging. Column dimensions
cover ranges ``min..max`` (reversed corners count like normal ones). Outline levels 1 to 7 go to
``row_outline_levels``; other levels are not recorded (warning ``outline_level_invalid``). A
sheet that hides rows by default (``sheetFormatPr zeroHeight``) gets the warning
``rows_hidden_by_default``, because which of its rows Excel showed cannot be read reliably.
Only rows and columns inside the sheet's extent (the last row and column holding a value) are
listed: nothing outside it holds data, and a hostile file could otherwise list billions.
"""

from __future__ import annotations

import contextlib
import math
import zipfile
import zlib
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from xml.etree.ElementTree import ParseError

import openpyxl
import openpyxl.xml
from defusedxml import DefusedXmlException
from defusedxml.ElementTree import DefusedXMLParser
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.chartsheet import Chartsheet
from openpyxl.utils.cell import column_index_from_string, range_boundaries
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.dimensions import ColumnDimension
from openpyxl.worksheet.formula import DataTableFormula
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.xml.constants import SHEET_MAIN_NS

from app.core.config import IngestionLimits
from app.core.errors import ExtractionError
from app.ingestion.base import MergedRange, RawCell, RawSheet, RawValueType, RawWorkbook
from app.ingestion.security import TableLimitGuard, WorkbookCellBudget
from app.models.dataset import ExtractionWarning
from app.models.document import DocumentFormat
from app.models.source import SourceKind, SourceLocation

# What a number that is not finite becomes: Excel's error for a number it cannot represent.
NON_FINITE_NUMBER_ERROR = "#NUM!"
MAX_OUTLINE_LEVEL = 7  # Excel's deepest row grouping

# Failures of openpyxl, zipfile and the XML parser on malformed or hostile workbooks. They are
# only caught around library calls, so they cannot hide bugs in this module.
_READ_FAILURES: tuple[type[Exception], ...] = (
    InvalidFileException,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    ParseError,
    KeyError,
    ValueError,  # includes defusedxml's DTDForbidden / EntitiesForbidden
    TypeError,
    AttributeError,
    IndexError,
    EOFError,
    zlib.error,
    OSError,
    NotImplementedError,  # unsupported compression method
    RuntimeError,  # zipfile: encrypted entry
)

_CELL_TAG = f"{{{SHEET_MAIN_NS}}}c"
_ROW_TAG = f"{{{SHEET_MAIN_NS}}}row"
_FORMULA_TAG = f"{{{SHEET_MAIN_NS}}}f"
_SHARED_STRING_TAG = f"{{{SHEET_MAIN_NS}}}si"
_TEXT_TAG = f"{{{SHEET_MAIN_NS}}}t"
_PHONETIC_TAG = f"{{{SHEET_MAIN_NS}}}rPh"  # reading aid; not part of the cell text
# Elements whose ``ref`` range openpyxl turns into one cell object per covered cell.
_RANGE_TAGS = frozenset(
    f"{{{SHEET_MAIN_NS}}}{name}" for name in ("mergeCell", "hyperlink", "comment")
)
# openpyxl creates a row-dimension object for a <row> with any other plain attribute.
_PLAIN_ROW_ATTRIBUTES = frozenset({"r", "spans"})
_EXCEL_MAX_ROWS = 1_048_576
_EXCEL_MAX_COLUMNS = 16_384
_SCAN_CHUNK_BYTES = 64 * 1024
_SHOWN_TITLE_CHARS = 40  # sheet names in messages; Excel allows 31


class XlsxAdapter:
    """Reads ``.xlsx`` workbooks into one raw sheet per worksheet (chart sheets are skipped)."""

    adapter_id = "xlsx.openpyxl"
    adapter_version = "1.1.0"
    formats: frozenset[DocumentFormat] = frozenset({DocumentFormat.XLSX})

    def __init__(self) -> None:
        if openpyxl.xml.DEFUSEDXML is not True:
            raise RuntimeError(
                "openpyxl is not using defusedxml, so XLSX extraction would be open to XML "
                "attacks. Install defusedxml and do not set OPENPYXL_DEFUSEDXML=False."
            )

    def extract(self, path: Path, limits: IngestionLimits) -> RawWorkbook:
        """Read ``path`` (already size/format-checked). Raises
        :class:`~app.core.errors.ExtractionError` when the workbook cannot be read safely or a
        limit of ``limits`` is exceeded."""
        _scan_archive(path, limits)
        builds: list[_SheetBuild] = []
        warnings: list[ExtractionWarning] = []
        workbook_cells = WorkbookCellBudget("The workbook", limits)
        with _open_workbook(path, data_only=False) as workbook:
            _check_sheet_count(workbook, limits)
            for index, title in enumerate(workbook.sheetnames):
                sheet = workbook[title]
                if isinstance(sheet, Chartsheet):
                    warnings.append(_chartsheet_skipped(title, index))
                else:
                    builds.append(_read_worksheet(sheet, index, limits, workbook_cells))
        formula_cells = sum(len(build.formula_cells) for build in builds)
        without_cached_value = 0
        if formula_cells:  # the second load is only needed for cached formula results
            with _open_workbook(path, data_only=True) as cached:
                without_cached_value = _apply_cached_values(cached, builds)
        for build in builds:
            build.sheet.warnings.extend(_sheet_warnings(build, limits))
        return RawWorkbook(
            format=DocumentFormat.XLSX,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            sheets=[build.sheet for build in builds],
            details={
                "openpyxl_version": openpyxl.__version__,
                "worksheets": len(builds),
                "formula_cells": formula_cells,
                "formula_cells_without_cached_value": without_cached_value,
            },
            warnings=warnings,
        )


# --------------------------------------------------------------------------- workbook loading
@contextlib.contextmanager
def _open_workbook(path: Path, *, data_only: bool) -> Iterator[Workbook]:
    """Load with every dangerous feature off. A file handle is passed (not the path) because
    stored originals have no extension, which openpyxl would refuse."""
    with path.open("rb") as handle:
        try:
            workbook = openpyxl.load_workbook(
                handle,
                read_only=False,
                keep_vba=False,
                data_only=data_only,
                keep_links=False,
                rich_text=False,
            )
        except _READ_FAILURES as exc:
            raise _unreadable(exc) from exc
        try:
            yield workbook
        finally:
            workbook.close()


def _unreadable(exc: Exception) -> ExtractionError:
    # Library messages can contain the file's path, so only the exception type is shown.
    return ExtractionError(f"The workbook could not be read ({type(exc).__name__}).")


def _check_sheet_count(workbook: Workbook, limits: IngestionLimits) -> None:
    count = len(workbook.sheetnames)
    if count > limits.max_sheets:
        raise ExtractionError(
            f"The workbook has {count:,} sheets; the limit is {limits.max_sheets:,}.",
            details={"limit": "max_sheets", "maximum": limits.max_sheets},
        )


def _chartsheet_skipped(title: str, index: int) -> ExtractionWarning:
    return ExtractionWarning(
        code="chartsheet_skipped",
        message=f"Chart sheet {_shown(title)} contains a chart, not cells, and was skipped.",
        source=_sheet_location(title, index),
        needs_review=False,  # no cell data is lost
    )


def _shown(title: str) -> str:
    """A sheet name for messages: quoted, and shortened when a hostile file made it long."""
    if len(title) <= _SHOWN_TITLE_CHARS:
        return repr(title)
    return f"{title[:_SHOWN_TITLE_CHARS]!r}…"


def _sheet_location(title: str, index: int) -> SourceLocation:
    return SourceLocation(kind=SourceKind.SPREADSHEET, sheet_name=title, sheet_index=index)


# --------------------------------------------------------------------------- worksheets
@dataclass(slots=True)
class _SheetBuild:
    """A raw sheet under construction: its limit guard, the formula cells that still wait for
    their cached results, and how many cells or rows each per-sheet warning concerns."""

    sheet: RawSheet
    guard: TableLimitGuard
    max_number_format_chars: int
    formula_cells: list[tuple[int, int]] = field(default_factory=list)
    notes: Counter[str] = field(default_factory=Counter)  # warning code -> cells or rows
    rows_hidden_by_default: bool = False

    def store(self, cell: RawCell, *, new: bool = True) -> None:
        if new:
            self.guard.admit(cell.row, cell.column)
        self.guard.check_text(cell.text, cell.row, cell.column)
        self.guard.check_text(cell.formula, cell.row, cell.column)
        self.sheet.cells[(cell.row, cell.column)] = cell


def _read_worksheet(
    worksheet: Worksheet, index: int, limits: IngestionLimits, workbook_cells: WorkbookCellBudget
) -> _SheetBuild:
    """Convert the cells present in the file, in (row, column) order, then the hidden rows and
    columns inside the extent. Formula cells are stored as UNAVAILABLE placeholders until
    :func:`_apply_cached_values` finds a cached result."""
    title = worksheet.title
    build = _SheetBuild(
        sheet=RawSheet(
            name=title,
            index=index,
            source_kind=SourceKind.SPREADSHEET,
            hidden=worksheet.sheet_state != "visible",  # "hidden" or "veryHidden": extracted
            merged_ranges=_merged_ranges(worksheet),
        ),
        guard=TableLimitGuard(f"Sheet {_shown(title)}", limits, workbook_cells),
        max_number_format_chars=limits.max_number_format_chars,
    )
    present = worksheet._cells  # only cells written in the file; see the module docstring
    for row, column in sorted(present):
        cell = present[(row, column)]
        if isinstance(cell, MergedCell):  # merged away: never a value, a formula or a format
            continue
        value = cell.value
        if cell.data_type == "f":
            build.store(_formula_placeholder(row, column, cell, _number_format(cell, build)))
            build.formula_cells.append((row, column))
        elif value is not None and value != "":  # styled-only cells are empty
            build.store(
                _value_cell(
                    row,
                    column,
                    value,
                    data_type=cell.data_type,
                    number_format=_number_format(cell, build),
                    notes=build.notes,
                )
            )
    cells = build.sheet.cells
    build.sheet.max_row = max((row for row, _ in cells), default=0)
    build.sheet.max_column = max((column for _, column in cells), default=0)
    _read_row_visibility(worksheet, build)
    _read_hidden_columns(worksheet, build.sheet)
    return build


def _merged_ranges(worksheet: Worksheet) -> list[MergedRange]:
    """Merged ranges in (row, column) order; openpyxl keeps them in a set."""
    bounds = sorted((r.min_row, r.min_col, r.max_row, r.max_col) for r in worksheet.merged_cells)
    return [MergedRange(*corners) for corners in bounds]


def _number_format(cell: Cell, build: _SheetBuild) -> str | None:
    """The cell's number format, or ``None`` when it cannot be used: the style references a
    format the workbook does not define (openpyxl raises ``IndexError``), or the format is
    longer than Excel allows. Both cases are counted for the sheet's warnings."""
    try:
        number_format = cell.number_format
    except IndexError:
        build.notes["number_format_invalid"] += 1
        return None
    if number_format is None:
        return None
    if len(number_format) > build.max_number_format_chars:
        build.notes["number_format_too_long"] += 1
        return None
    return number_format


def _read_row_visibility(worksheet: Worksheet, build: _SheetBuild) -> None:
    """Hidden rows and outline levels inside the extent. ``row_dimensions`` is a defaultdict:
    only its existing entries are read, so no row object is created."""
    sheet = build.sheet
    for row, dimension in worksheet.row_dimensions.items():
        if not 1 <= row <= sheet.max_row:
            continue
        if dimension.hidden or _is_collapsed_size(dimension.ht):
            sheet.hidden_rows.add(row)
        level = dimension.outlineLevel or 0
        if 1 <= level <= MAX_OUTLINE_LEVEL:
            sheet.row_outline_levels[row] = level
        elif level:
            build.notes["outline_level_invalid"] += 1
    build.rows_hidden_by_default = bool(worksheet.sheet_format.zeroHeight)


def _read_hidden_columns(worksheet: Worksheet, sheet: RawSheet) -> None:
    """Columns hidden (or of zero width) inside the extent; one dimension covers a range."""
    for dimension in worksheet.column_dimensions.values():
        if dimension.hidden or _is_collapsed_size(dimension.width):
            first, last = _column_span(dimension)
            sheet.hidden_columns.update(range(max(first, 1), min(last, sheet.max_column) + 1))


def _column_span(dimension: ColumnDimension) -> tuple[int, int]:
    """``(first, last)`` column of a ``<col>`` element; a missing ``max`` means one column and
    reversed bounds count like normal ones."""
    first = dimension.min or column_index_from_string(dimension.index)
    last = dimension.max or first
    return min(first, last), max(first, last)


def _is_collapsed_size(size: float | None) -> bool:
    """A row height or column width at which Excel shows nothing."""
    return size is not None and size <= 0


def _apply_cached_values(workbook: Workbook, builds: list[_SheetBuild]) -> int:
    """Replace formula placeholders with the results cached in ``workbook`` (loaded with
    ``data_only=True``). Returns how many formulas have no cached result."""
    missing = 0
    for build in builds:
        if not build.formula_cells:
            continue
        cached_cells = workbook[build.sheet.name]._cells
        for key in build.formula_cells:
            cached = cached_cells.get(key)
            if cached is None or cached.value is None:
                missing += 1  # the placeholder (UNAVAILABLE) stays
                continue
            placeholder = build.sheet.cells[key]
            build.store(
                _value_cell(
                    *key,
                    cached.value,
                    data_type=cached.data_type,
                    number_format=placeholder.number_format,
                    notes=build.notes,
                    formula=placeholder.formula,
                ),
                new=False,
            )
    return missing


# --------------------------------------------------------------------------- sheet warnings
# code -> (message after "<count> cell(s) / row(s) of sheet <name> ", needs_review)
_COUNTED_WARNINGS: dict[str, tuple[str, bool]] = {
    "non_finite_number": (
        "cell(s) of sheet {sheet} store a number that is not finite (such as 1E999, which "
        f"overflows to infinity), which no spreadsheet can hold. They are read as the error "
        f"{NON_FINITE_NUMBER_ERROR}; cached formula results are included.",
        True,  # a value could not be read
    ),
    "number_format_too_long": (
        "cell(s) of sheet {sheet} have a number format longer than {maximum:,} characters, "
        "Excel's own limit. The format was not read, so currency or percentage markers in it "
        "are not used.",
        True,  # can change how currency and percentages are read
    ),
    "number_format_invalid": (
        "cell(s) of sheet {sheet} refer to a number format that the workbook does not define "
        "(a malformed style sheet). The format was not read.",
        True,  # can change how currency and percentages are read
    ),
    "outline_level_invalid": (
        "row(s) of sheet {sheet} have an outline (grouping) level outside 1 to "
        f"{MAX_OUTLINE_LEVEL}. Their rows are extracted; the level is not recorded.",
        False,  # grouping only: no value and no row is affected
    ),
}


def _sheet_warnings(build: _SheetBuild, limits: IngestionLimits) -> list[ExtractionWarning]:
    """One warning per code that occurred on the sheet, with the number of cells or rows."""
    sheet = build.sheet
    shown = _shown(sheet.name)
    location = _sheet_location(sheet.name, sheet.index)
    warnings = [
        ExtractionWarning(
            code=code,
            message=f"{count:,} "
            + template.format(sheet=shown, maximum=limits.max_number_format_chars),
            source=location,
            count=count,
            needs_review=needs_review,
        )
        for code, (template, needs_review) in _COUNTED_WARNINGS.items()
        if (count := build.notes[code])
    ]
    if build.rows_hidden_by_default:
        warnings.append(
            ExtractionWarning(
                code="rows_hidden_by_default",
                message=f"Sheet {shown} hides rows by default (zeroHeight), so Excel may not "
                "have shown rows that are not marked hidden. Every row is extracted; check "
                "which rows the document presents.",
                source=location,
                needs_review=True,  # hidden rows are read with and without in totals
            )
        )
    return warnings


# --------------------------------------------------------------------------- cell values
def _formula_placeholder(row: int, column: int, cell: Cell, number_format: str | None) -> RawCell:
    return RawCell(
        row=row,
        column=column,
        value_type=RawValueType.UNAVAILABLE,
        text=None,
        formula=_formula_text(cell.value),
        number_format=number_format,
    )


def _value_cell(
    row: int,
    column: int,
    value: object,
    *,
    data_type: str,
    number_format: str | None,
    notes: Counter[str],
    formula: str | None = None,
) -> RawCell:
    """Convert a non-empty openpyxl value. ``formula`` marks a cached formula result; a number
    that is not finite is counted in ``notes``."""
    make = partial(RawCell, row, column, formula=formula, number_format=number_format)
    if isinstance(value, bool):  # before int: bool is a subclass of int
        return make(RawValueType.BOOLEAN, "TRUE" if value else "FALSE", boolean=value)
    if isinstance(value, int):
        return _number_cell(make, Decimal(value))
    if isinstance(value, float):
        if not math.isfinite(value):  # <v>1E999</v> parses as inf; never a number
            notes["non_finite_number"] += 1
            return make(RawValueType.ERROR, NON_FINITE_NUMBER_ERROR)
        # The RawCell contract: Excel's 15 significant digits, which also drops binary noise
        # such as 3.3000000000000003 in cached results. Never Decimal(float).
        return _number_cell(make, Decimal(format(value, ".15g")))
    if isinstance(value, datetime | date | time):
        return make(RawValueType.DATETIME, value.isoformat(), temporal=value)
    if isinstance(value, timedelta):  # duration formats such as [h]:mm
        return make(RawValueType.STRING, str(value))
    if isinstance(value, str):  # an error only when the file types it as one (t="e")
        return make(RawValueType.ERROR if data_type == "e" else RawValueType.STRING, value)
    raise ExtractionError(f"A cell holds a value of an unsupported type ({type(value).__name__}).")


def _number_cell(make: partial[RawCell], number: Decimal) -> RawCell:
    return make(RawValueType.NUMBER, format(number, "f"), number=number)


def _formula_text(value: object) -> str:
    """Formula expression as written, e.g. ``=B2*C2``. Shared formulas arrive already
    translated to their cell by openpyxl; array formulas carry their expression in ``text``."""
    if isinstance(value, str):
        return value
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(value, DataTableFormula):
        return _data_table_expression(value)
    raise ExtractionError(f"A formula cell holds an unsupported formula ({type(value).__name__}).")


def _data_table_expression(formula: DataTableFormula) -> str:
    """What-if data tables store only their input cells; Excel displays them as
    ``TABLE(row_input, column_input)``. ``dt2D`` marks two inputs (r1 = row, r2 = column);
    otherwise ``dtr`` says whether the single input r1 is a row or a column input."""
    if _xml_flag(formula.dt2D):
        row_input, column_input = formula.r1, formula.r2
    elif _xml_flag(formula.dtr):
        row_input, column_input = formula.r1, None
    else:
        row_input, column_input = None, formula.r1
    return f"=TABLE({row_input or ''},{column_input or ''})"


def _xml_flag(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true"}


# --------------------------------------------------------------------------- pre-parse scan
def _scan_archive(path: Path, limits: IngestionLimits) -> None:
    """Stream every part of the archive through :class:`_PartScanner` (see the module
    docstring). Parts that are not XML (images, binary parts) are skipped at their first
    syntax error; openpyxl cannot parse those as XML either."""
    budget = _ScanBudget(limits)
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if not entry.is_dir():
                    _scan_part(archive, entry, budget, limits)
    except DefusedXmlException as exc:
        raise ExtractionError(
            "The workbook contains an XML document type declaration or entity, which is refused "
            "to prevent XML attacks."
        ) from exc
    except _READ_FAILURES as exc:
        raise _unreadable(exc) from exc


def _scan_part(
    archive: zipfile.ZipFile, entry: zipfile.ZipInfo, budget: _ScanBudget, limits: IngestionLimits
) -> None:
    parser = DefusedXMLParser(target=_PartScanner(budget, limits), forbid_dtd=True)
    with archive.open(entry) as stream:
        while chunk := stream.read(_SCAN_CHUNK_BYTES):
            budget.consume_bytes(len(chunk))
            try:
                parser.feed(chunk)
            except ParseError:
                return
    with contextlib.suppress(ParseError):
        parser.close()


class _ScanBudget:
    """Workbook-wide totals of the scan: bytes of XML the parsers will process (decompressed
    part sizes plus the text openpyxl re-creates for shared formulas) against
    ``max_uncompressed_bytes``, and the cell objects of all parts against
    ``max_cells_per_workbook``."""

    def __init__(self, limits: IngestionLimits) -> None:
        self._max_bytes = limits.max_uncompressed_bytes
        self._max_cells = limits.max_cells_per_workbook
        self._bytes = 0
        self._cells = 0

    def consume_bytes(self, amount: int) -> None:
        self._bytes += amount
        if self._bytes > self._max_bytes:
            raise ExtractionError(
                f"The workbook expands to more than {self._max_bytes:,} bytes of XML (shared "
                "formulas included); that is above the limit.",
                details={"limit": "max_uncompressed_bytes", "maximum": self._max_bytes},
            )

    def add_cells(self, count: int) -> None:
        self._cells += count
        if self._cells > self._max_cells:
            raise ExtractionError(
                f"The worksheets of the workbook declare more than {self._max_cells:,} cells "
                "together (merged, hyperlinked and commented ranges count every covered cell, "
                "formatted rows one each); that is above the limit per workbook.",
                details={"limit": "max_cells_per_workbook", "maximum": self._max_cells},
            )


class _PartScanner:
    """XML parser target for one archive part; it builds no tree.

    Counts the objects openpyxl will create for the part (cell elements, the full area of every
    merged, hyperlinked or commented range, formatted ``<row>`` elements) against
    ``max_cells_per_sheet`` and the workbook budget, charges the budget with the master
    formula's length for every cell that reuses a shared formula, and measures the text of
    every shared string (``<si>``, phonetic runs excluded, as openpyxl reads it) against
    ``max_cell_chars``.
    """

    def __init__(self, budget: _ScanBudget, limits: IngestionLimits) -> None:
        self._budget = budget
        self._max_cells = limits.max_cells_per_sheet
        self._max_chars = limits.max_cell_chars
        self._cells = 0
        self._shared_formulas: dict[str, int] = {}  # shared index -> master formula length
        self._formula: tuple[str | None, str | None] | None = None  # (t, si) of an open <f>
        self._formula_chars = 0
        self._string_chars: int | None = None  # text of the open <si>; None outside one
        self._in_text = False
        self._phonetic_depth = 0

    def start(self, tag: str, attrib: dict[str, str]) -> None:
        if tag == _CELL_TAG:
            self._add_cells(1)
        elif tag == _ROW_TAG:
            if any(not key.startswith("{") and key not in _PLAIN_ROW_ATTRIBUTES for key in attrib):
                self._add_cells(1)  # a RowDimension object
        elif tag in _RANGE_TAGS:
            self._add_cells(_range_area(attrib.get("ref", "")))
        elif tag == _FORMULA_TAG:
            self._formula = (attrib.get("t"), attrib.get("si"))
            self._formula_chars = 0
        elif tag == _SHARED_STRING_TAG:
            self._string_chars = 0
        elif tag == _TEXT_TAG:
            self._in_text = True
        elif tag == _PHONETIC_TAG:
            self._phonetic_depth += 1

    def data(self, text: str) -> None:
        if self._formula is not None:
            self._formula_chars += len(text)
        if self._string_chars is not None and self._in_text and not self._phonetic_depth:
            self._add_string_chars(len(text))

    def end(self, tag: str) -> None:
        if tag == _FORMULA_TAG:
            self._end_formula()
        elif tag == _SHARED_STRING_TAG:
            self._string_chars = None
        elif tag == _TEXT_TAG:
            self._in_text = False
        elif tag == _PHONETIC_TAG:
            self._phonetic_depth -= 1

    def close(self) -> None:
        return None

    def _end_formula(self) -> None:
        if self._formula is None:
            return
        kind, index = self._formula
        self._formula = None
        if kind != "shared" or index is None:
            return
        master = self._shared_formulas.get(index)
        if master is not None:  # openpyxl translates the master's text for this cell
            self._budget.consume_bytes(master)
        elif self._formula_chars:
            self._shared_formulas[index] = self._formula_chars

    def _add_cells(self, count: int) -> None:
        self._cells += count
        if self._cells > self._max_cells:
            raise ExtractionError(
                f"A worksheet of the workbook declares more than {self._max_cells:,} cells "
                "(merged, hyperlinked and commented ranges count every covered cell, formatted "
                "rows one each); that is above the limit per sheet.",
                details={"limit": "max_cells_per_sheet", "maximum": self._max_cells},
            )
        self._budget.add_cells(count)

    def _add_string_chars(self, count: int) -> None:
        assert self._string_chars is not None  # only called inside <si>
        self._string_chars += count
        if self._string_chars > self._max_chars:
            raise ExtractionError(
                f"The workbook's shared string table holds a text longer than "
                f"{self._max_chars:,} characters, the limit per cell.",
                details={"limit": "max_cell_chars", "maximum": self._max_chars},
            )


def _range_area(ref: str) -> int:
    """Cells covered by a ``ref`` such as ``A1:C3``; whole rows or columns count in full and
    reversed corners count like normal ones, so the result never understates the work."""
    area = 0
    for part in ref.split():
        try:
            min_col, min_row, max_col, max_row = range_boundaries(part)
        except ValueError:
            raise ExtractionError(
                "The workbook contains an invalid cell range reference."
            ) from None
        rows = abs((max_row or _EXCEL_MAX_ROWS) - (min_row or 1)) + 1
        columns = abs((max_col or _EXCEL_MAX_COLUMNS) - (min_col or 1)) + 1
        area += rows * columns
    return area
