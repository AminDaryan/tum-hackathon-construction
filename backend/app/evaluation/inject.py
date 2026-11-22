"""Plant benchmark errors into real bills of quantities, in memory (``--inject-into``).

Each ``.xlsx`` and ``.csv`` file directly in the folder is read and uploaded into a temporary
workbench on in-memory storage, through the product's own path (security checks, extraction,
normalization). The errors are then planted into a copy of the **canonical dataset in memory**,
stored as the next revision of that dataset (``parent_revision`` is the revision as read). The
file is never changed and nothing is written into the folder: the planted errors exist only in
that in-memory revision, and the temporary workbench, with the copy of the upload it holds, is
deleted when the run ends. The validation runs on both revisions, so the report tells what a
bill already held from what planting added.

Planting follows the kinds of the ``boq`` corpus (:mod:`app.evaluation.boq`) on canonical rows.
Errors go only into item rows that count toward the totals and whose quantity, unit price and
line total agree, one error per row, the rows it compares with left alone. A changed line
total is carried into the totals that contain it: the subtotals that close a section the row
is in, the nearest subtotal after it whose section is not established, the net total after
it, the tax (at the rate its label gives, else in proportion) and the gross total. So only the
check named for a kind should find it, as in the generated corpus. A kind that no row of a
bill fits is left for the next bill; the report says why a kind was not planted at all.

Nothing of a bill's contents is logged or printed: the command prints counts per kind, and
the report (``inject-report.json`` and ``inject-report.md``, with the findings, which name rows
and may quote values) is written only to the output directory, which must lie outside the
folder. Every number carries :data:`app.evaluation.boq_report.LABEL`: the errors are planted,
so the recall says nothing about the errors a bill really holds.
"""

from __future__ import annotations

import json
import random
import re
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from app.core.errors import WorkbenchError
from app.core.ids import IdPrefix
from app.evaluation import boq_report
from app.evaluation.boq import near_text
from app.evaluation.boq_report import LABEL
from app.evaluation.prices import CENT, OTHER_DIMENSION, UNITS, UNKNOWN_UNITS, Language
from app.evaluation.runner import benchmark_workbench, signal_checks
from app.evaluation.scoring import DocumentResult, findings_of, score_document
from app.evaluation.synthetic import (
    BOQ_MAX_ERRORS,
    BOQ_SEED,
    ERROR_FIELD,
    EXCLUSIVE,
    EXPECTED_RULES,
    ErrorKind,
    GroundTruth,
    SyntheticDocument,
    corrupt,
    not_a_number,
)
from app.models import cell_rules
from app.models.dataset import Cell, Dataset, Row, RowKind, Table
from app.models.issue import ValidationIssue
from app.models.values import NumberValue, TextValue
from app.repositories.base import IssueQuery
from app.services import documents, runs
from app.services.workbench import Workbench

SUFFIXES = (".xlsx", ".csv")
MEASURED = frozenset({"m", "m2", "m3", "t"})
TOTAL_LEVEL = (ErrorKind.SUBTOTAL, ErrorKind.NET_TOTAL, ErrorKind.TAX)
_THICKNESS = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*cm\b")
_PERCENT = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
_LAST_NUMBER = re.compile(r"(\d+)(\D*)$")
_GERMAN_HEADERS = ("menge", "einheit", "preis", "kurztext", "betrag", "leistung", "bezeichnung")
_ROW_LEVEL = "row"

# Why a kind found no row in any bill (the default: no row fits the general conditions).
NEEDS: dict[ErrorKind, str] = {
    ErrorKind.INCONSISTENT_RATE: "a position that repeats with the same text and unit",
    ErrorKind.QUANTITY_DECIMAL_SLIP: "a measured position repeated with the same text and unit",
    ErrorKind.QUANTITY_UNIT_SLIP: "a position in m repeated with the same text and unit",
    ErrorKind.PRICE_PER_WRONG_UNIT: "a position in m3 whose text gives a thickness in cm",
    ErrorKind.WRONG_RATE_COPIED: "two positions in one unit whose prices differ by half or more",
    ErrorKind.HIGH_CONTINGENCY_PRICE: "a priced position that does not count toward the totals",
    ErrorKind.MISPLACED_POSITION: "two sections under one parent, with numbered item codes",
    ErrorKind.CODE_OUTSIDE_SECTION: "two coded sections at one level, with item codes under them",
    ErrorKind.COMPONENT_SUM_ERROR: (
        "unit price component columns mapped by a reviewer (no header maps them, so a bill "
        "read here has none)"
    ),
    ErrorKind.DUPLICATE_POSITION: "a section whose item codes are numbered",
    ErrorKind.NEAR_DUPLICATE_POSITION: "a section whose item codes are numbered",
    ErrorKind.SUBTOTAL: "a subtotal that closes a section",
    ErrorKind.NET_TOTAL: "a net total",
    ErrorKind.TAX: "a tax row below the net total",
    ErrorKind.MISSING_PRICE: "a measured position without unit price components",
}
GENERAL_NEED = "a priced position whose quantity, unit price and line total agree"


@dataclass(frozen=True)
class InjectConfig:
    seed: int = BOQ_SEED
    max_errors: int = BOQ_MAX_ERRORS  # per bill
    kinds: tuple[ErrorKind, ...] = tuple(ErrorKind)
    k: int = 10
    profile_id: str = "boq"


@dataclass
class _Planted:
    error_id: str
    kind: ErrorKind
    target: str  # row id
    field: str | None
    related: list[str]  # row ids
    change: str


@dataclass
class _Sheet:
    """The table being planted into, row by row, and what planting has done to it."""

    table: Table
    rows: list[Row]
    columns: dict[str, str]  # field id -> column id
    language: Language
    rng: random.Random
    new_row_id: Callable[[], str]
    prefix: str
    next_source_row: int
    used: set[str] = field(default_factory=set)
    planted: list[_Planted] = field(default_factory=list)

    def index(self, row_id: str) -> int:
        return next(i for i, row in enumerate(self.rows) if row.row_id == row_id)

    def number(self, row: Row, field_id: str) -> Decimal | None:
        column = self.columns.get(field_id)
        value = row.cells[column].parsed_value if column is not None else None
        return value.value if isinstance(value, NumberValue) else None

    def text(self, row: Row, field_id: str) -> str | None:
        column = self.columns.get(field_id)
        value = row.cells[column].normalized_value if column is not None else None
        return value.value if isinstance(value, TextValue) else None

    def cell(self, row: Row, field_id: str) -> Cell:
        return row.cells[self.columns[field_id]]

    def with_cell(self, index: int, field_id: str, cell: Cell) -> None:
        row = self.rows[index]
        self.rows[index] = row.evolve(cells={**row.cells, self.columns[field_id]: cell})

    def set_number(self, index: int, field_id: str, value: Decimal) -> None:
        old = self.cell(self.rows[index], field_id)
        previous = old.parsed_value
        currency = previous.currency if isinstance(previous, NumberValue) else None
        cell = cell_rules.number_cell(
            NumberValue(value=value, currency=currency),
            old.source,
            raw=format(value, "f"),
            number_format=old.number_format,
        )
        self.with_cell(index, field_id, cell)

    def record(
        self,
        kind: ErrorKind,
        target: Row,
        change: str,
        *,
        related: Sequence[Row] = (),
        field_id: str | None = _ROW_LEVEL,
    ) -> _Planted:
        planted = _Planted(
            error_id=f"{self.prefix}-e{len(self.planted) + 1}",
            kind=kind,
            target=target.row_id,
            field=ERROR_FIELD[kind] if field_id == _ROW_LEVEL else field_id,
            related=[row.row_id for row in related],
            change=change,
        )
        self.planted.append(planted)
        self.used.update({target.row_id, *planted.related})
        return planted

    def copy_of(self, row: Row) -> Row:
        """``row`` as a new row (a new id, a source row number after the file's last row)."""
        number = self.next_source_row
        self.next_source_row += 1
        cells = {
            column: cell.evolve(source=cell.source.evolve(row_number=number))
            for column, cell in row.cells.items()
        }
        return row.evolve(row_id=self.new_row_id(), source_row_number=number, cells=cells)


# Rows ---------------------------------------------------------------------------------------


def _counted(row: Row) -> bool:
    return (
        row.kind is RowKind.ITEM
        and not row.excluded
        and row.classification.counts_toward_totals is True
        and row.classification.not_counted_above_section_id is None
    )


def _consistent(sheet: _Sheet, row: Row) -> bool:
    quantity = sheet.number(row, "quantity")
    price = sheet.number(row, "unit_price")
    total = sheet.number(row, "line_total")
    if quantity is None or price is None or total is None or quantity <= 0 or price <= 0:
        return False
    return abs(quantity * price - total) <= CENT


def _priced(sheet: _Sheet) -> list[Row]:
    """The rows errors may go into: counted items whose numbers agree, not used yet."""
    return [
        row
        for row in sheet.rows
        if _counted(row) and _consistent(sheet, row) and row.row_id not in sheet.used
    ]


def _same_work(sheet: _Sheet, row: Row) -> tuple[str, str] | None:
    text, unit = sheet.text(row, "description"), sheet.text(row, "unit")
    return None if text is None or unit is None else (text.casefold(), unit)


def _identical(sheet: _Sheet, row: Row) -> list[Row]:
    """The other items with the same text and unit."""
    key = _same_work(sheet, row)
    return [
        other
        for other in sheet.rows
        if other.kind is RowKind.ITEM
        and other is not row
        and key
        and _same_work(sheet, other) == key
    ]


def _free(sheet: _Sheet, row: Row) -> bool:
    return not any(other.row_id in sheet.used for other in _identical(sheet, row))


def _section(row: Row) -> str | None:
    return row.section_path[-1] if row.section_path else None


def _has_continuation(sheet: _Sheet, row: Row) -> bool:
    return any(other.belongs_to_row_id == row.row_id for other in sheet.rows)


# Totals -------------------------------------------------------------------------------------


def _rate(sheet: _Sheet, row: Row) -> Decimal | None:
    for cell in row.cells.values():
        if isinstance(cell.normalized_value, TextValue):
            match = _PERCENT.search(cell.normalized_value.value)
            if match:
                return Decimal(match.group(1).replace(",", "."))
    return None


def _carry(sheet: _Sheet, index: int, delta: Decimal) -> None:
    """Add ``delta``, a change of the line total of the counted item at ``index``, to the totals
    that contain it (see the module docstring)."""
    if not delta:
        return
    path = set(sheet.rows[index].section_path)
    unscoped = False
    net_index: int | None = None
    for j in range(index + 1, len(sheet.rows)):
        row = sheet.rows[j]
        amount = sheet.number(row, "line_total")
        if row.excluded or amount is None:
            continue
        if row.kind is RowKind.SUBTOTAL and row.closes_section_id is not None:
            if row.closes_section_id in path:
                sheet.set_number(j, "line_total", amount + delta)
        elif row.kind is RowKind.SUBTOTAL and not unscoped:
            unscoped = True
            sheet.set_number(j, "line_total", amount + delta)
        elif row.kind is RowKind.GRAND_TOTAL:
            sheet.set_number(j, "line_total", amount + delta)
            net_index = j
            break
    if net_index is not None:
        _carry_tax(sheet, net_index, delta)


def _carry_tax(sheet: _Sheet, net_index: int, delta: Decimal) -> None:
    net = sheet.number(sheet.rows[net_index], "line_total")
    assert net is not None
    tax_delta = Decimal(0)
    for j in range(net_index + 1, len(sheet.rows)):
        row = sheet.rows[j]
        amount = sheet.number(row, "line_total")
        if row.excluded or amount is None:
            continue
        if row.kind is RowKind.TAX and not tax_delta:
            rate = _rate(sheet, row)
            if rate is not None:
                new = (net * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
            elif net - delta:
                new = (amount * net / (net - delta)).quantize(CENT, rounding=ROUND_HALF_UP)
            else:
                new = amount
            tax_delta = new - amount
            sheet.set_number(j, "line_total", new)
        elif row.kind is RowKind.GROSS_TOTAL:
            sheet.set_number(j, "line_total", amount + delta + tax_delta)
            return
        elif row.kind is RowKind.GRAND_TOTAL:
            return


def _reprice(sheet: _Sheet, index: int, price: Decimal) -> None:
    row = sheet.rows[index]
    quantity, old = sheet.number(row, "quantity"), sheet.number(row, "line_total")
    assert quantity is not None
    assert old is not None
    total = (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)
    sheet.set_number(index, "unit_price", price)
    sheet.set_number(index, "line_total", total)
    if _counted(row):
        _carry(sheet, index, total - old)


def _requantify(sheet: _Sheet, index: int, quantity: Decimal) -> None:
    row = sheet.rows[index]
    price, old = sheet.number(row, "unit_price"), sheet.number(row, "line_total")
    assert price is not None
    assert old is not None
    total = (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)
    sheet.set_number(index, "quantity", quantity)
    sheet.set_number(index, "line_total", total)
    _carry(sheet, index, total - old)


def _retotal(sheet: _Sheet, index: int, total: Decimal) -> None:
    old = sheet.number(sheet.rows[index], "line_total")
    assert old is not None
    sheet.set_number(index, "line_total", total)
    _carry(sheet, index, total - old)


# Planters: each takes a candidate row and plants into it, or returns None -------------------

Planter = Callable[[_Sheet, Row], _Planted | None]


def _factor(rng: random.Random, low: float, high: float) -> Decimal:
    return Decimal(f"{rng.uniform(low, high):.4f}")


def _price(sheet: _Sheet, row: Row) -> Decimal:
    price = sheet.number(row, "unit_price")
    assert price is not None
    return price


def _price_decimal_slip(sheet: _Sheet, row: Row) -> _Planted | None:
    factor = sheet.rng.choice((Decimal(10), Decimal("0.1"), Decimal(100)))
    price = (_price(sheet, row) * factor).quantize(CENT, rounding=ROUND_HALF_UP)
    if price < CENT or price == _price(sheet, row) or not _free(sheet, row):
        return None
    planted = sheet.record(
        ErrorKind.PRICE_DECIMAL_SLIP,
        row,
        f"unit price ×{factor.normalize()}",
        related=_identical(sheet, row),
    )
    _reprice(sheet, sheet.index(row.row_id), price)
    return planted


def _price_digit_swap(sheet: _Sheet, row: Row) -> _Planted | None:
    price = _price(sheet, row)
    wrong = corrupt(sheet.rng, price)
    if wrong == price + 100 or not _free(sheet, row):  # no two different digits to swap
        return None
    planted = sheet.record(
        ErrorKind.PRICE_DIGIT_SWAP,
        row,
        "two adjacent digits of the unit price swapped",
        related=_identical(sheet, row),
    )
    _reprice(sheet, sheet.index(row.row_id), wrong)
    return planted


def _inconsistent_rate(sheet: _Sheet, row: Row) -> _Planted | None:
    same = _identical(sheet, row)
    if not same or not _free(sheet, row):
        return None
    high = sheet.rng.random() < 0.5
    factor = _factor(sheet.rng, 1.25, 1.60) if high else _factor(sheet.rng, 0.60, 0.75)
    price = (_price(sheet, row) * factor).quantize(CENT, rounding=ROUND_HALF_UP)
    planted = sheet.record(
        ErrorKind.INCONSISTENT_RATE,
        row,
        f"unit price ×{factor} against the same position elsewhere",
        related=same,
    )
    _reprice(sheet, sheet.index(row.row_id), price)
    return planted


def _wrong_rate_copied(sheet: _Sheet, row: Row) -> _Planted | None:
    price, unit = _price(sheet, row), sheet.text(row, "unit")
    key = _same_work(sheet, row)
    others = [
        other
        for other in sheet.rows
        if other.kind is RowKind.ITEM
        and sheet.text(other, "unit") == unit
        and _same_work(sheet, other) != key
        and (other_price := sheet.number(other, "unit_price")) is not None
        and other_price > 0
        and max(other_price, price) >= Decimal("1.5") * min(other_price, price)
    ]
    if not others or not _free(sheet, row):
        return None
    source = sheet.rng.choice(others)
    planted = sheet.record(
        ErrorKind.WRONG_RATE_COPIED,
        row,
        f"unit price of row {source.source_row_number} copied",
        related=_identical(sheet, row),
    )
    _reprice(sheet, sheet.index(row.row_id), _price(sheet, source))
    return planted


def _placeholder_price(sheet: _Sheet, row: Row) -> _Planted | None:
    price = sheet.rng.choice((CENT, Decimal("0.00")))
    planted = sheet.record(ErrorKind.PLACEHOLDER_PRICE, row, f"unit price set to {price}")
    _reprice(sheet, sheet.index(row.row_id), price)
    return planted


def _high_contingency_price(sheet: _Sheet, row: Row) -> _Planted | None:
    factor = _factor(sheet.rng, 2.0, 3.0)
    price = (_price(sheet, row) * factor).quantize(CENT, rounding=ROUND_HALF_UP)
    planted = sheet.record(
        ErrorKind.HIGH_CONTINGENCY_PRICE, row, f"unit price of a non-counted position ×{factor}"
    )
    _reprice(sheet, sheet.index(row.row_id), price)
    return planted


def _quantity(sheet: _Sheet, row: Row) -> Decimal:
    quantity = sheet.number(row, "quantity")
    assert quantity is not None
    return quantity


def _quantity_decimal_slip(sheet: _Sheet, row: Row) -> _Planted | None:
    same = _identical(sheet, row)
    if sheet.text(row, "unit") not in MEASURED or not same or not _free(sheet, row):
        return None
    factor = sheet.rng.choice((10, 100, 1000))
    planted = sheet.record(
        ErrorKind.QUANTITY_DECIMAL_SLIP, row, f"quantity ×{factor}", related=same
    )
    _requantify(sheet, sheet.index(row.row_id), _quantity(sheet, row) * factor)
    return planted


def _quantity_unit_slip(sheet: _Sheet, row: Row) -> _Planted | None:
    same = _identical(sheet, row)
    if sheet.text(row, "unit") != "m" or not same or not _free(sheet, row):
        return None
    factor, unit = sheet.rng.choice(((100, "cm"), (1000, "mm")))
    planted = sheet.record(
        ErrorKind.QUANTITY_UNIT_SLIP, row, f"quantity in {unit}, unit still m", related=same
    )
    _requantify(sheet, sheet.index(row.row_id), _quantity(sheet, row) * factor)
    return planted


def _price_per_wrong_unit(sheet: _Sheet, row: Row) -> _Planted | None:
    match = _THICKNESS.search(sheet.text(row, "description") or "")
    if sheet.text(row, "unit") != "m3" or match is None or not _free(sheet, row):
        return None
    metres = Decimal(match.group(1).replace(",", ".")) / 100
    if not Decimal("0.05") <= metres <= Decimal("0.6"):
        return None
    price = (_price(sheet, row) * metres).quantize(CENT, rounding=ROUND_HALF_UP)
    if price < CENT:
        return None
    planted = sheet.record(
        ErrorKind.PRICE_PER_WRONG_UNIT,
        row,
        "price per m2 written in a m3 position",
        related=_identical(sheet, row),
    )
    _reprice(sheet, sheet.index(row.row_id), price)
    return planted


def _wrong_unit(sheet: _Sheet, row: Row) -> _Planted | None:
    unit = sheet.text(row, "unit")
    if unit not in OTHER_DIMENSION or not _free(sheet, row):
        return None
    other = OTHER_DIMENSION[unit]
    raw = UNITS[other].text(sheet.language)
    planted = sheet.record(ErrorKind.WRONG_UNIT, row, f"unit {unit} written as {other}")
    old = sheet.cell(row, "unit")
    sheet.with_cell(sheet.index(row.row_id), "unit", cell_rules.unit_cell(raw, old.source, other))
    return planted


def _unknown_unit(sheet: _Sheet, row: Row) -> _Planted | None:
    raw = sheet.rng.choice(UNKNOWN_UNITS[sheet.language])
    planted = sheet.record(ErrorKind.UNKNOWN_UNIT, row, "unit written as one the profile lacks")
    old = sheet.cell(row, "unit")
    sheet.with_cell(sheet.index(row.row_id), "unit", cell_rules.unit_cell(raw, old.source, None))
    return planted


def _missing_price(sheet: _Sheet, row: Row) -> _Planted | None:
    components = [f for f in sheet.columns if f.startswith("unit_price_component")]
    if sheet.text(row, "unit") not in MEASURED or components:
        return None
    planted = sheet.record(ErrorKind.MISSING_PRICE, row, "unit price left empty")
    old = sheet.cell(row, "unit_price")
    sheet.with_cell(sheet.index(row.row_id), "unit_price", cell_rules.empty_cell(old.source))
    return planted


def _invalid_quantity(sheet: _Sheet, row: Row) -> _Planted | None:
    text = not_a_number(_quantity(sheet, row), german=sheet.language == "de")
    planted = sheet.record(ErrorKind.INVALID_QUANTITY, row, "quantity misread as text")
    old = sheet.cell(row, "quantity")
    cell = cell_rules.failed_cell(text, old.source, "Not a number.")
    sheet.with_cell(sheet.index(row.row_id), "quantity", cell)
    return planted


def _line_total(sheet: _Sheet, row: Row) -> _Planted | None:
    total = sheet.number(row, "line_total")
    assert total is not None
    wrong = corrupt(sheet.rng, total)
    if wrong == total + 100:
        return None
    planted = sheet.record(
        ErrorKind.LINE_TOTAL, row, "two adjacent digits of the line total swapped"
    )
    _retotal(sheet, sheet.index(row.row_id), wrong)
    return planted


def _line_total_slip(sheet: _Sheet, row: Row) -> _Planted | None:
    total = sheet.number(row, "line_total")
    assert total is not None
    planted = sheet.record(ErrorKind.LINE_TOTAL_SLIP, row, "line total ×10")
    _retotal(sheet, sheet.index(row.row_id), total * 10)
    return planted


def _component_sum_error(sheet: _Sheet, row: Row) -> _Planted | None:
    fields = sorted(f for f in sheet.columns if f.startswith("unit_price_component"))
    values = [sheet.number(row, f) for f in fields]
    if not fields or any(v is None or v <= 0 for v in values):
        return None
    if sum(v for v in values if v is not None) != _price(sheet, row):
        return None
    k = sheet.rng.randrange(len(fields))
    value = values[k]
    assert value is not None
    sign = 1 if sheet.rng.random() < 0.5 else -1
    wrong = (value * (1 + sign * _factor(sheet.rng, 0.01, 0.20))).quantize(CENT)
    if wrong == value or wrong < CENT:
        return None
    planted = sheet.record(
        ErrorKind.COMPONENT_SUM_ERROR,
        row,
        f"unit price component {k + 1} changed; the components no longer add up",
        field_id=fields[k],
    )
    sheet.set_number(sheet.index(row.row_id), fields[k], wrong)
    return planted


def _codes(sheet: _Sheet) -> set[str]:
    return {code for row in sheet.rows if (code := sheet.text(row, "item_code"))}


def _next_code(sheet: _Sheet, section: str | None) -> str | None:
    """The code after the last item code of ``section``, in its step, not taken yet."""
    codes = [
        code
        for row in sheet.rows
        if row.kind is RowKind.ITEM
        and _section(row) == section
        and (code := sheet.text(row, "item_code"))
    ]
    match = _LAST_NUMBER.search(codes[-1]) if codes else None
    if match is None:
        return None
    previous = _LAST_NUMBER.search(codes[-2]) if len(codes) > 1 else None
    number = int(match.group(1))
    step = max(1, number - int(previous.group(1))) if previous else 1
    taken = _codes(sheet)
    for _ in range(100):
        number += step
        code = codes[-1][: match.start(1)] + str(number).zfill(len(match.group(1)))
        code += match.group(2)
        if code not in taken:
            return code
    return None


def _end_of(sheet: _Sheet, section: str | None) -> int:
    """The index after the last item of ``section`` (and the text rows that continue it)."""
    last = max(
        i
        for i, row in enumerate(sheet.rows)
        if row.kind is RowKind.ITEM and _section(row) == section
    )
    index = last + 1
    while (
        index < len(sheet.rows) and sheet.rows[index].belongs_to_row_id == sheet.rows[last].row_id
    ):
        index += 1
    return index


def _insert(sheet: _Sheet, index: int, row: Row) -> None:
    sheet.rows.insert(index, row)
    if _counted(row):
        total = sheet.number(row, "line_total")
        assert total is not None
        _carry(sheet, index, total)


def _duplicate_row(sheet: _Sheet, row: Row) -> _Planted | None:
    copy = sheet.copy_of(row)
    planted = sheet.record(
        ErrorKind.DUPLICATE_ROW, copy, "position entered twice, code included", related=[row]
    )
    index = sheet.index(row.row_id) + 1
    while index < len(sheet.rows) and sheet.rows[index].belongs_to_row_id == row.row_id:
        index += 1
    _insert(sheet, index, copy)
    return planted


def _copy_at_end(sheet: _Sheet, row: Row, kind: ErrorKind, change: str) -> _Planted | None:
    code = _next_code(sheet, _section(row))
    if code is None or not _free(sheet, row):
        return None
    copy = sheet.copy_of(row)
    copy = copy.evolve(
        cells={
            **copy.cells,
            sheet.columns["item_code"]: cell_rules.text_cell(
                code, sheet.cell(copy, "item_code").source
            ),
        }
    )
    planted = sheet.record(kind, copy, change, related=[row, *_identical(sheet, row)])
    index = _end_of(sheet, _section(row))
    _insert(sheet, index, copy)
    return planted


def _duplicate_position(sheet: _Sheet, row: Row) -> _Planted | None:
    return _copy_at_end(
        sheet, row, ErrorKind.DUPLICATE_POSITION, "position entered again under the next code"
    )


def _near(rng: random.Random, text: str, language: Language) -> str | None:
    """:func:`near_text`, or None when the text offers no small change (no comma-separated
    parts, no abbreviation and no two different adjacent letters, as in "X 1")."""
    try:
        return near_text(rng, text, language)
    except IndexError:  # near_text drew from an empty list of changes
        return None


def _near_duplicate_position(sheet: _Sheet, row: Row) -> _Planted | None:
    text = sheet.text(row, "description")
    changed = _near(sheet.rng, text, sheet.language) if text else None
    if changed is None:
        return None
    planted = _copy_at_end(
        sheet,
        row,
        ErrorKind.NEAR_DUPLICATE_POSITION,
        "position entered again under the next code, its text slightly changed",
    )
    if planted is None:
        return None
    index = sheet.index(planted.target)
    source = sheet.cell(sheet.rows[index], "description").source
    sheet.with_cell(index, "description", cell_rules.text_cell(changed, source))
    if sheet.rng.random() < 0.5:
        quantity = _quantity(sheet, sheet.rows[index]) * _factor(sheet.rng, 0.9, 1.1)
        places = (
            Decimal(1) if _quantity(sheet, row) == _quantity(sheet, row).to_integral() else CENT
        )
        _requantify(sheet, index, max(places, quantity.quantize(places, rounding=ROUND_HALF_UP)))
    return planted


def _sections(sheet: _Sheet) -> dict[str, Row]:
    return {row.row_id: row for row in sheet.rows if row.kind is RowKind.SECTION}


def _misplaced_position(sheet: _Sheet, row: Row) -> _Planted | None:
    own = _section(row)
    sections = _sections(sheet)
    if own is None or own not in sections or _has_continuation(sheet, row):
        return None
    siblings = [
        section_id
        for section_id, section in sections.items()
        if section_id != own
        and section.section_path == sections[own].section_path
        and any(_section(other) == section_id for other in sheet.rows if other.kind is RowKind.ITEM)
    ]
    if not siblings or not _free(sheet, row):
        return None
    target = sheet.rng.choice(siblings)
    code = _next_code(sheet, target)
    if code is None:
        return None
    planted = sheet.record(
        ErrorKind.MISPLACED_POSITION, row, "position moved to the end of another section"
    )
    index = sheet.index(row.row_id)
    total = sheet.number(row, "line_total")
    assert total is not None
    _carry(sheet, index, -total)
    moved = sheet.rows.pop(index)
    moved = moved.evolve(
        section_path=[*sections[target].section_path, target],
        cells={
            **moved.cells,
            sheet.columns["item_code"]: cell_rules.text_cell(
                code, sheet.cell(moved, "item_code").source
            ),
        },
    )
    _insert(sheet, _end_of(sheet, target), moved)
    return planted


def _code_outside_section(sheet: _Sheet, row: Row) -> _Planted | None:
    own, code = _section(row), sheet.text(row, "item_code")
    sections = _sections(sheet)
    own_code = sections[own].classification.code if own in sections else None
    if own is None or not code or not own_code or not code.startswith(own_code):
        return None
    others = [
        section
        for section_id, section in sections.items()
        if section_id != own
        and section.classification.code
        and len(section.section_path) == len(sections[own].section_path)
    ]
    taken = _codes(sheet)
    choices = [
        (section, section.classification.code + code[len(own_code) :])
        for section in others
        if section.classification.code
        and section.classification.code + code[len(own_code) :] not in taken
    ]
    if not choices or not _free(sheet, row):
        return None
    _, wrong = sheet.rng.choice(choices)
    index = sheet.index(row.row_id)
    following = [
        other
        for other in sheet.rows[index + 1 :]
        if other.kind is RowKind.ITEM and _section(other) == own
    ][:1]
    related = following if wrong > code else []
    planted = sheet.record(
        ErrorKind.CODE_OUTSIDE_SECTION,
        row,
        "item code given the prefix of another section",
        related=related,
    )
    source = sheet.cell(row, "item_code").source
    sheet.with_cell(index, "item_code", cell_rules.text_cell(wrong, source))
    return planted


PLANTERS: dict[ErrorKind, Planter] = {
    ErrorKind.LINE_TOTAL: _line_total,
    ErrorKind.UNKNOWN_UNIT: _unknown_unit,
    ErrorKind.DUPLICATE_ROW: _duplicate_row,
    ErrorKind.MISSING_PRICE: _missing_price,
    ErrorKind.INVALID_QUANTITY: _invalid_quantity,
    ErrorKind.PRICE_DECIMAL_SLIP: _price_decimal_slip,
    ErrorKind.PRICE_DIGIT_SWAP: _price_digit_swap,
    ErrorKind.INCONSISTENT_RATE: _inconsistent_rate,
    ErrorKind.WRONG_RATE_COPIED: _wrong_rate_copied,
    ErrorKind.PLACEHOLDER_PRICE: _placeholder_price,
    ErrorKind.HIGH_CONTINGENCY_PRICE: _high_contingency_price,
    ErrorKind.QUANTITY_DECIMAL_SLIP: _quantity_decimal_slip,
    ErrorKind.QUANTITY_UNIT_SLIP: _quantity_unit_slip,
    ErrorKind.PRICE_PER_WRONG_UNIT: _price_per_wrong_unit,
    ErrorKind.WRONG_UNIT: _wrong_unit,
    ErrorKind.MISPLACED_POSITION: _misplaced_position,
    ErrorKind.CODE_OUTSIDE_SECTION: _code_outside_section,
    ErrorKind.LINE_TOTAL_SLIP: _line_total_slip,
    ErrorKind.COMPONENT_SUM_ERROR: _component_sum_error,
    ErrorKind.DUPLICATE_POSITION: _duplicate_position,
    ErrorKind.NEAR_DUPLICATE_POSITION: _near_duplicate_position,
}


def _candidates(sheet: _Sheet, kind: ErrorKind) -> list[Row]:
    if kind is ErrorKind.HIGH_CONTINGENCY_PRICE:
        return [
            row
            for row in sheet.rows
            if row.kind is RowKind.ITEM
            and not row.excluded
            and row.classification.counts_toward_totals is False
            and _consistent(sheet, row)
            and row.row_id not in sheet.used
        ]
    return _priced(sheet)


def _total_rows(sheet: _Sheet, kind: RowKind) -> list[Row]:
    return [
        row
        for row in sheet.rows
        if row.kind is kind
        and not row.excluded
        and sheet.number(row, "line_total") is not None
        and row.row_id not in sheet.used
    ]


def _after(sheet: _Sheet, row: Row, kind: RowKind) -> list[Row]:
    index = sheet.index(row.row_id)
    return [other for other in sheet.rows[index + 1 :] if other.kind is kind][:1]


def _plant_total(sheet: _Sheet, kind: ErrorKind) -> _Planted | None:
    rng = sheet.rng
    if kind is ErrorKind.SUBTOTAL:
        rows = [row for row in _total_rows(sheet, RowKind.SUBTOTAL) if row.closes_section_id]
        if not rows:
            return None
        target = rng.choice(rows)
        sections = _sections(sheet)
        closed = sections.get(target.closes_section_id or "")
        ancestors = set(closed.section_path) if closed is not None else set()
        enclosing = [
            row
            for row in sheet.rows
            if row.kind is RowKind.SUBTOTAL and row.closes_section_id in ancestors
        ]
        related = [*enclosing, *_after(sheet, target, RowKind.GRAND_TOTAL)]
        change = "two adjacent digits of a subtotal swapped"
    elif kind is ErrorKind.NET_TOTAL:
        rows = _total_rows(sheet, RowKind.GRAND_TOTAL)
        if not rows:
            return None
        target = rows[0]
        related = [*_after(sheet, target, RowKind.TAX), *_after(sheet, target, RowKind.GROSS_TOTAL)]
        change = "two adjacent digits of the net total swapped"
    else:
        rows = _total_rows(sheet, RowKind.TAX)
        nets = _total_rows(sheet, RowKind.GRAND_TOTAL)
        if not rows or not nets:
            return None
        target, related = rows[0], []
        change = "two adjacent digits of the tax swapped"
    amount = sheet.number(target, "line_total")
    assert amount is not None
    wrong = corrupt(rng, amount)
    planted = sheet.record(kind, target, change, related=related)
    index = sheet.index(target.row_id)
    sheet.set_number(index, "line_total", wrong)
    if kind is ErrorKind.TAX:
        for j in range(index + 1, len(sheet.rows)):
            gross = sheet.number(sheet.rows[j], "line_total")
            if sheet.rows[j].kind is RowKind.GROSS_TOTAL and gross is not None:
                sheet.set_number(j, "line_total", gross + wrong - amount)
                break
    return planted


def plant_table(sheet: _Sheet, kinds: Sequence[ErrorKind]) -> list[ErrorKind]:
    """Plant one error of each kind (position kinds first, then totals); return the kinds no
    row fitted."""
    missing: list[ErrorKind] = []
    for kind in kinds:
        if kind in TOTAL_LEVEL:
            continue
        candidates = _candidates(sheet, kind)
        sheet.rng.shuffle(candidates)
        if not any(PLANTERS[kind](sheet, row) is not None for row in candidates):
            missing.append(kind)
    for kind in kinds:
        if kind in TOTAL_LEVEL and _plant_total(sheet, kind) is None:
            missing.append(kind)
    return missing


# Datasets -----------------------------------------------------------------------------------


def _language(table: Table) -> Language:
    headers = " ".join((column.original_header or "").casefold() for column in table.columns)
    return "de" if any(word in headers for word in _GERMAN_HEADERS) else "en"


def _priced_table(dataset: Dataset) -> Table | None:
    """The table with the most item rows among those that map quantity, unit price and line
    total."""
    needed = {"quantity", "unit_price", "line_total", "unit", "description"}
    tables = [
        table
        for table in dataset.tables
        if needed <= {c.mapping.field_id for c in table.columns if c.mapping is not None}
    ]
    return max(
        tables,
        key=lambda table: sum(1 for row in table.rows if row.kind is RowKind.ITEM),
        default=None,
    )


def sheet_for(
    dataset: Dataset, rng: random.Random, new_row_id: Callable[[], str], prefix: str
) -> _Sheet | None:
    table = _priced_table(dataset)
    if table is None:
        return None
    return _Sheet(
        table=table,
        rows=list(table.rows),
        columns={c.mapping.field_id: c.column_id for c in table.columns if c.mapping is not None},
        language=_language(table),
        rng=rng,
        new_row_id=new_row_id,
        prefix=prefix,
        next_source_row=max((row.source_row_number for row in table.rows), default=0) + 1,
    )


def planted_dataset(dataset: Dataset, sheet: _Sheet) -> Dataset:
    """The next revision of ``dataset``, with the sheet's rows (positions renumbered)."""
    rows = [
        row if row.position == i else row.evolve(position=i) for i, row in enumerate(sheet.rows)
    ]
    table = sheet.table.evolve(rows=rows)
    tables = [table if t.table_id == table.table_id else t for t in dataset.tables]
    return dataset.evolve(
        tables=tables, revision=dataset.revision + 1, parent_revision=dataset.revision
    )


def truths(sheet: _Sheet) -> tuple[GroundTruth, ...]:
    number = {row.row_id: row.source_row_number for row in sheet.rows}
    result = []
    for planted in sheet.planted:
        row = number[planted.target]
        result.append(
            GroundTruth(
                error_id=planted.error_id,
                kind=planted.kind,
                row=row,
                field=planted.field,
                rows=tuple(sorted({row, *(number[r] for r in planted.related)})),
                expected_rules=EXPECTED_RULES[planted.kind],
                change=planted.change,
            )
        )
    return tuple(result)


# The run ------------------------------------------------------------------------------------


def _issues(wb: Workbench, dataset_id: str) -> list[ValidationIssue]:
    run = runs.start(wb, dataset_id)
    with wb.uow() as uow:
        return list(uow.issues.iter_all(IssueQuery(run_id=run["run_id"])))


def _only(dataset: Dataset, table_id: str) -> Dataset:
    """``dataset`` with just the planted table, so findings map to that table's rows."""
    return dataset.evolve(tables=[dataset.table(table_id)])


def _deal(rng: random.Random, deck: list[ErrorKind], config: InjectConfig) -> list[ErrorKind]:
    kinds: list[ErrorKind] = []
    for _ in range(config.max_errors):
        if not deck:
            deck.extend(config.kinds)
            rng.shuffle(deck)
        kind = deck.pop()
        if kind in kinds or (kind in EXCLUSIVE and EXCLUSIVE & set(kinds)):
            deck.insert(0, kind)
            continue
        kinds.append(kind)
    return kinds


@dataclass
class _Outcome:
    entry: dict[str, Any]
    result: DocumentResult | None = None
    others: list[dict[str, Any]] = field(default_factory=list)
    missing: list[ErrorKind] = field(default_factory=list)


def _inject_one(
    wb: Workbench,
    path: Path,
    number: int,
    rng: random.Random,
    kinds: list[ErrorKind],
    config: InjectConfig,
    signals: frozenset[str],
) -> _Outcome:
    entry: dict[str, Any] = {"file": path.name, "status": "not read", "rows": 0, "planted": 0}
    try:
        _, dataset = documents.upload(
            wb, filename=path.name, chunks=[path.read_bytes()], profile_id=config.profile_id
        )
    except WorkbenchError as exc:
        return _Outcome({**entry, "reason": exc.code}, missing=kinds)
    if dataset is None:
        return _Outcome({**entry, "reason": "the file could not be read"}, missing=kinds)
    sheet = sheet_for(dataset, rng, lambda: wb.ids.new(IdPrefix.ROW), f"b{number}")
    if sheet is None:
        reason = "no table maps description, quantity, unit, unit price and line total"
        return _Outcome({**entry, "status": "not planted", "reason": reason}, missing=kinds)
    started = time.perf_counter()
    table_id = sheet.table.table_id
    before = findings_of(_issues(wb, dataset.dataset_id), _only(dataset, table_id))
    first_new_row = sheet.next_source_row
    missing = plant_table(sheet, kinds)
    planted = planted_dataset(dataset, sheet)
    with wb.uow() as uow:
        uow.datasets.add(planted)
    after = findings_of(_issues(wb, planted.dataset_id), _only(planted, table_id))
    rows = planted.table(table_id).rows
    doc = SyntheticDocument(
        name=path.name,
        language=sheet.language,
        format=path.suffix.lstrip(".").lower(),
        content=b"",  # the file's bytes are not kept
        row_kinds={row.source_row_number: row.kind.value for row in rows},
        truths=truths(sheet),
    )
    score = score_document(after, doc.truths, k=config.k)
    result = DocumentResult(
        document=doc,
        score=score,
        classified=(0, 0),
        misclassified=(),
        seconds=time.perf_counter() - started,
        status="planted",
    )
    known = {(f.detector_id, f.rule_id, f.rows) for f in before}
    others = [
        {
            "file": path.name,
            "rows": sorted(f.rows),
            "detector_id": f.detector_id,
            "rule_id": f.rule_id,
            "severity": f.severity,
            "check": "signal" if f.detector_id in signals else "rule",
            "in_file_as_read": (f.detector_id, f.rule_id, f.rows) in known,
            "title": f.title,
        }
        for f in score.false_positives
    ]
    entry.update(
        status="planted",
        rows=len(rows),
        item_rows=sum(1 for row in rows if row.kind is RowKind.ITEM),
        planted=len(doc.truths),
        language=sheet.language,
        first_inserted_row=first_new_row,  # rows numbered from here were inserted by planting
    )
    return _Outcome(entry, result, others, missing)


def run_injection(folder: Path, config: InjectConfig, out_dir: Path) -> dict[str, Any]:
    """Plant errors into the bills in ``folder`` (in memory), validate, and write the report
    to ``out_dir`` (which must lie outside ``folder``); return the report."""
    folder, out_dir = folder.resolve(), out_dir.resolve()
    if not folder.is_dir():
        raise ValueError("The folder of bills does not exist.")
    if out_dir == folder or folder in out_dir.parents:
        raise ValueError("The output directory must lie outside the folder of bills.")
    began = time.perf_counter()
    files = sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUFFIXES
    )
    rng = random.Random(config.seed)  # noqa: S311 - reproducible planting, not security
    deck: list[ErrorKind] = []
    outcomes: list[_Outcome] = []
    with tempfile.TemporaryDirectory(prefix="twb-inject-") as scratch:
        wb = benchmark_workbench(Path(scratch))
        signals = signal_checks(wb)
        for number, path in enumerate(files, start=1):
            kinds = _deal(rng, deck, config)
            outcome = _inject_one(wb, path, number, rng, kinds, config, signals)
            deck[:0] = outcome.missing  # what this bill could not hold goes to a later one
            outcomes.append(outcome)
        results = [outcome.result for outcome in outcomes if outcome.result is not None]
        boq = boq_report.build(
            results,
            config.kinds,
            registered=wb.detectors.ids(),
            signal_checks=signals,
            defaults=wb.profiles.get(config.profile_id).detector_defaults,
        )
    planted = {truth.kind for result in results for truth in result.document.truths}
    report: dict[str, Any] = {
        "label": LABEL,
        "planting": (
            "In memory: errors planted into a copy of each file's canonical dataset (its next "
            "revision); the files were not changed and nothing was written next to them."
        ),
        "seed": config.seed,
        "max_errors": config.max_errors,
        "k": config.k,
        "profile_id": config.profile_id,
        "files": [outcome.entry for outcome in outcomes],
        "not_planted": {
            kind.value: NEEDS.get(kind, GENERAL_NEED)
            for kind in config.kinds
            if kind not in planted
        },
        "boq": boq,
        "other_findings": [item for outcome in outcomes for item in outcome.others],
        "timing": {"total_seconds": round(time.perf_counter() - began, 1)},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "inject-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "inject-report.md").write_text(render(report), encoding="utf-8")
    return report


def _other_counts(report: dict[str, Any]) -> tuple[int, int, int, int]:
    """(rule findings, of them in the files as read, signals, of them in the files as read)."""
    others = report["other_findings"]
    rules = [item for item in others if item["check"] == "rule"]
    signals = [item for item in others if item["check"] == "signal"]
    return (
        len(rules),
        sum(item["in_file_as_read"] for item in rules),
        len(signals),
        sum(item["in_file_as_read"] for item in signals),
    )


def summary(report: dict[str, Any]) -> str:
    """What the command prints: counts only, no file names, rows or titles."""
    rules, rules_before, signals, signals_before = _other_counts(report)
    files = report["files"]
    planted = sum(1 for entry in files if entry["status"] == "planted")
    lines = [
        "# Planted errors in your bills",
        "",
        f"{LABEL}.",
        "",
        f"{planted} of {len(files)} files planted into, in memory, with "
        f"{report['boq']['planted_errors']} errors (seed {report['seed']}); the files were not "
        "changed.",
        "",
        *boq_report.kind_table(report["boq"]["by_kind"]),
        "",
        f"Findings not matched to a planted error: {rules} from rule checks ({rules_before} "
        f"already in the files as read), {signals} signals ({signals_before} already in the "
        "files as read). The report lists them.",
    ]
    return "\n".join(lines) + "\n"


def render(report: dict[str, Any]) -> str:
    """The markdown report (``inject-report.md``)."""
    caption = f"{LABEL}."
    lines = [
        "# Planted errors in your bills",
        "",
        caption,
        "",
        f"{report['planting'][0].upper()}{report['planting'][1:]} Seed `{report['seed']}`, up "
        f"to {report['max_errors']} errors per file, profile `{report['profile_id']}`. Rows are "
        "source rows; a row numbered from a file's first inserted row was inserted by planting.",
        "",
        "## Files",
        "",
        "| File | Status | Rows | Item rows | Errors planted | First inserted row |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in report["files"]:
        status = entry["status"] + (f" ({entry['reason']})" if entry.get("reason") else "")
        lines.append(
            f"| {entry['file']} | {status} | {entry['rows']} | {entry.get('item_rows', '')} | "
            f"{entry['planted']} | {entry.get('first_inserted_row', '')} |"
        )
    lines += ["", "## By error kind", "", caption, ""]
    lines += boq_report.kind_table(report["boq"]["by_kind"])
    if report["not_planted"]:
        lines += ["", "Not planted, because no file has what the kind needs:", ""]
        lines += [f"- `{kind}`: {need}" for kind, need in report["not_planted"].items()]
    lines += ["", "## Planted errors not found by their expected check", ""]
    missed = report["boq"]["missed"]
    if missed:
        lines += [
            "| File | Error | Kind | Row | Change | Rules found |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {m['document']} | {m['error_id']} | `{m['kind']}` | {m['row']} | {m['change']} | "
            f"{', '.join(m['rules_found']) or 'none'} |"
            for m in missed
        ]
    else:
        lines.append("None.")
    lines += [
        "",
        "## Findings not matched to a planted error",
        "",
        "Every finding of the planted revision that matches no planted error: from rule checks "
        "and signals, and whether the same finding was already reported on the file as read "
        "(then the file holds it, not the planting).",
        "",
    ]
    others = report["other_findings"]
    if others:
        lines += [
            "| File | Rows | Check | Rule | Severity | Kind of check | In the file as read "
            "| Title |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {o['file']} | {', '.join(map(str, o['rows'])) or 'table'} | `{o['detector_id']}` | "
            f"`{o['rule_id']}` | {o['severity']} | {o['check']} | "
            f"{'yes' if o['in_file_as_read'] else 'no'} | {o['title']} |"
            for o in others
        ]
    else:
        lines.append("None.")
    lines += ["", f"The run took {report['timing']['total_seconds']:.1f} s.", ""]
    return "\n".join(lines)
