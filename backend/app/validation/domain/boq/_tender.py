"""Helpers shared by the tender review checks (``domain.boq_*``): item numbers, item texts and
phrase matching.

The checks read a bill the way a tender estimator (Kalkulator) does before pricing it: are
items missing, can each description be priced, does an item contradict itself, are there
typing slips. Wording lists are plain phrases (profile-tunable); they are matched as whole
words, case-insensitively, over the whole text (long texts included), never as user-supplied
regular expressions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from app.models.dataset import CellRef, Row, Table
from app.validation.contracts.context import ValidationContext

WORD = re.compile(r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)*")
_CODE_SEPARATOR = re.compile(r"[.\s]+")


def code_parts(code: str | None) -> tuple[str, ...]:
    """An ordinal number (OZ) as comparable parts: ``"01.02.0030."`` -> ``("1", "2", "30")``.
    Leading zeros do not matter; empty parts (``"1.2..7"``) are dropped."""
    if not code:
        return ()
    return tuple(
        part.lstrip("0") or "0" for part in _CODE_SEPARATOR.split(code.strip(". ")) if part
    )


def phrase_pattern(phrases: Iterable[str]) -> re.Pattern[str] | None:
    """One case-insensitive pattern matching any of ``phrases`` as whole words (whitespace in a
    phrase matches any run of whitespace). ``None`` when there are no phrases."""
    alternatives = []
    for phrase in sorted({p.strip() for p in phrases if p.strip()}, key=len, reverse=True):
        body = r"\s+".join(re.escape(part) for part in phrase.split())
        start = r"(?<!\w)" if phrase[0].isalnum() else ""
        end = r"(?!\w)" if phrase[-1].isalnum() else ""
        alternatives.append(f"{start}{body}{end}")
    if not alternatives:
        return None
    return re.compile("|".join(alternatives), re.IGNORECASE)


def matches(
    pattern: re.Pattern[str] | None,
    text: str,
    limit: int = 3,
    skip: re.Pattern[str] | None = None,
) -> list[str]:
    """Up to ``limit`` distinct phrases ``pattern`` finds in ``text``, as written. A phrase that
    overlaps a match of ``skip`` (wording another check reports) is left out."""
    if pattern is None or not text:
        return []
    taken = [m.span() for m in skip.finditer(text)] if skip is not None else []
    found: list[str] = []
    for match in pattern.finditer(text):
        if any(match.start() < end and start < match.end() for start, end in taken):
            continue
        phrase = " ".join(match.group(0).split())
        if phrase.lower() not in (f.lower() for f in found):
            found.append(phrase)
            if len(found) >= limit:
                break
    return found


def texts(
    context: ValidationContext, table: Table, row: Row, short_field: str, long_field: str
) -> tuple[str, str]:
    """The short text and long text of ``row`` (empty strings when absent)."""
    short = context.text(table, row, short_field) or ""
    long = context.text(table, row, long_field) if context.has_fields(table, long_field) else ""
    return short, long or ""


def anchor(context: ValidationContext, table: Table, row: Row, *fields: str) -> list[CellRef]:
    """The cells of ``fields`` that the table maps (the first ones only), to highlight."""
    refs = [context.cell_ref(table, row, f) for f in fields if context.has_fields(table, f)]
    return refs[:1]


def quote(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def listing(values: Sequence[str], limit: int = 12) -> str:
    shown = ", ".join(values[:limit])
    return f"{shown} and {len(values) - limit} more" if len(values) > limit else shown
