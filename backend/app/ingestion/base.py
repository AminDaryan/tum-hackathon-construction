"""Raw extraction layer: what a format adapter produces before normalization.

Adapters are format experts and know nothing about domains: they turn bytes into a
:class:`RawWorkbook` of :class:`RawSheet` grids of :class:`RawCell` values with exact source
coordinates. They never evaluate formulas or macros, never follow external links, and never
interpret meaning (headers, totals, units). That is normalization's job.

Plain dataclasses (not Pydantic) keep this transient, high-volume layer fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from app.core.config import IngestionLimits
from app.models.dataset import ExtractionWarning
from app.models.document import DocumentFormat
from app.models.schema import TableDecisions
from app.models.source import BoundingBox, SourceKind


class RawValueType(StrEnum):
    EMPTY = "empty"
    STRING = "string"  # text that still needs parsing (all CSV fields are STRING or EMPTY)
    NUMBER = "number"  # typed numeric value from the source (XLSX); see RawCell.number
    BOOLEAN = "boolean"
    DATETIME = "datetime"  # typed date/time value from the source (XLSX)
    ERROR = "error"  # spreadsheet error literal (#REF!, #DIV/0!, ...)
    UNAVAILABLE = "unavailable"  # formula cell whose cached result is not stored in the file


@dataclass(frozen=True, slots=True)
class RawCell:
    """One source cell.

    Numbers: integers stay exact (``Decimal(int)``; check ``bool`` before ``int``). Binary
    floats from a spreadsheet library become ``Decimal(format(value, ".15g"))``: Excel's own
    15-significant-digit precision, which also removes binary noise from cached formula results
    (``3.3000000000000003`` -> ``3.3``). Never ``Decimal(float)``. A float that is not finite
    is an ERROR cell with text ``#NUM!`` (warning ``non_finite_number``). Text is an ERROR cell
    only when the source itself types it as an error (``t="e"``), never because it looks like
    one (``"#N/A"`` typed as text stays text).

    ``page_number``, ``bbox`` and ``confidence`` are for PDF/OCR adapters (engine-reported
    score, uncalibrated); spreadsheet and delimited-text adapters leave them ``None``.
    """

    row: int  # 1-based source row (CSV: 1-based record number, header record included)
    column: int  # 1-based source column
    value_type: RawValueType
    text: str | None  # source text; for typed XLSX values a canonical string rendering
    number: Decimal | None = None  # exact Decimal for NUMBER cells (never a float)
    boolean: bool | None = None
    temporal: datetime | date | time | None = None
    formula: str | None = None  # formula text, e.g. "=B2*C2"; never evaluated
    number_format: str | None = None
    line_number: int | None = None  # physical line for delimited text, when known
    page_number: int | None = None
    bbox: BoundingBox | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class MergedRange:
    min_row: int
    min_column: int
    max_row: int
    max_column: int


@dataclass(slots=True)
class RawSheet:
    name: str
    index: int  # 0-based position in the workbook
    source_kind: SourceKind
    cells: dict[tuple[int, int], RawCell] = field(default_factory=dict)  # (row, column)
    max_row: int = 0
    max_column: int = 0
    merged_ranges: list[MergedRange] = field(default_factory=list)
    hidden: bool = False  # sheet state hidden or veryHidden
    warnings: list[ExtractionWarning] = field(default_factory=list)
    # Rows and columns hidden in the source (1-based). Hidden content is still extracted:
    # it may belong to a total, so normalization flags it instead of dropping it. Only rows
    # and columns inside the sheet's extent are listed; zero-height rows and zero-width
    # columns count as hidden.
    hidden_rows: set[int] = field(default_factory=set)
    hidden_columns: set[int] = field(default_factory=set)
    row_outline_levels: dict[int, int] = field(default_factory=dict)  # row -> level 1..7
    # Structure the format states itself (GAEB: categories, items, totals). Normalization
    # applies it like reviewer decisions, which win on conflict; spreadsheets leave it None.
    declared: TableDecisions | None = None

    def get(self, row: int, column: int) -> RawCell | None:
        return self.cells.get((row, column))


@dataclass(slots=True)
class RawWorkbook:
    format: DocumentFormat
    adapter_id: str
    adapter_version: str
    sheets: list[RawSheet]
    details: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    warnings: list[ExtractionWarning] = field(default_factory=list)


class IngestionAdapter(Protocol):
    """Format adapter. Implementations must be safe on hostile input and respect ``limits``."""

    adapter_id: str
    adapter_version: str
    formats: frozenset[DocumentFormat]

    def extract(self, path: Path, limits: IngestionLimits) -> RawWorkbook:
        """Read ``path`` (already size/format-checked) into raw grids. Raise
        :class:`app.core.errors.ExtractionError` when the file cannot be read."""
        ...
