"""Text matching for the risk checks: folding, word lists, bounded patterns and quotes.

Every check matches on *folded* text: lower case, umlauts and ß spelled out (ä -> ae), runs of
whitespace collapsed to one space, and words split by a line-break hyphen joined again
("Abdich- tung" -> "abdichtung"). Word lists are substrings of folded text, so German
compounds match ("Kellerwandabdichtung" contains "abdicht").

Patterns are applied only through :mod:`app.core.patterns`, which looks at no more than 500
characters at a time: a long text is searched in overlapping windows, so a configured pattern
can never run for long on hostile document text. Quotes are cut from the original text, so
they are exactly what the bill says.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from app.core.patterns import MAX_MATCH_CHARS, compile_pattern, search

_SPELLED = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ẞ": "SS"}
_PATTERN_FOLD = str.maketrans(_SPELLED)
_LETTER = re.compile(r"[^\W\d_]")
# Window overlap: longer than any match a configured pattern is meant to make.
OVERLAP = 120
QUOTE_CHARS = 280
WORD_REACH = 40
MAX_QUOTE = 1000


def fold_pattern(pattern: str) -> str:
    """A configured pattern with its umlauts spelled out, to run on folded text (patterns are
    compiled case-insensitively)."""
    return pattern.translate(_PATTERN_FOLD)


@dataclass(frozen=True, slots=True)
class Folded:
    """Folded text and, for each of its characters, the index of the original character."""

    text: str
    origin: tuple[int, ...]


def fold_with_origin(original: str) -> Folded:
    out: list[str] = []
    origin: list[int] = []
    pending_space = False
    for index, char in enumerate(original):
        if char.isspace():
            pending_space = bool(out)
            continue
        if pending_space:
            # "abdich- tung": a hyphen between letters with a space after it is a line break.
            if len(out) >= 2 and out[-1] == "-" and _LETTER.match(out[-2]) and _LETTER.match(char):
                out.pop()
                origin.pop()
            else:
                out.append(" ")
                origin.append(index - 1)
            pending_space = False
        for piece in _SPELLED.get(char, char).lower():
            out.append(piece)
            origin.append(index)
    return Folded("".join(out), tuple(origin))


def fold(text: str | None) -> str:
    """Folded text (see the module docstring); ``""`` for ``None``."""
    return fold_with_origin(text).text if text else ""


def occurrences(folded: str, word: str) -> Iterator[int]:
    start = folded.find(word)
    while start != -1:
        yield start
        start = folded.find(word, start + 1)


def windows(text: str) -> Iterator[tuple[int, str]]:
    """(offset, slice) pairs of at most MAX_MATCH_CHARS characters covering ``text`` with an
    overlap of OVERLAP characters."""
    step = MAX_MATCH_CHARS - OVERLAP
    start = 0
    while True:
        yield start, text[start : start + MAX_MATCH_CHARS]
        if start + MAX_MATCH_CHARS >= len(text):
            return
        start += step


def find(pattern: str, text: str) -> tuple[int, int, re.Match[str]] | None:
    """The first match of a configured pattern in ``text`` as (start, end, match), with
    positions in ``text``."""
    for offset, piece in windows(text):
        found = search(pattern, piece)
        if found is not None:
            return offset + found.start(), offset + found.end(), found
    return None


def find_all(pattern: str, text: str) -> list[tuple[int, int, re.Match[str]]]:
    """Every match of a configured pattern as (start, end, match) with positions in ``text``,
    each once (windows overlap)."""
    compiled = compile_pattern(pattern)
    seen: set[int] = set()
    matches: list[tuple[int, int, re.Match[str]]] = []
    for offset, piece in windows(text):
        for found in compiled.finditer(piece):
            if offset + found.start() not in seen:
                seen.add(offset + found.start())
                matches.append((offset + found.start(), offset + found.end(), found))
    return matches


def around(text: str, start: int, end: int, chars: int) -> str:
    return text[max(0, start - chars) : end + chars]


def clause(folded: str, start: int, end: int, abbreviations: Sequence[str]) -> str:
    """The clause of folded text around [start, end): cut at ";" or at a full stop that ends a
    sentence (not after an abbreviation such as "inkl."), at most 200 characters each side."""
    left, right = clause_bounds(folded, start, end, abbreviations)
    return folded[left:right].strip()


def clause_bounds(
    folded: str, start: int, end: int, abbreviations: Sequence[str]
) -> tuple[int, int]:
    """Where :func:`clause` cuts, as (left, right) positions in ``folded``."""
    left = max(0, start - 200)
    for index in range(start - 1, left - 1, -1):
        if folded[index] == ";" or (
            folded[index] == "." and _ends_sentence(folded, index, abbreviations)
        ):
            left = index + 1
            break
    right = min(len(folded), end + 200)
    for index in range(end, right):
        if folded[index] == ";" or (
            folded[index] == "." and _ends_sentence(folded, index, abbreviations)
        ):
            right = index
            break
    return left, right


def _ends_sentence(folded: str, dot: int, abbreviations: Sequence[str]) -> bool:
    word_start = dot
    while word_start > 0 and not folded[word_start - 1].isspace():
        word_start -= 1
    word = folded[word_start:dot]
    if not word or word in abbreviations or f"{word}." in abbreviations:
        return False
    if len(word) <= 2 or word[-1].isdigit():
        return False
    return dot + 1 >= len(folded) or folded[dot + 1] == " "


def original_span(original: str, start: int, end: int) -> str:
    """The original text behind folded positions [start, end), exactly (no widening)."""
    folded = fold_with_origin(original)
    if start >= end or end > len(folded.origin):
        return ""
    return original[folded.origin[start] : folded.origin[end - 1] + 1]


def quote(original: str, start: int, end: int, chars: int = QUOTE_CHARS) -> str:
    """The original text behind folded positions [start, end), widened to about ``chars``
    characters at word boundaries; verbatim, with "…" where it was cut."""
    folded = fold_with_origin(original)
    if not folded.origin:
        return original.strip()
    first = folded.origin[min(start, len(folded.origin) - 1)]
    last = folded.origin[min(max(end - 1, 0), len(folded.origin) - 1)] + 1
    spare = max(0, chars - (last - first)) // 2
    left, right = max(0, first - spare), min(len(original), last + spare)
    # Widen to word boundaries, by at most WORD_REACH characters: a long token (embedded image
    # data, a URL) has no boundary to find.
    floor, ceiling = max(0, left - WORD_REACH), min(len(original), right + WORD_REACH)
    while left > floor and not original[left - 1].isspace():
        left -= 1
    while right < ceiling and not original[right].isspace():
        right += 1
    text = clip(" ".join(original[left:right].split()), MAX_QUOTE)
    return ("…" if left > 0 else "") + text + ("…" if right < len(original) else "")


def original_text(original: str, start: int, end: int, fallback: str) -> str:
    """The original characters behind folded positions [start, end) (``fallback`` when they lie
    outside ``original``, e.g. in a folded item type appended to it)."""
    origin = fold_with_origin(original).origin
    if not 0 <= start < end <= len(origin):
        return fallback
    return original[origin[start] : origin[end - 1] + 1]


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
