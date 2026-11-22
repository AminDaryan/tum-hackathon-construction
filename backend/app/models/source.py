"""Provenance: where a value came from in the original document.

Every canonical cell keeps a :class:`SourceLocation` so a reviewer can always navigate from a
finding back to the original evidence (sheet + A1 cell, CSV record, or PDF page + bounding box).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, computed_field

from app.core.a1 import a1_reference
from app.models.base import FrozenModel


class SourceKind(StrEnum):
    SPREADSHEET = "spreadsheet"
    DELIMITED_TEXT = "delimited_text"
    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    GAEB_XML = "gaeb_xml"  # a GAEB file shown as a table; row/column of that table, XML line
    GAEB_90 = "gaeb_90"  # a GAEB 90 file shown as a table; row/column of that table, file line
    # A Word document: a table of the document (sheet "Table 2", row/column in that table), or
    # its list of item paragraphs shown as a table (line = paragraph number in the document).
    WORD = "word"


class BoundingBox(FrozenModel):
    """Region on a PDF page or image. Origin top-left; ``unit`` states the coordinate space."""

    page_number: int = Field(ge=1)
    x0: float
    y0: float
    x1: float
    y1: float
    unit: Literal["pt", "px", "normalized"] = "pt"


class SourceLocation(FrozenModel):
    kind: SourceKind
    sheet_name: str | None = None
    sheet_index: int | None = Field(default=None, ge=0)
    page_number: int | None = Field(default=None, ge=1)
    table_index: int | None = Field(default=None, ge=0)
    row_number: int | None = Field(default=None, ge=1)  # 1-based row/record in the source
    column_number: int | None = Field(default=None, ge=1)  # 1-based column in the source
    line_number: int | None = Field(default=None, ge=1)  # physical line (CSV), if known
    bbox: BoundingBox | None = None

    @computed_field  # type: ignore[prop-decorator]  # mypy cannot type a decorated property
    @property
    def a1(self) -> str | None:
        """A1 reference for spreadsheet cells, e.g. ``C12``; ``None`` elsewhere."""
        if self.kind is not SourceKind.SPREADSHEET:
            return None
        if self.row_number is None or self.column_number is None:
            return None
        return a1_reference(self.row_number, self.column_number)

    def describe(self) -> str:
        """Human-readable location, e.g. ``Sheet 'LV' cell C12`` or ``CSV record 14, field 3``."""
        if self.kind is SourceKind.SPREADSHEET:
            where = f"sheet '{self.sheet_name}'" if self.sheet_name else "sheet"
            return f"{where} cell {self.a1}" if self.a1 else where
        if self.kind is SourceKind.DELIMITED_TEXT:
            parts = []
            if self.row_number is not None:
                parts.append(f"record {self.row_number}")
            if self.column_number is not None:
                parts.append(f"field {self.column_number}")
            return "CSV " + ", ".join(parts) if parts else "CSV"
        if self.kind is SourceKind.GAEB_XML:
            parts = [f"row {self.row_number}"] if self.row_number is not None else []
            if self.column_number is not None:
                parts.append(f"column {self.column_number}")
            if self.line_number is not None:
                parts.append(f"XML line {self.line_number}")
            return "GAEB " + ", ".join(parts) if parts else "GAEB"
        if self.kind is SourceKind.GAEB_90:
            parts = [f"row {self.row_number}"] if self.row_number is not None else []
            if self.column_number is not None:
                parts.append(f"column {self.column_number}")
            if self.line_number is not None:
                parts.append(f"line {self.line_number}")
            return "GAEB 90 " + ", ".join(parts) if parts else "GAEB 90"
        if self.kind is SourceKind.WORD:
            if self.line_number is not None:  # a bill written as item paragraphs
                return f"Word paragraph {self.line_number}"
            parts = [self.sheet_name or "table"]  # "Word Table 2, row 5, column 3"
            if self.row_number is not None:
                parts.append(f"row {self.row_number}")
            if self.column_number is not None:
                parts.append(f"column {self.column_number}")
            return "Word " + ", ".join(parts)
        page = f"page {self.page_number}" if self.page_number else "page ?"
        return f"{self.kind.value} {page}"
