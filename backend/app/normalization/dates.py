"""Date text parsing. ISO 8601 dates and datetimes are always read (``exact``). Day-month-year
texts (``03.04.2026``, ``03/04/2026``, ``3-4-2026``) need an order: the profile's
``locale.date_order`` decides (``inferred``); with ``auto`` they are read only when the text
itself decides (a component above 12), otherwise they stay ambiguous. Two-digit years are not
read (the century would be a guess)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from app.models.values import DateTimeValue, DateValue, ParseStatus

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_DATETIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$")
_NUMERIC_DATE = re.compile(r"^(\d{1,2})([./-])(\d{1,2})\2(\d{4})$")

DateOrder = Literal["auto", "DMY", "MDY", "YMD"]


@dataclass(frozen=True, slots=True)
class DateReading:
    value: DateValue | DateTimeValue
    status: ParseStatus
    note: str | None = None


@dataclass(frozen=True, slots=True)
class AmbiguousDate:
    note: str


def parse_date(text: str, order: DateOrder) -> DateReading | AmbiguousDate | None:
    """Read date text; ``None`` when the text is not a date (or not a valid one)."""
    core = text.strip()
    if len(core) > 32:
        return None
    try:
        if found := _ISO_DATE.match(core):
            year, month, day = (int(g) for g in found.groups())
            return DateReading(DateValue(value=date(year, month, day)), ParseStatus.EXACT)
        if found := _ISO_DATETIME.match(core):
            return DateReading(DateTimeValue(value=_iso_datetime(found)), ParseStatus.EXACT)
        found = _NUMERIC_DATE.match(core)
        if found is None:
            return None
        first, second, year = int(found.group(1)), int(found.group(3)), int(found.group(4))
        if order == "DMY":
            return _reading(year, second, first, "Day-month-year order from the profile locale.")
        if order == "MDY":
            return _reading(year, first, second, "Month-day-year order from the profile locale.")
        if order == "YMD":
            return None
        if first > 12 >= second:
            return DateReading(DateValue(value=date(year, second, first)), ParseStatus.EXACT)
        if second > 12 >= first:
            return DateReading(DateValue(value=date(year, first, second)), ParseStatus.EXACT)
        if first == second:
            return DateReading(DateValue(value=date(year, first, second)), ParseStatus.EXACT)
        return AmbiguousDate(
            f"Day and month order is undecided: {date(year, second, first).isoformat()} or "
            f"{date(year, first, second).isoformat()}."
        )
    except ValueError:
        return None  # an impossible date such as 31.02.2026


def _iso_datetime(found: re.Match[str]) -> datetime:
    """The moment an ``_ISO_DATETIME`` match names (its seconds are optional)."""
    year, month, day, hour, minute, second = found.groups()
    return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))


def _reading(year: int, month: int, day: int, note: str) -> DateReading:
    return DateReading(DateValue(value=date(year, month, day)), ParseStatus.INFERRED, note)
