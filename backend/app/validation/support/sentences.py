"""Sentences of German bill text (Kurztext, Langtext), for checks that read clauses.

A clause check asks whether one sentence names two things together ("Verbau ist mit
einzukalkulieren!"), so it needs the sentences of a text. :func:`split_sentences` splits on
``.``, ``!``, ``?`` and ``;`` followed by whitespace and an upper-case letter or a digit, except

* after the abbreviations in :data:`ABBREVIATIONS` ("ca. 5 m", "z. B. Kies", "Pos. 3"),
  matched without regard to case and only at the start of a word ("s." but not "Maßes."), and
* at a dot between two numbers ("Wie Position 5. 4. 17., jedoch", "am 1. 2. 2026"): GAEB
  printouts write position numbers that way, and a date is not a sentence end either.

Every sentence keeps its offsets in the text, so a finding can quote it as written. The
splitter is a pure function of the text: two fixed patterns without nested quantifiers, one
pass, linear in the length of the text. It knows no construction words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Abbreviations after which a dot does not end a sentence (plan 5a, B2 brief).
ABBREVIATIONS: tuple[str, ...] = (
    "einschl.",
    "inkl.",
    "ca.",
    "z. B.",
    "z.B.",
    "gem.",
    "lt.",
    "bzw.",
    "evtl.",
    "ggf.",
    "d. h.",
    "u. a.",
    "usw.",
    "Pos.",
    "Nr.",
    "max.",
    "min.",
    "mind.",
    "Std.",
    "St.",
    "lfd.",
    "zzgl.",
    "o. ä.",
    "u. ä.",
    "Abs.",
    "Art.",
    "Kap.",
    "Ziff.",
    "vgl.",
    "s.",
    "Gew.",
    "Pkt.",
)

# A possible sentence end: the mark and the whitespace after it.
_END = re.compile(r"[.!?;]\s+")


def _abbreviation_pattern(abbreviations: tuple[str, ...]) -> re.Pattern[str]:
    """One alternation of the abbreviations, longest first; the parts of "z. B." may be
    written with up to two whitespace characters or none between them ("z.B.")."""
    alternatives = []
    for abbreviation in sorted(abbreviations, key=len, reverse=True):
        parts = [part.strip() for part in abbreviation.split(".") if part.strip()]
        alternatives.append(r"\.\s{0,2}".join(re.escape(part) for part in parts) + r"\.")
    # Not preceded by a letter: "s." is an abbreviation, the end of "Maßes." is not.
    return re.compile(r"(?<![^\W\d_])(?:" + "|".join(alternatives) + ")", re.IGNORECASE)


_ABBREVIATION = _abbreviation_pattern(ABBREVIATIONS)


@dataclass(frozen=True, slots=True)
class Sentence:
    """One sentence: ``text`` is ``source[start:end]``, without the whitespace around it."""

    text: str
    start: int
    end: int


def split_sentences(text: str) -> list[Sentence]:
    """The sentences of ``text`` in order (see the module docstring). Blank text has none;
    text without a sentence end is one sentence."""
    protected = _abbreviation_dots(text)
    sentences: list[Sentence] = []
    start = 0
    for end in _END.finditer(text):
        mark = end.start()
        following = text[end.end()] if end.end() < len(text) else ""
        if not (following.isupper() or following.isdigit()):
            continue
        if text[mark] == "." and (
            mark in protected or (mark > 0 and text[mark - 1].isdigit() and following.isdigit())
        ):
            continue
        _append(sentences, text, start, mark + 1)
        start = end.end()
    _append(sentences, text, start, len(text))
    return sentences


def sentences(text: str) -> list[str]:
    """The sentences of ``text`` as strings."""
    return [sentence.text for sentence in split_sentences(text)]


def _abbreviation_dots(text: str) -> set[int]:
    """Offsets of the dots that belong to an abbreviation."""
    dots: set[int] = set()
    for match in _ABBREVIATION.finditer(text):
        dots.update(index for index in range(*match.span()) if text[index] == ".")
    return dots


def _append(sentences: list[Sentence], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        sentences.append(Sentence(text=text[start:end], start=start, end=end))
