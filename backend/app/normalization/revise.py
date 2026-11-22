"""Manual cell corrections -> revision N+1 of a dataset (ADR 0001).

A reviewer types a new text into a cell. The cell is read again the way an upload reads a text
cell of that column (:class:`~app.normalization.cells.CellParser`, then
:func:`~app.normalization.cells.finish`): a quantity column reads a number or a value marker, a
unit column resolves the unit, an unmapped column reads a number or a date, anything else stays
text. An ambiguous number takes the column's decimal separator, else the profile locale's. The
cell keeps its source location and number format; a formula and an engine confidence belong to
the old content and are dropped.

The result is revision N+1 of the same dataset: same dataset, table, column and row ids, every
other cell unchanged, ``parent_revision = N``. The uploaded file is never changed.

Not derived again (the extraction's decisions stay as they were): row classification and the
section structure, column type profiles, extraction warnings, and reviewer unit aliases.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.core.errors import InvalidInputError
from app.ingestion.base import RawCell, RawValueType
from app.models.dataset import Cell, Column, Dataset, Row
from app.models.profile import DomainProfile
from app.normalization.cells import CellParser, finish
from app.normalization.numbers import DecimalMark
from app.profiles.currency import CurrencyResolver
from app.profiles.units import UnitCatalog


@dataclass(frozen=True, slots=True)
class CellCorrection:
    """The text a reviewer typed into one cell; ``""`` empties it."""

    table_id: str
    row_id: str
    column_id: str
    raw_value: str


@dataclass(frozen=True, slots=True)
class AppliedCorrection:
    table_id: str
    table_name: str
    row_id: str
    column_id: str
    reference: str  # where the cell is, e.g. "D14" or "row 14, column 4"
    before: Cell
    after: Cell


def revise(
    dataset: Dataset,
    corrections: Sequence[CellCorrection],
    *,
    profile: DomainProfile,
    created_at: datetime,
) -> tuple[Dataset, list[AppliedCorrection]]:
    """``dataset`` with the corrected cells as its next revision, and what changed.

    Unknown table, row or column ids raise ``NotFoundError``; the same cell twice raises
    ``InvalidInputError``. A correction to the cell's current text changes nothing; when
    nothing changes, ``dataset`` itself is returned with an empty list.
    """
    seen: set[tuple[str, str, str]] = set()
    for correction in corrections:
        key = (correction.table_id, correction.row_id, correction.column_id)
        if key in seen:
            raise InvalidInputError(
                "The same cell is corrected twice in one request.",
                details={"table_id": key[0], "row_id": key[1], "column_id": key[2]},
            )
        seen.add(key)

    parser = CellParser(
        profile, UnitCatalog.from_profile(profile), CurrencyResolver.from_profile(profile), {}
    )
    locale: DecimalMark | None = (
        profile.locale.decimal_separator if profile.locale.decimal_separator != "auto" else None
    )
    changed: dict[tuple[str, str], dict[str, Cell]] = {}  # (table, row) -> column -> new cell
    applied: list[AppliedCorrection] = []
    for correction in corrections:
        table = dataset.table(correction.table_id)
        row = table.row(correction.row_id)
        column = table.column(correction.column_id)
        before = row.cells[column.column_id]
        if (before.raw_value or "") == correction.raw_value:
            continue
        after = _read(parser, profile, locale, row, column, before, correction.raw_value)
        changed.setdefault((table.table_id, row.row_id), {})[column.column_id] = after
        applied.append(
            AppliedCorrection(
                table_id=table.table_id,
                table_name=table.name,
                row_id=row.row_id,
                column_id=column.column_id,
                reference=_reference(before, row, column),
                before=before,
                after=after,
            )
        )
    if not applied:
        return dataset, []

    tables = [
        table.evolve(
            rows=[
                row.evolve(cells={**row.cells, **changed[(table.table_id, row.row_id)]})
                if (table.table_id, row.row_id) in changed
                else row
                for row in table.rows
            ]
        )
        if any(table_id == table.table_id for table_id, _ in changed)
        else table
        for table in dataset.tables
    ]
    revised = dataset.evolve(
        tables=tables,
        revision=dataset.revision + 1,
        parent_revision=dataset.revision,
        created_at=created_at,
    )
    return revised, applied


def _read(
    parser: CellParser,
    profile: DomainProfile,
    locale: DecimalMark | None,
    row: Row,
    column: Column,
    before: Cell,
    text: str,
) -> Cell:
    field_id = column.mapped_semantic_field
    field = profile.field(field_id) if field_id is not None else None
    raw = RawCell(
        row=before.source.row_number or row.source_row_number,
        column=before.source.column_number or column.source_column_number,
        value_type=RawValueType.STRING,
        text=text,
        number_format=before.number_format,
    )
    draft = parser.draft(raw, field)
    resolved: tuple[DecimalMark, str] | None = None
    if draft.kind == "ambiguous":
        if column.decimal_separator is not None:
            separator = column.decimal_separator
            resolved = (separator, f"Decimal separator '{separator}' as used in this column.")
        elif locale is not None:
            resolved = (locale, f"Decimal separator '{locale}' taken from the profile's locale.")
    return finish(raw, draft, before.source, resolved)


def _reference(before: Cell, row: Row, column: Column) -> str:
    a1 = before.source.a1
    if a1:
        return a1
    return f"row {row.source_row_number}, column {column.source_column_number}"


__all__ = ["AppliedCorrection", "CellCorrection", "revise"]
