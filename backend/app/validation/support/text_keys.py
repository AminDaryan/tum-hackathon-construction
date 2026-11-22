"""Comparison keys of free text such as item descriptions.

:func:`description_key` is the key under which two descriptions count as the same text, and
:func:`char_ngrams` splits a description into the character n-grams that similarity
comparisons count (the similar-positions checks build their text index from them). Both are
pure functions of the text: no vocabulary, no language rules.
"""

from __future__ import annotations

import unicodedata


def description_key(text: str) -> str:
    """Comparison key of a description: Unicode NFKC, case folded, whitespace collapsed and
    trimmed (``"  Mauerwerk KS  ２４ cm "`` -> ``"mauerwerk ks 24 cm"``)."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def char_ngrams(text: str, n_min: int = 3, n_max: int = 5) -> list[str]:
    """The character n-grams (``n_min`` to ``n_max`` characters) inside the word boundaries
    of ``description_key(text)``, in order and with repeats (so counts can be weighted).

    Each word is padded with one space on both sides, so n-grams at the start and the end of a
    word are marked ("beton" gives ``" be"``, ``"bet"``, ..., ``"on "``) and no n-gram spans two
    words. A padded word shorter than ``n`` yields itself once, as its only n-gram of that
    length and longer: ``"m3"`` gives ``" m3"``, ``"m3 "`` and ``" m3 "``. Empty or blank text
    gives no n-grams.
    """
    if n_min < 1 or n_max < n_min:
        raise ValueError(f"need 1 <= n_min <= n_max, got n_min={n_min}, n_max={n_max}")
    grams: list[str] = []
    for word in description_key(text).split(" "):
        if not word:
            continue
        padded = f" {word} "
        for n in range(n_min, n_max + 1):
            if len(padded) <= n:
                grams.append(padded)
                break
            grams.extend(padded[start : start + n] for start in range(len(padded) - n + 1))
    return grams
