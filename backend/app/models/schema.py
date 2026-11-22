"""Reviewer decisions about a document's structure (the extraction review step, brief Part I).

Normalization applies these on top of automatic detection: a chosen header row, manual
column-to-field mapping, row-kind overrides and rows that are not data. Decisions are keyed by
*source coordinates* (sheet index, source row and column numbers), never by generated ids, so
they survive re-normalization. Phase 1 applies them in ``build_dataset``; the review UI and
API that collect them arrive in Phase 2.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import Field, field_validator

from app.models.base import FrozenModel
from app.models.dataset import RowKind
from app.models.profile import FIELD_ID_PATTERN


class TableDecisions(FrozenModel):
    """Decisions for one sheet. Row decisions are keyed by source row number, column
    decisions by source column number."""

    sheet_index: int = Field(ge=0)
    # Hidden sheets are skipped unless a reviewer includes them (warning hidden_sheet_skipped).
    include_hidden_sheet: bool = False
    header_row_numbers: list[int] | None = None  # None = detect automatically; [] = no header
    column_fields: dict[int, str | None] = Field(default_factory=dict)  # source col -> field
    row_kinds: dict[int, RowKind] = Field(default_factory=dict)  # source row -> kind
    not_data_rows: list[int] = Field(default_factory=list)  # source rows excluded as not data
    # source row -> True / False / None (unknown): whether an item is added into totals
    counts_toward_totals: dict[int, bool | None] = Field(default_factory=dict)
    section_levels: dict[int, int] = Field(default_factory=dict)  # SECTION row -> level
    # SUBTOTAL row -> the SECTION row it closes (None = no section; the scope is unknown)
    closes_section: dict[int, int | None] = Field(default_factory=dict)
    # unit text as written -> unit_id of the profile (confirms or adds a unit alias)
    unit_aliases: dict[str, str] = Field(default_factory=dict)

    @field_validator("section_levels")
    @classmethod
    def _valid_levels(cls, value: dict[int, int]) -> dict[int, int]:
        if any(not 1 <= level <= 9 for level in value.values()):
            raise ValueError("section levels range from 1 (outermost) to 9")
        return value

    @field_validator("column_fields")
    @classmethod
    def _valid_fields(cls, value: dict[int, str | None]) -> dict[int, str | None]:
        for column, field_id in value.items():
            if column < 1:
                raise ValueError("source column numbers start at 1")
            if field_id is not None and not re.fullmatch(FIELD_ID_PATTERN, field_id):
                raise ValueError(f"invalid field id {field_id!r}")
        assigned = [f for f in value.values() if f is not None]
        if len(assigned) != len(set(assigned)):
            raise ValueError("a field can be assigned to only one column")
        return value

    def over(self, base: TableDecisions | None) -> TableDecisions:
        """These decisions on top of ``base``, the structure a file format declares itself
        (``RawSheet.declared``). Every decision made here wins for its row, column or unit
        text; a field assigned here is removed from the column ``base`` gave it."""
        if base is None:
            return self
        taken = {f for f in self.column_fields.values() if f is not None}
        column_fields = {
            c: f
            for c, f in base.column_fields.items()
            if c not in self.column_fields and f not in taken
        }
        column_fields.update(self.column_fields)
        return TableDecisions(
            sheet_index=self.sheet_index,
            include_hidden_sheet=self.include_hidden_sheet or base.include_hidden_sheet,
            header_row_numbers=(
                self.header_row_numbers
                if self.header_row_numbers is not None
                else base.header_row_numbers
            ),
            column_fields=column_fields,
            row_kinds={**base.row_kinds, **self.row_kinds},
            not_data_rows=sorted(set(base.not_data_rows) | set(self.not_data_rows)),
            counts_toward_totals={**base.counts_toward_totals, **self.counts_toward_totals},
            section_levels={**base.section_levels, **self.section_levels},
            closes_section={**base.closes_section, **self.closes_section},
            unit_aliases={**base.unit_aliases, **self.unit_aliases},
        )


class SchemaDecisions(FrozenModel):
    tables: list[TableDecisions] = Field(default_factory=list)
    decided_by: str | None = None
    decided_at: datetime | None = None

    def for_sheet(self, sheet_index: int) -> TableDecisions | None:
        return next((t for t in self.tables if t.sheet_index == sheet_index), None)
