"""The one place where configured regular expressions meet document text.

Python's ``re`` cannot be interrupted, and document text is untrusted: a 32 KiB cell or a
shared string referenced by thousands of cells must not turn a pattern with a little
backtracking into minutes of CPU. Every configured pattern (domain profiles, detector
parameters) is therefore compiled here and applied only through :func:`search` and
:func:`fullmatch`, which

* look at no more than :data:`MAX_MATCH_CHARS` characters of the text, and
* memoize results per (pattern, text), so a repeated shared string costs one match.

Patterns come only from trusted, server-side configuration (profiles); plans cannot set them.
``tests/unit/profiles/test_pattern_safety.py`` times every built-in pattern against
adversarial strings.
"""

from __future__ import annotations

import re
from functools import lru_cache

MAX_MATCH_CHARS = 500
_FLAGS = re.IGNORECASE


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a configured pattern (case-insensitive). Raises ``ValueError`` when invalid."""
    try:
        return re.compile(pattern, _FLAGS)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression {pattern!r}: {exc}") from exc


def search(pattern: str, text: str) -> re.Match[str] | None:
    """``re.search`` over the first :data:`MAX_MATCH_CHARS` characters of ``text``."""
    return _search(pattern, text[:MAX_MATCH_CHARS])


def fullmatch(pattern: str, text: str) -> re.Match[str] | None:
    """``re.fullmatch``; text longer than :data:`MAX_MATCH_CHARS` never matches (a value that
    long cannot be a valid code, unit or token)."""
    if len(text) > MAX_MATCH_CHARS:
        return None
    return _fullmatch(pattern, text)


# The caches are keyed by the already truncated text, so they hold at most
# 16,384 x MAX_MATCH_CHARS characters however long the cells are.
@lru_cache(maxsize=16384)
def _search(pattern: str, text: str) -> re.Match[str] | None:
    return compile_pattern(pattern).search(text)


@lru_cache(maxsize=16384)
def _fullmatch(pattern: str, text: str) -> re.Match[str] | None:
    return compile_pattern(pattern).fullmatch(text)
