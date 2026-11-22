"""Raw cells -> canonical cells, through :mod:`app.models.cell_rules` only.

Text that may be a number is parsed in two passes per column: :func:`draft` reads each cell on
its own, then the builder resolves ambiguous separators from the column's (and the
document's) evidence and calls :func:`finish`. Typed source values (XLSX numbers, booleans,
dates, error literals, formulas without a cached result) need no evidence.

What text means depends on the column's field (``None`` = unmapped column):

* text fields: plain text; the unit field's normalized value is the canonical unit id when
  the unit catalogue or a reviewer's unit alias resolves the text without a multiplier;
* number fields: a profile value marker ("Incl.", "psch"), else a number, else ``failed``;
* date and boolean fields: a date or boolean, else ``failed``;
* unmapped columns: a number, else a date, else plain text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal, TypedDict, TypeVar

from app.ingestion.base import RawCell, RawValueType
from app.models import cell_rules as rules
from app.models.dataset import Cell, FormulaInfo
from app.models.profile import DomainProfile, FieldRole, SemanticField, normalize_token
from app.models.source import SourceLocation
from app.models.values import (
    BooleanValue,
    DataType,
    DateTimeValue,
    DateValue,
    NumberValue,
    ParseStatus,
    ValueMarker,
    is_bounded_decimal,
)
from app.normalization.dates import AmbiguousDate, DateReading, parse_date
from app.normalization.numbers import (
    AmbiguousNumber,
    DecimalMark,
    NumberReading,
    OutOfRange,
    ParenthesizedNumber,
    parse_number,
)
from app.profiles.currency import CurrencyResolver
from app.profiles.units import UnitCatalog, unit_key

OUT_OF_RANGE_NOTE = "Number outside the supported range (at most 28 significant digits)."
PARENTHESES_NOTE = (
    "Parentheses can mark a negative amount or an amount not included in the total; the "
    "profile leaves them unread."
)
_NOTE_TEXT_CHARS = 40
MAX_MARKER_CHARS = 40  # as DomainProfile.match_marker

DraftKind = Literal[
    "typed",
    "number",
    "ambiguous",
    "parenthesized",
    "out_of_range",
    "date",
    "ambiguous_date",
    "marker",
    "boolean",
    "text",
    "unit",
    "failed",
]


# What a draft holds, by kind: "number" a NumberReading, "ambiguous" an AmbiguousNumber,
# "date" a DateReading, "marker" a ValueMarker, "boolean" a bool, "unit" the unit id (or None
# when the unit is unknown); the other kinds hold None.
DraftReading = NumberReading | AmbiguousNumber | DateReading | ValueMarker | bool | str | None
_ReadingT = TypeVar("_ReadingT", NumberReading, AmbiguousNumber, DateReading, ValueMarker)


@dataclass(frozen=True, slots=True)
class Draft:
    """First-pass reading of one text cell."""

    kind: DraftKind
    reading: DraftReading = None
    note: str | None = None

    def reading_as(self, expected: type[_ReadingT]) -> _ReadingT:
        """The reading, which this draft's kind says is an ``expected``."""
        if not isinstance(self.reading, expected):
            raise TypeError(f"A {self.kind!r} draft holds {type(self.reading).__name__}")
        return self.reading


@dataclass(frozen=True, slots=True)
class CellParser:
    profile: DomainProfile
    units: UnitCatalog
    currencies: CurrencyResolver
    unit_aliases: dict[str, str]  # unit_key(text as written) -> unit_id (reviewer decisions)
    _markers: dict[tuple[FieldRole, str], ValueMarker] = field(
        init=False, repr=False, compare=False
    )
    _booleans: dict[str, bool] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # DomainProfile.match_marker compiled into one lookup (first rule wins, as there).
        markers: dict[tuple[FieldRole, str], ValueMarker] = {}
        for rule in self.profile.value_markers:
            for role in rule.roles:
                for token in rule.tokens:
                    markers.setdefault((role, normalize_token(token)), rule.marker)
        object.__setattr__(self, "_markers", markers)
        words = self.profile.boolean_words
        booleans = {w.strip().casefold(): True for w in words.true_words}
        booleans.update({w.strip().casefold(): False for w in words.false_words})
        object.__setattr__(self, "_booleans", booleans)

    def marker(self, text: str, role: FieldRole) -> ValueMarker | None:
        """Same answer as ``DomainProfile.match_marker``, without re-reading every token."""
        if not text or len(text) > MAX_MARKER_CHARS:
            return None
        return self._markers.get((role, normalize_token(text)))

    def draft(self, raw: RawCell, field: SemanticField | None) -> Draft:
        """Read one STRING cell (callers handle every other raw type)."""
        text = raw.text or ""
        if field is None:
            return self._unmapped(text)
        if field.data_type is DataType.NUMBER:
            marker = self.marker(text, field.role)
            if marker is not None:
                return Draft("marker", marker)
            return self._number(text, failed=f"Not a number: '{_clip(text)}'.")
        if field.data_type in (DataType.DATE, DataType.DATETIME):
            reading = parse_date(text, self.profile.locale.date_order)
            if isinstance(reading, DateReading):
                return Draft("date", reading)
            if isinstance(reading, AmbiguousDate):
                return Draft("ambiguous_date", note=reading.note)
            return Draft("failed", note=f"Not a date: '{_clip(text)}'.")
        if field.data_type is DataType.BOOLEAN:
            meaning = self._booleans.get(text.strip().casefold())
            if meaning is not None:
                return Draft("boolean", meaning)
            return Draft("failed", note=f"Not a yes/no value: '{_clip(text)}'.")
        if field.role is FieldRole.UNIT:
            return Draft("unit", self._unit_id(text))
        return Draft("text")

    def _unmapped(self, text: str) -> Draft:
        drafted = self._number(text, failed=None)
        if drafted.kind != "text":
            return drafted
        reading = parse_date(text, self.profile.locale.date_order)
        if isinstance(reading, DateReading):
            return Draft("date", reading)
        return Draft("text")  # an ambiguous day/month order stays text outside date fields

    def _number(self, text: str, *, failed: str | None) -> Draft:
        parsed = parse_number(
            text,
            currencies=self.currencies,
            parentheses=self.profile.locale.parenthesized_numbers,
        )
        if isinstance(parsed, NumberReading):
            return Draft("number", parsed)
        if isinstance(parsed, AmbiguousNumber):
            return Draft("ambiguous", parsed)
        if isinstance(parsed, ParenthesizedNumber):
            return Draft("parenthesized", note=PARENTHESES_NOTE)
        if isinstance(parsed, OutOfRange):
            return Draft("out_of_range", note=OUT_OF_RANGE_NOTE)
        if failed is not None:
            return Draft("failed", note=failed)
        return Draft("text")

    def _unit_id(self, text: str) -> str | None:
        alias = self.unit_aliases.get(unit_key(text))
        if alias is not None:
            return alias
        lookup = self.units.lookup(text)
        if lookup is None or lookup.multiplier is not None:
            return None
        return lookup.unit.unit_id


def finish(
    raw: RawCell,
    draft: Draft,
    source: SourceLocation,
    resolved: tuple[DecimalMark, str] | None = None,
) -> Cell:
    """Second pass for a STRING cell. ``resolved`` = (decimal separator, note) for an
    ambiguous number whose separator the evidence decided."""
    text = raw.text or ""
    extra = _extras(raw)
    kind = draft.kind
    if rules.is_blank(text):
        return rules.empty_cell(source, raw=text, **extra)
    if kind == "number":
        number = draft.reading_as(NumberReading)
        return _number_cell(number, source, text, ParseStatus.EXACT, None, extra)
    if kind == "ambiguous":
        ambiguous = draft.reading_as(AmbiguousNumber)
        if resolved is not None:
            number = ambiguous.resolve(resolved[0])
            return _number_cell(number, source, text, ParseStatus.INFERRED, resolved[1], extra)
        note = (
            f"Could be {_plain(ambiguous.as_decimal)} or {_plain(ambiguous.as_grouping)}: the "
            f"'{ambiguous.separator}' may be a decimal separator or a thousands separator."
        )
        return rules.ambiguous_cell(text, source, note, **extra)
    if kind in ("parenthesized", "ambiguous_date"):
        return rules.ambiguous_cell(text, source, draft.note or "", **extra)
    if kind in ("out_of_range", "failed"):
        return rules.failed_cell(text, source, draft.note or "", **extra)
    if kind == "marker":
        return rules.marker_cell(
            text,
            source,
            draft.reading_as(ValueMarker),
            formula=extra["formula"],
            confidence=extra["confidence"],
        )
    if kind == "date":
        reading = draft.reading_as(DateReading)
        data_type = DataType.DATE if isinstance(reading.value, DateValue) else DataType.DATETIME
        return rules.typed_cell(
            reading.value,
            data_type,
            source,
            raw=text,
            status=reading.status,
            note=reading.note,
            **extra,
        )
    if kind == "boolean":
        return rules.typed_cell(
            BooleanValue(value=bool(draft.reading)), DataType.BOOLEAN, source, raw=text, **extra
        )
    if kind == "unit":
        return rules.unit_cell(
            text,
            source,
            draft.reading if isinstance(draft.reading, str) else None,
            formula=extra["formula"],
            confidence=extra["confidence"],
        )
    return rules.text_cell(text, source, **extra)


def typed_cell(raw: RawCell | None, source: SourceLocation, currencies: CurrencyResolver) -> Cell:
    """Cells that need no text parsing: missing, empty, typed values, errors, unavailable."""
    if raw is None:
        return rules.empty_cell(source)
    extra = _extras(raw)
    value_type = raw.value_type
    if value_type is RawValueType.EMPTY:
        return rules.empty_cell(source, raw=raw.text, **extra)
    if value_type is RawValueType.ERROR:
        return rules.error_cell(
            raw.text or "#VALUE!",
            source,
            raw=raw.text,
            formula=extra["formula"],
            confidence=extra["confidence"],
        )
    if value_type is RawValueType.UNAVAILABLE:
        formula = extra["formula"] or FormulaInfo(expression="", cached_result_available=False)
        return rules.unavailable_cell(
            source, formula, raw=raw.text, number_format=extra["number_format"]
        )
    if value_type is RawValueType.NUMBER and raw.number is not None:
        if not is_bounded_decimal(raw.number):
            return rules.failed_cell(
                raw.text or str(raw.number), source, OUT_OF_RANGE_NOTE, **extra
            )
        number = NumberValue(
            value=raw.number,
            currency=currencies.find_in_number_format(raw.number_format),
            is_percent=_format_is_percent(raw.number_format),
        )
        return rules.number_cell(number, source, raw=raw.text, **extra)
    if value_type is RawValueType.BOOLEAN and raw.boolean is not None:
        return rules.typed_cell(
            BooleanValue(value=raw.boolean), DataType.BOOLEAN, source, raw=raw.text, **extra
        )
    if value_type is RawValueType.DATETIME and raw.temporal is not None:
        temporal = raw.temporal
        if isinstance(temporal, datetime):
            if temporal.time() == time(0) and not _format_has_time(raw.number_format):
                value: DateValue | DateTimeValue = DateValue(value=temporal.date())
            else:
                value = DateTimeValue(value=temporal)
        elif isinstance(temporal, date):
            value = DateValue(value=temporal)
        else:  # a time of day: no canonical type; keep the text
            return rules.text_cell(raw.text or temporal.isoformat(), source, **extra)
        data_type = DataType.DATE if isinstance(value, DateValue) else DataType.DATETIME
        return rules.typed_cell(value, data_type, source, raw=raw.text, **extra)
    return rules.text_cell(raw.text or "", source, **extra)


def _number_cell(
    reading: NumberReading,
    source: SourceLocation,
    text: str,
    status: ParseStatus,
    note: str | None,
    extra: _Extras,
) -> Cell:
    number = NumberValue(
        value=reading.value, currency=reading.currency, is_percent=reading.is_percent
    )
    return rules.number_cell(number, source, raw=text, status=status, note=note, **extra)


class _Extras(TypedDict):
    """What a cell keeps from its raw source, whatever its value."""

    formula: FormulaInfo | None
    number_format: str | None
    confidence: float | None


def _extras(raw: RawCell) -> _Extras:
    formula = (
        FormulaInfo(
            expression=raw.formula,
            cached_result_available=raw.value_type is not RawValueType.UNAVAILABLE,
        )
        if raw.formula
        else None
    )
    return {"formula": formula, "number_format": raw.number_format, "confidence": raw.confidence}


def _strip_literals(number_format: str) -> str:
    """A number format without quoted text, bracketed sections and escaped characters."""
    out: list[str] = []
    quoted = bracket = escaped = False
    for ch in number_format:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not quoted:
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif ch == "[" and not quoted:
            bracket = True
        elif ch == "]" and bracket:
            bracket = False
        elif not quoted and not bracket:
            out.append(ch)
    return "".join(out)


def _format_is_percent(number_format: str | None) -> bool:
    if not number_format:
        return False
    return "%" in _strip_literals(number_format[:255])


def _format_has_time(number_format: str | None) -> bool:
    if not number_format:
        return False
    bare = _strip_literals(number_format[:255]).casefold()
    return "h" in bare or "s" in bare or "am/pm" in bare


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _NOTE_TEXT_CHARS else text[: _NOTE_TEXT_CHARS - 1] + "…"


def _plain(value: Decimal) -> str:
    return format(value, "f")


__all__ = ["CellParser", "Draft", "ValueMarker", "finish", "typed_cell"]
