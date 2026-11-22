"""Locale-aware parsing of number text. Pure functions; never ``float``.

Accepted: an optional sign (``+``, ``-``, U+2212) or a trailing minus (``1234,50-``),
accounting parentheses (``(1.234,50)``, see ``LocaleSettings.parenthesized_numbers``), one
currency marker before or after the number (``€ 1.234,50``, ``1,234.50 EUR``; the markers
are the currency vocabulary's symbols and 2-5 letter words that are aliases, and its ambiguous
symbols are accepted without deciding the currency), a trailing ``%`` (the value is divided
by 100 and flagged), grouping with ``.``, ``,``, spaces (including no-break and thin spaces)
or apostrophes (first group 1-3 digits, later groups exactly 3), and plain scientific notation
(``1.5E+3``).

Which character is the decimal separator:

* only digits: an integer;
* ``.`` and ``,`` both present: the right-most one (it must occur once, after every grouping
  character);
* one kind of ``.``/``,`` occurring more than once: grouping (``1.234.567``), so the other
  character is the decimal separator;
* spaces or apostrophes with one ``.`` or ``,``: that one is decimal (``1 234,56``);
* exactly one ``.`` or ``,`` followed by a number of digits other than three, or after a group
  that cannot be a thousands group (``0,125``, ``1234,567``, ``,5``): decimal;
* exactly one ``.`` or ``,`` with three digits after a 1-3 digit group (``1,234``,
  ``12.500``): **ambiguous** (:class:`AmbiguousNumber`); normalization resolves it from column
  or document evidence, the profile locale, or leaves it unread.

Unambiguous readings report the decimal separator they reveal (``decimal_evidence``), which is
the column and document evidence. Anything else (``approx. 5``, ``5-10``, ``1.2.3``, ``n/a``,
more than 30 digits, a word that is not a currency) is not a number (``None``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.models.values import is_bounded_decimal
from app.profiles.currency import CurrencyResolver

MAX_NUMBER_TEXT_CHARS = 64
MAX_DIGITS = 30
_SPACES = {" ": " ", " ": " ", " ": " ", " ": " ", "’": "'"}
_SPACE_TRANSLATION = str.maketrans(_SPACES)
_MINUS = {"-", "−", "–"}
_SCIENTIFIC = re.compile(r"^(\d{1,28})(?:\.(\d{1,28}))?[eE]([+-]?\d{1,6})$")
_GROUPING = frozenset({" ", "'"})
_SEPARATORS = frozenset({".", ",", " ", "'"})

DecimalMark = Literal[".", ","]


def _mark(ch: str) -> DecimalMark:
    """``ch``, which the caller has checked is "." or ",", as a decimal mark."""
    return "." if ch == "." else ","


@dataclass(frozen=True, slots=True)
class NumberReading:
    """An unambiguous number. ``decimal_evidence`` is the decimal separator the text shows
    (``None`` for integers without grouping evidence)."""

    value: Decimal
    currency: str | None = None
    is_percent: bool = False
    decimal_evidence: DecimalMark | None = None


@dataclass(frozen=True, slots=True)
class AmbiguousNumber:
    """``1,234``: ``as_decimal`` reads the separator as decimal (1.234), ``as_grouping`` as
    thousands grouping (1234)."""

    separator: DecimalMark
    as_decimal: Decimal
    as_grouping: Decimal
    currency: str | None = None
    is_percent: bool = False

    def resolve(self, decimal_separator: DecimalMark) -> NumberReading:
        value = self.as_decimal if decimal_separator == self.separator else self.as_grouping
        return NumberReading(value, self.currency, self.is_percent, None)


@dataclass(frozen=True, slots=True)
class ParenthesizedNumber:
    """``(1.234,50)`` under ``parenthesized_numbers: ambiguous``: a negative amount, or an
    amount "not included in the total"; no value is chosen."""

    text: str


@dataclass(frozen=True, slots=True)
class OutOfRange:
    """A number that does not fit the supported range (``BoundedDecimal``)."""

    text: str


NumberParse = NumberReading | AmbiguousNumber | ParenthesizedNumber | OutOfRange | None


def parse_number(
    text: str,
    *,
    currencies: CurrencyResolver,
    parentheses: Literal["negative", "ambiguous"] = "negative",
) -> NumberParse:
    """Parse number text (see the module docstring). ``None`` means "not a number"."""
    core = text.strip().translate(_SPACE_TRANSLATION).strip()
    if not core or len(core) > MAX_NUMBER_TEXT_CHARS:
        return None
    parenthesized, core = _strip_parentheses(core)
    percent = core.endswith("%")
    if percent:
        core = core[:-1].rstrip()
    stripped = _strip_currency(core, currencies)
    if stripped is None:
        return None
    core, currency, marked = stripped
    if not parenthesized:
        parenthesized, core = _strip_parentheses(core)
    negative, core = _strip_sign(core)
    if not marked:
        stripped = _strip_currency(core, currencies)
        if stripped is None:
            return None
        core, currency, marked = stripped
    if not core or not core[0].isascii():
        return None
    if parenthesized and negative:
        return None  # "(-5)" is not a convention we can read
    parsed = _parse_core(core)
    if parsed is None:
        return None
    if parenthesized and parentheses == "ambiguous":
        return ParenthesizedNumber(text)
    negative = negative or parenthesized
    if isinstance(parsed, AmbiguousNumber):
        return AmbiguousNumber(
            parsed.separator,
            _finish(parsed.as_decimal, negative, percent),
            _finish(parsed.as_grouping, negative, percent),
            currency,
            percent,
        )
    value, evidence = parsed
    value = _finish(value, negative, percent)
    if not is_bounded_decimal(value):
        return OutOfRange(text)
    return NumberReading(value, currency, percent, evidence)


def _finish(value: Decimal, negative: bool, percent: bool) -> Decimal:
    if percent:
        value = value.scaleb(-2)
    return -value if negative else value


def _strip_parentheses(core: str) -> tuple[bool, str]:
    if len(core) >= 3 and core[0] == "(" and core[-1] == ")":
        return True, core[1:-1].strip()
    return False, core


def _strip_sign(core: str) -> tuple[bool, str]:
    if core[:1] in _MINUS:
        return True, core[1:].lstrip()
    if core[:1] == "+":
        return False, core[1:].lstrip()
    if len(core) > 1 and core[-1] in _MINUS:
        return True, core[:-1].rstrip()
    return False, core


def _strip_currency(core: str, currencies: CurrencyResolver) -> tuple[str, str | None, bool] | None:
    """Remove one leading or trailing currency marker: ``(rest, code, marker_found)``;
    ``None`` when a word that is not a currency is attached (the text is not a number)."""
    markers: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
        (currencies.leading_marker, lambda m: core[m.end() :]),
        (currencies.trailing_marker, lambda m: core[: m.start()]),
    )
    for pattern, rest in markers:
        found = pattern.search(core)
        if found is None:
            continue
        token = found.group(1)
        if currencies.is_ambiguous(token):
            return rest(found).strip(), None, True
        code = currencies.resolve_token(token)
        if code is None:
            return None
        return rest(found).strip(), code, True
    return core, None, False


def _parse_core(core: str) -> tuple[Decimal, DecimalMark | None] | AmbiguousNumber | None:
    if core.isascii() and core.isdigit():
        return (Decimal(core), None) if len(core) <= MAX_DIGITS else None
    scientific = _SCIENTIFIC.match(core)
    if scientific:
        try:
            return Decimal(core), None
        except InvalidOperation:  # pragma: no cover - the pattern admits valid numbers only
            return None
    if any(not (ch.isascii() and ch.isdigit()) and ch not in _SEPARATORS for ch in core):
        return None
    if sum(ch.isdigit() for ch in core) > MAX_DIGITS:
        return None
    if core[0] in ".," and core[1:].isdigit():
        return Decimal("0" + "." + core[1:]), _mark(core[0])
    if not (core[0].isdigit() and core[-1].isdigit()):
        return None
    separators = [ch for ch in core if not ch.isdigit()]
    marks = [_mark(ch) for ch in separators if ch in ".,"]
    spaces = [ch for ch in separators if ch in _GROUPING]
    if "." in marks and "," in marks:
        decimal = marks[-1]
        if marks.count(decimal) != 1 or separators[-1] != decimal:
            return None
        return _grouped_with_decimal(core, decimal)
    if spaces:
        if not marks:
            digits = _grouped_integer(core, spaces[0])
            return None if digits is None else (Decimal(digits), None)
        if len(marks) != 1 or separators[-1] != marks[0]:
            return None
        return _grouped_with_decimal(core, marks[0])
    mark = marks[0]
    if len(marks) > 1:
        digits = _grouped_integer(core, mark)
        evidence: DecimalMark = "," if mark == "." else "."
        return None if digits is None else (Decimal(digits), evidence)
    left, right = core.split(mark)
    if len(right) != 3 or len(left) > 3 or left.startswith("0"):
        return Decimal(f"{left}.{right}"), mark
    return AmbiguousNumber(mark, Decimal(f"{left}.{right}"), Decimal(left + right))


def _grouped_with_decimal(core: str, decimal: DecimalMark) -> tuple[Decimal, DecimalMark] | None:
    integer, fraction = core.rsplit(decimal, 1)
    if not fraction.isdigit():
        return None
    grouping = {ch for ch in integer if not ch.isdigit()}
    if len(grouping) > 1:
        return None
    digits = _grouped_integer(integer, grouping.pop()) if grouping else integer
    if digits is None or not digits.isdigit():
        return None
    return Decimal(f"{digits}.{fraction}"), decimal


def _grouped_integer(text: str, separator: str) -> str | None:
    """Digits of ``text`` grouped by ``separator`` (first group 1-3 digits, then 3)."""
    groups = text.split(separator)
    if not (1 <= len(groups[0]) <= 3) or any(len(g) != 3 for g in groups[1:]):
        return None
    if not all(g.isdigit() for g in groups):
        return None
    return "".join(groups)
