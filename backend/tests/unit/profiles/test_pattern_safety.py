"""Configured regular expressions stay fast on hostile document text.

Python's ``re`` cannot be interrupted, so a pattern with nested or adjacent quantifiers could
spend minutes on one crafted cell. Every pattern of every built-in profile is timed here against
adversarial strings, through the same length bound that :mod:`app.core.patterns` applies in
production. A new pattern that backtracks badly fails this test before it ships.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest

from app.core import patterns
from app.models.profile import DomainProfile
from app.profiles.loader import ProfileCatalog

# Per (pattern, text) budget. Linear patterns take microseconds on 500 characters; a
# quadratic one takes milliseconds; anything cubic or exponential blows far past this.
BUDGET_SECONDS = 0.1

_WORDS = (
    "summe",
    "total",
    "titel",
    "gesamt",
    "nur",
    "bedarfsposition",
    "site",
    "wie pos",
    "übertrag",
    "mwst",
    "inkl",
    "alternative",
    "wahlposition (",
    "stundenlohnarbeiten",
    "entfällt",
    "wie vor",
    "vorbeschrieben",
    "as before",
)

ADVERSARIAL = [
    " " * 5000,
    "\t  " * 1700,
    "a" * 5000,
    "1" * 5000,
    "1." * 2500,
    "(" * 5000,
    "- " * 2500,
    "." * 5000,
    "0" * 4999 + "x",
    *(f"{word} " * (5000 // (len(word) + 1)) + "!" for word in _WORDS),
    *(word + " " * 4990 + "x" for word in _WORDS),
    *(word + "." * 2000 + " " * 2000 + "x" for word in _WORDS),
    "Summe Titel 01 " * 330,
    "wie Pos. " + "1." * 2400 + "x",
    "baustelleneinrichtung" + " " * 4970 + "x",
    "Bedarfsposition " * 100 + "mit " * 300 + "x",
]


def _profile_patterns(profile: DomainProfile) -> Iterator[tuple[str, str]]:
    rules = profile.row_classification
    for name in (
        "carry_forward_patterns",
        "gross_total_patterns",
        "tax_patterns",
        "grand_total_patterns",
        "adjustment_patterns",
        "summary_block_patterns",
        "subtotal_patterns",
    ):
        for pattern in getattr(rules, name):
            yield f"{profile.profile_id}.{name}", pattern
    for section in rules.section_patterns:
        yield f"{profile.profile_id}.section_patterns", section.pattern
    for rule in rules.totals_rules:
        yield f"{profile.profile_id}.totals_rules.{rule.rule_id}", rule.pattern
    if rules.section_code_pattern:
        yield f"{profile.profile_id}.section_code_pattern", rules.section_code_pattern
    for field in profile.fields:
        if field.constraints and field.constraints.pattern:
            yield f"{profile.profile_id}.fields.{field.field_id}", field.constraints.pattern
    yield from _nested_patterns(
        f"{profile.profile_id}.detector_defaults", profile.detector_defaults
    )


def _nested_patterns(path: str, value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and str(key).endswith("pattern"):
                yield f"{path}.{key}", item
            else:
                yield from _nested_patterns(f"{path}.{key}", item)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _nested_patterns(f"{path}[{index}]", item)


def _all_patterns() -> list[tuple[str, str]]:
    from app.core.config import BUILTIN_PROFILE_DIR

    catalog = ProfileCatalog.from_directories([BUILTIN_PROFILE_DIR])
    return [found for profile in catalog.list() for found in _profile_patterns(profile)]


ALL_PATTERNS = _all_patterns()


def test_every_profile_pattern_is_collected() -> None:
    # Guards the collector itself: the BoQ profile alone has dozens of patterns.
    assert len(ALL_PATTERNS) > 40
    assert any(".detector_defaults." in where for where, _ in ALL_PATTERNS)


def test_the_line_total_lump_sum_pattern_is_collected() -> None:
    where = {found for found, _ in ALL_PATTERNS}
    assert "boq.detector_defaults.deterministic.line_total.lump_sums.text_pattern" in where


@pytest.mark.parametrize(("where", "pattern"), ALL_PATTERNS, ids=[w for w, _ in ALL_PATTERNS])
def test_pattern_is_fast_on_adversarial_text(where: str, pattern: str) -> None:
    compiled = patterns.compile_pattern(pattern)
    for text in ADVERSARIAL:
        bounded = text[: patterns.MAX_MATCH_CHARS]
        started = time.perf_counter()
        compiled.search(bounded)  # uncached, exactly what patterns.search runs
        elapsed = time.perf_counter() - started
        assert elapsed < BUDGET_SECONDS, (
            f"{where}: {pattern!r} took {elapsed * 1000:.1f} ms on {text[:30]!r}..."
        )


def test_search_examines_a_bounded_prefix() -> None:
    late = "x" * patterns.MAX_MATCH_CHARS + "Summe"
    assert patterns.search(r"summe", late) is None
    assert patterns.search(r"summe", "Summe Titel 1") is not None  # case-insensitive


def test_fullmatch_refuses_overlong_text() -> None:
    assert patterns.fullmatch(r"\d+", "1" * patterns.MAX_MATCH_CHARS) is not None
    assert patterns.fullmatch(r"\d+", "1" * (patterns.MAX_MATCH_CHARS + 1)) is None


def test_repeated_texts_are_matched_once() -> None:
    text = "Summe Titel 07 " + "y" * 20
    assert patterns.search(r"summe", text) is patterns.search(r"summe", text)


def test_invalid_patterns_raise_value_error() -> None:
    with pytest.raises(ValueError, match="Invalid regular expression"):
        patterns.compile_pattern("(unclosed")
