"""Test helpers for the BoQ wording checks (not a test module).

The texts in these tests are synthetic German BoQ wording made up for the tests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.models.dataset import Dataset, RowKind
from app.models.profile import DomainProfile
from tests.support.builders import DatasetBuilder

COLUMNS: list[tuple[str | None, str | None]] = [
    ("OZ", "item_code"),
    ("Kurztext", "description"),
    ("Langtext", "long_description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
    ("EP", "unit_price"),
]
SHORT_ONLY = [column for column in COLUMNS if column[1] != "long_description"]


@dataclass(frozen=True)
class Line:
    """One row: an item, a note (``kind=TEXT``) or a continuation line of the item above."""

    oz: str | None
    short: str | None
    long: str | None = None
    unit: str | None = "St"
    kind: RowKind = RowKind.ITEM
    continues: bool = False


def item(oz: str, short: str, long: str | None = None, unit: str | None = "St") -> Line:
    return Line(oz, short, long, unit)


def note(short: str, long: str | None = None) -> Line:
    return Line(None, short, long, None, RowKind.TEXT)


def continuation(text: str) -> Line:
    return Line(None, text, None, None, RowKind.TEXT, continues=True)


def bill(
    profile: DomainProfile,
    lines: Iterable[Line],
    *,
    columns: list[tuple[str | None, str | None]] = COLUMNS,
    name: str = "LV",
) -> Dataset:
    """One table of ``lines``; columns without a field in ``columns`` are left out."""
    builder = DatasetBuilder(profile)
    table = builder.table(name, columns)
    last_item: int | None = None
    for index, line in enumerate(lines):
        by_field = {
            "item_code": line.oz,
            "description": line.short,
            "long_description": line.long,
            "quantity": "1" if line.kind is RowKind.ITEM else None,
            "unit": line.unit,
            "unit_price": None,
        }
        values = [by_field.get(field_id or "") for _, field_id in columns]
        table.row(
            values,
            kind=line.kind,
            in_totals=True if line.kind is RowKind.ITEM else None,
            belongs_to=last_item if line.continues else None,
        )
        if line.kind is RowKind.ITEM:
            last_item = index
    return builder.build()


def long_text(words: str, before: int = 3000) -> str:
    """``words`` after ``before`` characters of filler wording (a long Langtext)."""
    filler = "Die Leistung ist nach den Vorgaben der Bauleitung auszuführen. "
    return (filler * (before // len(filler) + 1))[:before] + " " + words
