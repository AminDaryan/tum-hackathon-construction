"""Typed cell values.

A value is always tagged with its ``kind`` so it round-trips through JSON and SQLite without
ambiguity (the string ``"12.50"`` and the number ``12.50`` stay distinct). Numbers are
:class:`~decimal.Decimal`; they serialize to strings in JSON so no precision is lost.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BeforeValidator, Field

from app.models.base import FrozenModel

# Bounds for numbers read from documents: at most 28 significant digits, all of them between
# 1E-20 and 1E+24. Every value then spans at most 45 digit positions, so products, sums and
# differences of document values stay exact inside the 100-digit arithmetic context of
# app.validation.contracts.decimal_math, and hostile inputs such as "1E+999999" or 59-digit
# fractions are rejected at parse time instead of being rounded or skipped later.
MAX_SIGNIFICANT_DIGITS = 28
MAX_ADJUSTED_EXPONENT = 24  # most significant digit at most 1E+24, so |value| < 10**25
MIN_ADJUSTED_EXPONENT = -20  # least significant digit at least 1E-20


def _to_decimal(value: Any) -> Any:
    """Accept Decimal, int and numeric strings; reject floats so binary noise never enters."""
    if isinstance(value, bool):
        raise ValueError("booleans are not numbers")
    if isinstance(value, float):
        raise ValueError(
            "floats are not accepted for exact decimals; pass a string or Decimal instead"
        )
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            raise ValueError(f"{value!r} is not a decimal number") from None
    return value


def _finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("decimal values must be finite")
    return value


def significant_digits(value: Decimal) -> tuple[int, int]:
    """``(number of significant digits, exponent of the last one)`` of a finite Decimal,
    counted exactly. ``Decimal.normalize()`` is not used because it rounds to the context
    precision first, which would let a 59-digit value pass as 28 digits."""
    _, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)  # finite values only
    end = len(digits)
    while end > 1 and digits[end - 1] == 0:
        end -= 1
        exponent += 1
    start = 0
    while start < end - 1 and digits[start] == 0:
        start += 1
    return end - start, exponent


def _bounded(value: Decimal) -> Decimal:
    if value.is_zero():
        # A zero has no significant digits, but its exponent still decides how it is
        # written out (0E-999999 is a million characters): bound it like any other value.
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or not (
            MIN_ADJUSTED_EXPONENT <= exponent <= MAX_ADJUSTED_EXPONENT
        ):
            raise ValueError("number outside the supported range (digits from 1E-20 to 1E+24)")
        return value
    count, last_exponent = significant_digits(value)
    if count > MAX_SIGNIFICANT_DIGITS:
        raise ValueError(f"more than {MAX_SIGNIFICANT_DIGITS} significant digits")
    if value.adjusted() > MAX_ADJUSTED_EXPONENT or last_exponent < MIN_ADJUSTED_EXPONENT:
        raise ValueError("number outside the supported range (digits from 1E-20 to 1E+24)")
    return value


# Exact decimal for computed amounts (differences, sums, tolerances): finite, never a float.
ExactDecimal = Annotated[Decimal, BeforeValidator(_to_decimal), AfterValidator(_finite)]
# Exact decimal for values read from a document: additionally bounded in size.
BoundedDecimal = Annotated[
    Decimal, BeforeValidator(_to_decimal), AfterValidator(_finite), AfterValidator(_bounded)
]


def is_bounded_decimal(value: Decimal) -> bool:
    """True when ``value`` fits :data:`BoundedDecimal` (normalization checks before parsing)."""
    try:
        _bounded(_finite(value))
    except ValueError:
        return False
    return True


class DataType(StrEnum):
    """Data type of a cell, or the dominant data type of a column."""

    EMPTY = "empty"
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    ERROR = "error"  # spreadsheet error literal such as #REF! or #DIV/0!
    MIXED = "mixed"  # column level only: no type reaches the dominance threshold
    UNKNOWN = "unknown"  # the value could not be determined (ambiguous or unavailable)


class ParseStatus(StrEnum):
    """How a cell's typed value was obtained. Categorical on purpose: no invented scores."""

    EXACT = "exact"  # read verbatim from a typed source, or from unambiguous text
    INFERRED = "inferred"  # relied on column/document evidence (e.g. decimal separator)
    AMBIGUOUS = "ambiguous"  # several interpretations remained; no value was chosen
    FAILED = "failed"  # text did not match the expected type
    UNAVAILABLE = "unavailable"  # the source holds no value (formula without cached result)
    NOT_APPLICABLE = "not_applicable"  # empty cell, or plain text that needs no parsing
    # A conventional token in a numeric column ("Incl.", "Nil", "-", "entfällt", "nur EP"):
    # Cell.marker says what it means; no number is invented and the raw text is unchanged.
    MARKER = "marker"


class ValueMarker(StrEnum):
    """Generic meaning of a conventional token in a numeric column (see ParseStatus.MARKER).

    Domain profiles map their vocabulary to these meanings (``DomainProfile.value_markers``).
    """

    NIL = "nil"  # nothing to price: contributes zero ("Nil", "-", "-,--")
    INCLUDED_ELSEWHERE = "included_elsewhere"  # priced in another item ("Incl.", "enthalten")
    NOT_APPLICABLE = "not_applicable"  # the item does not apply ("N/A", "entfällt")
    BY_OTHERS = "by_others"  # supplied by another party ("By others", "bauseits")
    RATE_ONLY = "rate_only"  # priced as a unit rate only ("Rate only", "nur EP")
    LUMP_SUM = "lump_sum"  # quantity written as a lump-sum token ("psch", "LS")
    NOT_OFFERED = "not_offered"  # the bidder gives no price ("nicht angeboten", "not offered")


# Markers whose amount contributes nothing to a total (a total is complete without a number):
# the default of ``DomainProfile.zero_contribution_markers``, which decides.
ZERO_CONTRIBUTION_MARKERS: frozenset[ValueMarker] = frozenset(
    {
        ValueMarker.NIL,
        ValueMarker.INCLUDED_ELSEWHERE,
        ValueMarker.NOT_APPLICABLE,
        ValueMarker.BY_OTHERS,
    }
)


class NumberValue(FrozenModel):
    kind: Literal["number"] = "number"
    value: BoundedDecimal
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    is_percent: bool = False  # True when written as a percentage; ``value`` is already /100


class TextValue(FrozenModel):
    kind: Literal["text"] = "text"
    value: str


class DateValue(FrozenModel):
    kind: Literal["date"] = "date"
    value: date


class DateTimeValue(FrozenModel):
    kind: Literal["datetime"] = "datetime"
    value: datetime


class BooleanValue(FrozenModel):
    kind: Literal["boolean"] = "boolean"
    value: bool


class ErrorValue(FrozenModel):
    kind: Literal["error"] = "error"
    code: str  # "#REF!", "#DIV/0!", "#N/A", ...


CellValue = Annotated[
    NumberValue | TextValue | DateValue | DateTimeValue | BooleanValue | ErrorValue,
    Field(discriminator="kind"),
]


def value_to_display(value: CellValue | None) -> str | None:
    """Plain-text rendering used in issue observed/expected values and exports."""
    if value is None:
        return None
    if isinstance(value, NumberValue):
        if value.is_percent:
            text = format((value.value * 100).normalize(), "f") + " %"
        else:
            text = format(value.value, "f")
        if value.currency:
            text = f"{text} {value.currency}"
        return text
    if isinstance(value, ErrorValue):
        return value.code
    if isinstance(value, DateTimeValue | DateValue):
        return value.value.isoformat()
    if isinstance(value, BooleanValue):
        return "TRUE" if value.value else "FALSE"
    return value.value
