"""Canonical form of hierarchical identifiers (item codes, section codes, references).

Normalization (section levels, subtotal scopes, reviewer decisions keyed by codes) and the
detectors (reference integrity, uniqueness, code-prefix scopes) must agree on when two codes
are the same and when one code contains another, so both import these helpers from here.

Rules (pinned by ``tests/unit/core/test_codes.py``):

* :func:`normalize_code`: Unicode NFKC, case folded, all whitespace and invisible format
  characters (category ``Cf``) removed, trailing dots stripped:
  ``' 01.02.0030. '`` -> ``'01.02.0030'``.
* :func:`code_segments`: the normalized code split at ``.`` and ``/``; empty segments are
  dropped; leading zeros are removed from segments made only of ASCII digits, so
  ``'01.02.0030'`` and ``'1.2.30'`` compare equal. Non-ASCII digits (``'١٢'``) stay text:
  ``str.isdigit`` alone would accept them, and ``int()`` would convert them silently.
  A segment longer than :data:`MAX_CODE_SEGMENT_CHARS` is not a plausible code: ``None``.
* :func:`is_strict_prefix`: ``(1,)`` is a strict prefix of ``(1, 2)``, not of ``(1,)``.

Document text must never be able to raise here: there is no ``int()`` conversion and no
unbounded work.
"""

from __future__ import annotations

import re
import unicodedata

MAX_CODE_SEGMENT_CHARS = 32
MAX_CODE_CHARS = 200  # longer text is not a code

_WHITESPACE = re.compile(r"\s+")
_SEPARATORS = re.compile(r"[./]")


def normalize_code(text: str | None) -> str | None:
    """Comparison key for an identifier, or ``None`` for empty or implausibly long input."""
    if text is None or len(text) > MAX_CODE_CHARS:
        return None
    folded = unicodedata.normalize("NFKC", text)
    # Invisible format characters (zero-width space, soft hyphen, BOM) are not part of a code.
    visible = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    key = _WHITESPACE.sub("", visible).casefold().rstrip(".")
    return key or None


def code_segments(text: str | None) -> tuple[str, ...] | None:
    """Segments of a dotted or slashed code, ASCII-digit segments without leading zeros."""
    key = normalize_code(text)
    if key is None:
        return None
    segments: list[str] = []
    for part in _SEPARATORS.split(key):
        if not part:
            continue
        if len(part) > MAX_CODE_SEGMENT_CHARS:
            return None
        if part.isascii() and part.isdigit():
            part = part.lstrip("0") or "0"
        segments.append(part)
    return tuple(segments) or None


def is_strict_prefix(prefix: tuple[str, ...] | None, code: tuple[str, ...] | None) -> bool:
    """True when ``prefix`` is a proper leading part of ``code``."""
    return (
        prefix is not None
        and code is not None
        and len(prefix) < len(code)
        and code[: len(prefix)] == prefix
    )


def same_code(a: str | None, b: str | None) -> bool:
    """True when both texts are codes with equal segments (``'01.02'`` equals ``'1.2'``)."""
    left, right = code_segments(a), code_segments(b)
    return left is not None and left == right
