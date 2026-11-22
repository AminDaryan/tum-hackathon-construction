"""Anonymisation tokens in bill text, which no check may read as words.

The sample bills were anonymised: names, places and some technical words were replaced by
tokens such as ``[PERSON_074]``, ``[ORT_030]``, ``ORT_030``, ``[PERSON_00000000083]``,
``PER89``, ``PER0033`` (inside "Sand-PER0033-Gemisch"), ``FIR62``, ``TEL00009``, ``P125`` and
``###``. A token is never vague wording, a typo or a material, so a match that falls on a token
is skipped (:func:`overlaps_token`), or the token is blanked out before any pattern sees the
text (:func:`mask_tokens`), and a token is never quoted as the thing a finding is about.

The pattern is fixed and case-sensitive (the anonymiser writes capitals): bracketed upper-case
tags ending in a number, the same tags without brackets (``ORT_030``), the bare forms
``PER``/``TEL``/``ORT``/``FIR`` plus digits and ``P`` plus three digits, and runs of two or
more ``#``. It has no nested quantifiers and is linear in the length of the text.
"""

from __future__ import annotations

import re

TOKEN = re.compile(
    r"\[[A-ZÄÖÜ]+(?:_[A-ZÄÖÜ0-9]+)*_\d+\]"  # [PERSON_074], [ORT_00030], [PROJEKT_001]
    r"|\b[A-ZÄÖÜ]{2,}_\d+\b"  # ORT_030, without brackets
    r"|\b(?:PER|TEL|ORT|FIR)\d{2,}\b"  # PER89, PER0033, TEL00009, FIR62
    r"|\bP\d{3}\b"  # P125
    r"|#{2,}"  # ###
)


def token_spans(text: str) -> list[tuple[int, int]]:
    """Start and end offsets of the tokens in ``text``, in order."""
    return [match.span() for match in TOKEN.finditer(text)]


def overlaps_token(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]`` touches a token (shares at least one character with it)."""
    return any(left < end and start < right for left, right in token_spans(text))


def is_token(word: str) -> bool:
    """Whether ``word`` (stripped of surrounding punctuation) is a token."""
    return TOKEN.fullmatch(word.strip(" ,.;:!?()")) is not None


def mask_tokens(text: str) -> str:
    """``text`` with every token replaced by spaces of the same length, so offsets into the
    masked text are offsets into ``text`` and a quote can be cut from the text as written."""
    return TOKEN.sub(lambda match: " " * len(match.group()), text)
