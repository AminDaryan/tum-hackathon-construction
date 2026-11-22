"""The item frame: one record per item row of every table that maps a unit price.

The comparison checks (similar prices, quantity factors, unit and section fit, near-copies)
look at the same rows, so :func:`item_frame` reads them once per validation run and caches the
result in ``context.memo`` under :data:`ITEM_FRAME_KEY` (the per-detector copies of a run's
context share that dict). Values come only through the context's accessors: markers ("Incl.",
"entfällt"), ambiguous, failed and unavailable numbers stay ``None`` and are never guessed, and
rows a reviewer excluded are left out.

:attr:`ItemFrame.records` hold the exact ``Decimal`` values and the cell references that a
finding shows. :attr:`ItemFrame.frame` is a pandas DataFrame over the same records, row ``i``
for ``records[i]``, with float64 columns for the statistics only; nothing shown to people is
taken from it.

An item discount (``discount_percent``, mapped where a file declares it, such as a GAEB bill)
reduces the line total: :attr:`ItemRecord.discount_factor` is what an amount of the row is
multiplied by. An amount at stake computed from a reference price (the ``reference_deviation``
of the comparison checks, plan contract P11) is multiplied by it, so it is as discounted as the
line total it stands for.
"""

from __future__ import annotations

import decimal
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

import numpy as np
import pandas as pd

from app.models.dataset import CellRef, Row, Table
from app.validation.contracts.conditions import CellCondition, cell_condition
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import multiply, subtract
from app.validation.contracts.detector import Applicability
from app.validation.contracts.issue_factory import is_verified
from app.validation.support.text_keys import description_key

ITEM_FRAME_KEY = "validation.support.item_frame"

# Columns of ItemFrame.frame. Numbers are float64 (NaN where the record's value is None).
TEXT_COLUMNS = (
    "table_id",
    "row_id",
    "item_code",
    "description_key",
    "standard_text_key",
    "unit_id",
    "dimension",
    "item_type",
    "section_row_id",
)
NUMBER_COLUMNS = (
    "quantity",
    "unit_price",
    "unit_price_per_base_unit",
    "line_total",
    "multiplier",
    "log_price",  # natural log of the unit price per base unit, for positive prices only
)
FLAG_COLUMNS = ("counts_toward_totals", "verified")

# Precision of the unit price per base unit when the division by a multiplier does not end
# (a price for "3 St"); multipliers such as 10, 100 and 1000 always divide exactly.
_PER_BASE_UNIT_DIGITS = 28
_ONE, _HUNDRED, _PERCENT = Decimal(1), Decimal(100), Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ItemFields:
    """The profile fields a record is read from. The defaults are the field ids of the shipped
    profiles; ``unit=None`` means the profile's field with role ``unit``."""

    item_code: str = "item_code"
    description: str = "description"
    long_description: str = "long_description"
    standard_text_key: str = "standard_text_key"
    quantity: str = "quantity"
    unit: str | None = None
    unit_price: str = "unit_price"
    line_total: str = "line_total"
    discount_percent: str = "discount_percent"
    item_type: str = "item_type"


DEFAULT_ITEM_FIELDS = ItemFields()


@dataclass(frozen=True, slots=True)
class ItemRecord:
    """One item row. Every value is ``None`` when its field is not mapped or its cell holds no
    usable value. ``cells`` maps the field ids of the mapped fields to their cells.

    ``multiplier`` is the leading number of a unit such as "100 St" (the price is per 100
    pieces), and ``unit_price_per_base_unit`` the unit price divided by it (the unit price
    itself when the unit has no multiplier), so prices of "St" and "100 St" compare.
    ``discount_percent`` is the item discount in percent (1.5 for 1.5 %, whether the cell says
    "1.5" or "1,5 %"), ``None`` when none is stated; ``discount_factor`` is 1 − discount / 100,
    exactly 1 when no discount is stated (field not mapped, cell empty), and ``None`` when the
    discount cell holds no usable number, so that an amount depending on it is not computed.
    ``verified`` is True when every mapped cell of the row may confirm a rule (verbatim digital
    cells, or scored cells at or above the confidence threshold).
    """

    position: int
    table_id: str
    row_id: str
    item_code: str | None
    description: str | None
    description_key: str | None
    long_description: str | None
    standard_text_key: str | None
    unit_id: str | None
    dimension: str | None
    multiplier: Decimal | None
    quantity: Decimal | None
    unit_price: Decimal | None
    unit_price_per_base_unit: Decimal | None
    line_total: Decimal | None
    discount_percent: Decimal | None
    discount_factor: Decimal | None
    cells: Mapping[str, CellRef]
    section_row_id: str | None
    section_path: tuple[str, ...]
    counts_toward_totals: bool | None
    item_type: str | None
    verified: bool

    def cell(self, field_id: str) -> CellRef | None:
        """The cell of a mapped field of this row."""
        return self.cells.get(field_id)


class ItemFrame:
    """The records of a run's item rows and a DataFrame over them (see the module docstring).

    :attr:`frame` returns a new shallow copy on every access: pandas copies on write, so a
    check that adds a column or changes a value never changes what the next check reads."""

    __slots__ = ("_by_row", "_frame", "fields", "records")

    def __init__(self, records: tuple[ItemRecord, ...], fields: ItemFields) -> None:
        self.records = records
        self.fields = fields
        self._by_row = {(record.table_id, record.row_id): record for record in records}
        self._frame = _data_frame(records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=False)

    def record(self, table_id: str, row_id: str) -> ItemRecord | None:
        return self._by_row.get((table_id, row_id))


def item_frame(context: ValidationContext, fields: ItemFields | None = None) -> ItemFrame:
    """The item frame of the context's dataset, built on first use and then cached in
    ``context.memo`` (under :data:`ITEM_FRAME_KEY` for the default fields)."""
    wanted = fields or DEFAULT_ITEM_FIELDS
    key: object = ITEM_FRAME_KEY if wanted == DEFAULT_ITEM_FIELDS else (ITEM_FRAME_KEY, wanted)
    cached = context.memo.get(key)
    if isinstance(cached, ItemFrame):
        return cached
    built = ItemFrame(_records(context, wanted), wanted)
    context.memo[key] = built
    return built


# ---------------------------------------------------------------------------- reading
def unit_price_applicability(context: ValidationContext) -> Applicability:
    """A price check applies where a table maps both a unit price and a unit."""
    unit_field = context.unit_field_id()
    tables = [
        t.name
        for t in context.tables()
        if unit_field and context.has_fields(t, "unit_price", unit_field)
    ]
    if not tables:
        return Applicability.no("No table maps both a unit price and a unit.")
    return Applicability.yes(f"Unit prices and units are mapped in: {', '.join(tables)}.")


def _records(context: ValidationContext, fields: ItemFields) -> tuple[ItemRecord, ...]:
    unit_field = fields.unit or context.unit_field_id()
    wanted = [
        fields.item_code,
        fields.description,
        fields.long_description,
        fields.standard_text_key,
        fields.quantity,
        *([unit_field] if unit_field else []),
        fields.unit_price,
        fields.line_total,
        fields.discount_percent,
        fields.item_type,
    ]
    records: list[ItemRecord] = []
    for table in context.tables():
        if context.column(table, fields.unit_price) is None:
            continue
        mapped = [
            field_id
            for field_id in dict.fromkeys(wanted)
            if context.column(table, field_id) is not None
        ]
        for row in context.rows(table):
            records.append(_record(context, fields, unit_field, table, row, mapped, len(records)))
    return tuple(records)


def _record(
    context: ValidationContext,
    fields: ItemFields,
    unit_field: str | None,
    table: Table,
    row: Row,
    mapped: list[str],
    position: int,
) -> ItemRecord:
    unit = context.unit(table, row, unit_field) if unit_field else None
    multiplier = unit.multiplier if unit is not None else None
    unit_price = context.number(table, row, fields.unit_price)
    description = context.text(table, row, fields.description)
    discount_percent, discount_factor = _discount(context, fields, table, row)
    threshold = context.issues.low_confidence_threshold
    cells = {field_id: context.cell_ref(table, row, field_id) for field_id in mapped}
    verified = all(
        is_verified(cell, threshold)
        for field_id in mapped
        if (cell := context.cell(table, row, field_id)) is not None
    )
    return ItemRecord(
        position=position,
        table_id=table.table_id,
        row_id=row.row_id,
        item_code=context.text(table, row, fields.item_code),
        description=description,
        description_key=description_key(description) if description else None,
        long_description=context.text(table, row, fields.long_description),
        standard_text_key=context.text(table, row, fields.standard_text_key),
        unit_id=unit.unit.unit_id if unit is not None else None,
        dimension=unit.unit.dimension if unit is not None else None,
        multiplier=multiplier,
        quantity=context.number(table, row, fields.quantity),
        unit_price=unit_price,
        unit_price_per_base_unit=_per_base_unit(unit_price, multiplier),
        line_total=context.number(table, row, fields.line_total),
        discount_percent=discount_percent,
        discount_factor=discount_factor,
        cells=MappingProxyType(cells),
        section_row_id=row.section_row_id,
        section_path=tuple(row.section_path),
        counts_toward_totals=row.counts_toward_totals,
        item_type=context.text(table, row, fields.item_type),
        verified=verified,
    )


def _discount(
    context: ValidationContext, fields: ItemFields, table: Table, row: Row
) -> tuple[Decimal | None, Decimal | None]:
    """(discount in percent, factor): see :class:`ItemRecord`. Read as the line total check
    reads it: a cell written as "1,5 %" is already divided by 100."""
    if context.column(table, fields.discount_percent) is None:
        return None, _ONE
    if cell_condition(context.cell(table, row, fields.discount_percent)) is CellCondition.EMPTY:
        return None, _ONE
    value = context.number_value(table, row, fields.discount_percent)
    if value is None:
        return None, None
    percent = multiply(value.value, _HUNDRED) if value.is_percent else value.value
    return percent, subtract(_ONE, multiply(percent, _PERCENT))


def _per_base_unit(price: Decimal | None, multiplier: Decimal | None) -> Decimal | None:
    if price is None or multiplier is None:
        return price
    with decimal.localcontext() as ctx:
        ctx.prec = _PER_BASE_UNIT_DIGITS
        ctx.rounding = decimal.ROUND_HALF_EVEN
        return price / multiplier


# ---------------------------------------------------------------------------- frame
def _floats(values: list[Decimal | None]) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)


def _data_frame(records: tuple[ItemRecord, ...]) -> pd.DataFrame:
    per_base = _floats([r.unit_price_per_base_unit for r in records])
    log_price = np.full(per_base.shape, np.nan, dtype=np.float64)
    positive = per_base > 0
    log_price[positive] = np.log(per_base[positive])
    columns: dict[str, object] = {
        name: pd.array([getattr(r, name) for r in records], dtype="string") for name in TEXT_COLUMNS
    }
    columns |= {
        "quantity": _floats([r.quantity for r in records]),
        "unit_price": _floats([r.unit_price for r in records]),
        "unit_price_per_base_unit": per_base,
        "line_total": _floats([r.line_total for r in records]),
        "multiplier": _floats([r.multiplier for r in records]),
        "log_price": log_price,
        "counts_toward_totals": pd.array(
            [r.counts_toward_totals for r in records], dtype="boolean"
        ),
        "verified": np.array([r.verified for r in records], dtype=np.bool_),
    }
    return pd.DataFrame(columns, index=pd.RangeIndex(len(records)))
