"""RawWorkbook builders for normalization tests (no ingestion adapter involved)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.clock import FixedClock
from app.core.ids import SequentialIdFactory
from app.ingestion.base import MergedRange, RawCell, RawSheet, RawValueType, RawWorkbook
from app.models.dataset import Cell, Dataset, Row, RowKind, Table
from app.models.document import DocumentFormat
from app.models.profile import DomainProfile
from app.models.schema import SchemaDecisions
from app.models.source import SourceKind
from app.normalization.builder import NormalizationOptions, build_dataset

Value = str | int | Decimal | bool | date | datetime | RawCell | None


def raw_cell(row: int, column: int, value: Value) -> RawCell | None:
    """A raw cell from a Python value: ``str`` is text to parse, ``int``/``Decimal`` a typed
    number, ``bool`` a boolean, dates are typed dates, ``None`` no cell."""
    if value is None:
        return None
    if isinstance(value, RawCell):
        return value
    if isinstance(value, bool):
        return RawCell(row, column, RawValueType.BOOLEAN, str(value).upper(), boolean=value)
    if isinstance(value, int | Decimal):
        number = Decimal(value)
        return RawCell(row, column, RawValueType.NUMBER, str(number), number=number)
    if isinstance(value, date):
        return RawCell(row, column, RawValueType.DATETIME, value.isoformat(), temporal=value)
    return RawCell(row, column, RawValueType.STRING, value)


def formula(row: int, column: int, expression: str, cached: Decimal | int | None = None) -> RawCell:
    """A formula cell with a cached numeric result, or without one (``cached=None``)."""
    if cached is None:
        return RawCell(row, column, RawValueType.UNAVAILABLE, None, formula=expression)
    number = Decimal(cached)
    return RawCell(row, column, RawValueType.NUMBER, str(number), number=number, formula=expression)


def sheet(
    rows: Sequence[Sequence[Value]],
    *,
    name: str = "LV",
    index: int = 0,
    kind: SourceKind = SourceKind.SPREADSHEET,
    hidden: bool = False,
    merged: Iterable[MergedRange] = (),
    hidden_rows: Iterable[int] = (),
    hidden_columns: Iterable[int] = (),
    outline: dict[int, int] | None = None,
    first_row: int = 1,
) -> RawSheet:
    cells: dict[tuple[int, int], RawCell] = {}
    for r, values in enumerate(rows, start=first_row):
        for c, value in enumerate(values, start=1):
            cell = raw_cell(r, c, value)
            if cell is not None:
                cells[(cell.row, cell.column)] = cell
    return RawSheet(
        name=name,
        index=index,
        source_kind=kind,
        cells=cells,
        max_row=first_row + len(rows) - 1,
        max_column=max((len(v) for v in rows), default=0),
        merged_ranges=list(merged),
        hidden=hidden,
        hidden_rows=set(hidden_rows),
        hidden_columns=set(hidden_columns),
        row_outline_levels=dict(outline or {}),
    )


def workbook(*sheets: RawSheet, fmt: DocumentFormat = DocumentFormat.XLSX) -> RawWorkbook:
    return RawWorkbook(format=fmt, adapter_id="test", adapter_version="0", sheets=list(sheets))


def normalize(
    raw: RawWorkbook,
    profile: DomainProfile,
    *,
    decisions: SchemaDecisions | None = None,
    options: NormalizationOptions | None = None,
) -> Dataset:
    return build_dataset(
        raw,
        profile=profile,
        document_id="doc_000001",
        ids=SequentialIdFactory(),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        options=options,
        decisions=decisions,
    )


def by_source_row(table: Table) -> dict[int, Row]:
    return {row.source_row_number: row for row in table.rows}


def kinds(table: Table) -> dict[int, RowKind]:
    return {row.source_row_number: row.kind for row in table.rows}


def cell(table: Table, row: int, field_id: str) -> Cell:
    column = table.column_for_field(field_id)
    assert column is not None, f"{field_id} is not mapped"
    return by_source_row(table)[row].cells[column.column_id]


def codes(dataset: Dataset) -> list[str]:
    return [w.code for w in dataset.extraction.warnings]


GERMAN_LV: list[list[Value]] = [
    ["Leistungsverzeichnis Neubau Halle 3"],
    ["Projekt 2026-114"],
    [],
    ["OZ", "Kurztext", "Menge", "ME", "EP", "GP"],
    ["01", "Titel 01 Erdarbeiten"],
    ["01.01", "Untertitel Aushub"],
    ["01.01.0010", "Oberboden abtragen", "1.250,50", "m2", "4,20", "5.252,10"],
    [None, "inkl. Abfuhr und Entsorgung"],
    ["01.01.0020", "Baugrube ausheben", "380", "m3", "18,50", "7.030,00"],
    [None, "Summe 01.01", None, None, None, "12.282,10"],
    ["01.02", "Untertitel Verfüllung"],
    ["01.02.0010", "Verfüllen mit Kies", "120", "m3", "32,00", "3.840,00"],
    ["01.02.0020", "Bedarfsposition Wasserhaltung", "1", "psch", "1.500,00", "1.500,00"],
    ["01.02.0030", "Bodenaustausch", "50", "m3", "40,00", "nur EP"],
    [None, "Summe 01.02", None, None, None, "3.840,00"],
    [None, "Summe Titel 01", None, None, None, "16.122,10"],
    [None, "Gesamtsumme netto", None, None, None, "16.122,10"],
    [None, "zzgl. 19 % MwSt.", None, None, None, "3.063,20"],
    [None, "Gesamtsumme brutto", None, None, None, "19.185,30"],
]

ENGLISH_BOQ: list[list[Value]] = [
    ["Item", "Description", "Qty", "Unit", "Rate", "Amount"],
    [None, "Section 1 Groundworks"],
    ["1.1", "Excavate topsoil", 250, "m2", Decimal("4.20"), Decimal("1050.00")],
    ["1.2", "Disposal off site", 300, "m3", Decimal("12.00"), Decimal("3600.00")],
    [None, "Subtotal", None, None, None, Decimal("4650.00")],
    [None, "Section 2 Concrete"],
    ["2.1", "Section of wall, C30/37", 12, "m3", Decimal("150.00"), Decimal("1800.00")],
    ["2.2", "Alternative item: precast wall", 12, "m3", Decimal("170.00"), Decimal("2040.00")],
    [None, "Total carried to collection", None, None, None, Decimal("1800.00")],
    [None, "Grand total", None, None, None, Decimal("6450.00")],
    [None, "VAT 20%", None, None, None, Decimal("1290.00")],
    [None, "Total incl. VAT", None, None, None, Decimal("7740.00")],
]
