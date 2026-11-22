"""Helpers shared by the formula, reference and unit detectors (private module: not discovered).

``formula_errors``, ``reference_integrity``, ``unit_vocabulary`` and ``unit_compatibility`` use
these small, domain-neutral helpers: the bounded window of text that configured patterns
examine, repeated matching through :mod:`app.core.patterns` (the only place where configured
regular expressions meet document text), pattern validation for config models, readable
column labels, stable subject keys and row lists for grouped findings. The BoQ text checks
(``app.validation.domain.boq``) read long texts through the same windows and matching.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence

from app.core import patterns
from app.core.a1 import column_letter
from app.models.dataset import Cell, Column, Row, Table
from app.models.source import SourceKind
from app.validation.contracts.context import ValidationContext
from app.validation.deterministic._support import field_label

__all__ = [
    "MAX_MATCHES_PER_TEXT",
    "checked_pattern",
    "clip",
    "column_key",
    "column_label",
    "describe_rows",
    "find_captures",
    "find_spans",
    "match_window",
    "raw_preview",
    "short_digest",
    "windows",
]

MAX_MATCHES_PER_TEXT = 16  # matches collected from one text by find_spans and find_captures
_RAW_PREVIEW = 60  # characters of a cell text quoted in evidence
_MASK = "\x00"  # replaces a found match before the next search (see find_spans)

# A match: its start and end, and the span of the pattern's first group (``None`` when the
# pattern has no group or the group did not take part in the match).
Span = tuple[int, int, tuple[int, int] | None]


def clip(text: str, limit: int) -> str:
    """``text`` shortened to at most ``limit`` characters (an ellipsis marks the cut)."""
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def raw_preview(cell: Cell) -> str:
    """The cell's text as read, on one line and clipped for an evidence detail."""
    text = " ".join((cell.raw_value or "").split())
    return clip(text, _RAW_PREVIEW) if text else "(no text)"


def short_digest(text: str) -> str:
    """Stable 16-character hex digest, used as the subject of grouped findings whose key is
    document text (a description) that may be long."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- columns, rows
def column_key(column: Column) -> str:
    """Subject part for findings grouped per column. Built from the source column number,
    not the generated column id, so fingerprints survive re-normalization (ADR 0003)."""
    return f"column_{column.source_column_number}"


def column_label(context: ValidationContext, table: Table, column: Column) -> str:
    """Readable name of a column: the profile label of its field ("Line total"), else its
    header ("column 'Bemerkung'"), else its position ("column F", or "column 6" for sources
    that are not spreadsheets)."""
    if column.mapping is not None:
        return field_label(context, column.mapping.field_id)
    header = " ".join((column.original_header or "").split())
    if header:
        return f"column '{clip(header, 40)}'"
    if table.source.kind is SourceKind.SPREADSHEET:
        return f"column {column_letter(column.source_column_number)}"
    return f"column {column.source_column_number}"


def describe_rows(rows: Sequence[tuple[Table, Row]], limit: int = 6) -> str:
    """Source rows for explanations, grouped by table in the given order: ``"'LV' row 5"``,
    ``"'LV' rows 5, 9 and 14"``, ``"'LV' rows 5, 9; 'Los 2' row 3 and 4 more"``."""
    groups: list[tuple[Table, list[str]]] = []
    for table, row in rows[:limit]:
        if groups and groups[-1][0] is table:
            groups[-1][1].append(str(row.source_row_number))
        else:
            groups.append((table, [str(row.source_row_number)]))
    more = len(rows) - limit
    parts: list[str] = []
    for table, numbers in groups:
        noun = "row" if len(numbers) == 1 else "rows"
        if len(groups) == 1 and len(numbers) > 1 and more <= 0:
            listed = f"{', '.join(numbers[:-1])} and {numbers[-1]}"
        else:
            listed = ", ".join(numbers)
        parts.append(f"'{table.name}' {noun} {listed}")
    text = "; ".join(parts)
    return f"{text} and {more} more" if more > 0 else text


# --------------------------------------------------------------------------- patterns
def checked_pattern(pattern: str, *, groups: int | None) -> str:
    """Validate a configured pattern for a config model: it compiles (case-insensitive, as
    :mod:`app.core.patterns` applies it), has exactly ``groups`` capture groups when
    ``groups`` is given, and does not match the empty text (such a pattern would match every
    cell). Raises ``ValueError`` (Pydantic reports it as a validation error)."""
    compiled = patterns.compile_pattern(pattern)
    if groups is not None and compiled.groups != groups:
        raise ValueError(
            f"pattern must have exactly {groups} capture group(s), found {compiled.groups}: "
            f"{pattern!r}"
        )
    if compiled.search("") is not None:
        raise ValueError(f"pattern matches empty text, so it would match every cell: {pattern!r}")
    return pattern


def match_window(text: str) -> tuple[str, bool]:
    """The part of ``text`` that configured patterns examine, and whether it was cut.

    :mod:`app.core.patterns` looks at no more than ``MAX_MATCH_CHARS`` characters. A longer
    text is cut at the last whitespace before that bound instead, so no word is split (a cut
    word could match a pattern such as ``\\bplant\\b`` it does not contain, or let an end
    anchor match inside it). A text without whitespace in the window is cut at the bound."""
    limit = patterns.MAX_MATCH_CHARS
    if len(text) <= limit:
        return text, False
    if text[limit].isspace():
        return text[:limit], True
    for index in range(limit - 1, 0, -1):
        if text[index].isspace():
            return text[:index], True
    return text[:limit], True


def windows(text: str, overlap: int) -> Iterator[tuple[int, str]]:
    """``(offset, window)`` pairs that cover ``text`` for patterns that examine no more than
    ``MAX_MATCH_CHARS`` characters: the text itself when it fits, else the windows that
    :func:`match_window` cuts at whitespace, each starting at the first word start at most
    ``overlap`` characters before the previous window ended. A match up to about ``overlap``
    characters long that a cut splits is whole in the next window; a match that crosses a cut
    and is longer than the overlap can be missed."""
    limit = patterns.MAX_MATCH_CHARS
    start = 0
    while True:
        window, cut = match_window(text[start : start + limit + 1])
        yield start, window
        if not cut:
            return
        end = start + len(window)
        following = max(end - overlap, start + 1)
        while following < end and not text[following - 1].isspace():
            following += 1
        start = following


def find_spans(pattern: str, window: str, *, limit: int = MAX_MATCHES_PER_TEXT) -> list[Span]:
    """Non-overlapping matches of ``pattern`` in ``window`` (already bounded by
    :func:`match_window`), leftmost first, as offsets into ``window`` (see :data:`Span`).

    ``app.core.patterns`` offers ``search`` only, so each found match is masked with NUL
    characters before the next search: positions keep their meaning (``^`` still matches only
    at the real start) and a later match cannot reuse text of an earlier one. At most
    ``limit`` searches are made; an empty match ends the search."""
    found: list[Span] = []
    current = window
    for _ in range(limit):
        match = patterns.search(pattern, current)
        if match is None or match.end() <= match.start():
            break
        start, end = match.span()
        if _MASK not in current[start:end]:
            group = match.span(1) if match.re.groups and match.start(1) >= 0 else None
            found.append((start, end, group))
        current = current[:start] + _MASK * (end - start) + current[end:]
    return found


def find_captures(
    pattern: str, window: str, *, limit: int = MAX_MATCHES_PER_TEXT
) -> list[tuple[str, str]]:
    """Non-overlapping matches of a one-group ``pattern`` in ``window`` (already bounded by
    :func:`match_window`), leftmost first, as ``(matched text, captured text)`` pairs, found
    as :func:`find_spans` finds them. Matches whose captured group did not participate are
    skipped."""
    return [
        (window[start:end], window[group[0] : group[1]])
        for start, end, group in find_spans(pattern, window, limit=limit)
        if group is not None
    ]
