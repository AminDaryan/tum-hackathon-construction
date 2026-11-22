"""Comparison keys and names derived from document text (the original text is never changed).

* :func:`header_key`: the key headers, synonyms, labels and field ids are compared by. NFKC
  (``m³`` -> ``m3``), case folded, bracketed currency markers removed (``EP [€]`` -> ``ep``),
  every character that is not a letter, digit or ``%`` replaced by a space, whitespace
  collapsed: ``"Pos.-Nr."`` -> ``"pos nr"``, ``"Menge [m³]"`` -> ``"menge m3"``.
* :func:`snake_name`: the column's ``normalized_name`` (``"Unit price (EUR)"`` ->
  ``"unit_price_eur"``).
"""

from __future__ import annotations

import re
import unicodedata

from app.profiles.currency import CurrencyResolver

MAX_HEADER_CHARS = 200  # header text beyond this is not a column name
_BRACKETED = re.compile(r"[\[(]([^\])]{1,12})[\])]")
_NON_KEY = re.compile(r"[^\w%]+|_+")
_NON_NAME = re.compile(r"[^\w]+|_+")


def header_key(text: str | None, currencies: CurrencyResolver | None = None) -> str:
    """Comparison key of a header or synonym (empty string for empty text). When
    ``currencies`` is given, bracketed currency markers (``[€]``, ``(EUR)``) and words that
    are currency codes are dropped from the key, unless nothing else would remain."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text[:MAX_HEADER_CHARS]).casefold()
    if currencies is not None:
        folded = _BRACKETED.sub(
            lambda m: (
                " "
                if currencies.resolve_token(m.group(1)) or currencies.is_symbol(m.group(1))
                else m[0]
            ),
            folded,
        )
    key = " ".join(_NON_KEY.sub(" ", folded).split())
    if currencies is None or not key:
        return key
    words = [w for w in key.split() if currencies.resolve_token(w) is None]
    return " ".join(words) if words else key


def snake_name(text: str | None) -> str:
    """Lower snake case of a header (``""`` when nothing usable remains)."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text[:MAX_HEADER_CHARS]).casefold()
    return _NON_NAME.sub("_", folded).strip("_")


def column_letter(number: int) -> str:
    """Spreadsheet column letters for a 1-based column number (``28`` -> ``AB``)."""
    letters = ""
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def unique_names(names: list[str]) -> list[str]:
    """Make names unique by appending ``_2``, ``_3`` ... to later repetitions."""
    seen: dict[str, int] = {}
    taken = set(names)
    result: list[str] = []
    for name in names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        if count == 1:
            result.append(name)
            continue
        candidate = f"{name}_{count}"
        while candidate in taken:
            count += 1
            candidate = f"{name}_{count}"
        seen[name] = count
        taken.add(candidate)
        result.append(candidate)
    return result
