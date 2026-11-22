"""The default patterns of the BoQ wording checks stay fast on hostile document text.

``tests/unit/profiles/test_pattern_safety.py`` times the patterns of the profile files; these
checks keep their defaults in code, so they are timed here the same way: each pattern on each
adversarial string, bounded as :mod:`app.core.patterns` bounds it, and the whole window-by-
window search of a cell as long as a GAEB Langtext can be."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from app.core import patterns
from app.validation.domain.boq._bill_text import search, search_all
from app.validation.domain.boq.boq_companion_work import CompanionWorkConfig
from app.validation.domain.boq.boq_required_attributes import RequiredAttributesConfig
from app.validation.domain.boq.boq_separate_payment import SeparatePaymentConfig
from app.validation.domain.boq.typos import BoqTyposDetector
from app.validation.support.tokens import mask_tokens
from tests.unit.profiles.test_pattern_safety import ADVERSARIAL, BUDGET_SECONDS
from tests.unit.validation.deterministic.references_fixtures import run
from tests.unit.validation.domain.boq_text_fixtures import bill, item

LONGEST_CELL = 32_767  # the longest Langtext the GAEB import writes into a cell
WHOLE_CELL_BUDGET_SECONDS = 1.0  # all windows of one such cell

EXTRA = [
    "-" * 5000,
    "a-" * 2500,
    "Rohr" * 1250,
    "Beton " * 800 + "!",
    "Z " * 2500,
    "1 " * 2500,
    "1/" * 2500,
    "1,5 x " * 800,
    '"' * 5000,
    "Ø" * 5000,
    "Boden " * 800 + "x",
    "Kernbohrung " * 400,
    "wird gesondert " * 300,
    "[" * 5000,
    "[A_" * 1600,
    "AB_" * 1600,
    "PER" * 1600,
    "#" * 5000,
]
TEXTS = [*ADVERSARIAL, *EXTRA]


def _default_patterns() -> Iterator[tuple[str, str]]:
    for pair in CompanionWorkConfig().pairs:
        for term in pair.triggers:
            yield f"{pair.rule_id}.trigger.{term.name}", term.pattern
        for index, pattern in enumerate(pair.trigger_requires):
            yield f"{pair.rule_id}.trigger_requires[{index}]", pattern
        for name in ("trigger_exclude", "own_text_pattern", "companion_pattern"):
            value = getattr(pair, name)
            if value:
                yield f"{pair.rule_id}.{name}", value
    for rule in RequiredAttributesConfig().rules:
        for index, conditions in enumerate(rule.triggers):
            for condition in conditions:
                yield f"{rule.rule_id}.triggers[{index}]", condition.pattern
        for condition in rule.excludes:
            yield f"{rule.rule_id}.excludes", condition.pattern
        if rule.ignore_in_description:
            yield f"{rule.rule_id}.ignore_in_description", rule.ignore_in_description
        yield f"{rule.rule_id}.attribute_pattern", rule.attribute_pattern
    yield "separate_payment.clause_pattern", SeparatePaymentConfig().clause_pattern


PATTERNS = list(_default_patterns())


def test_every_default_pattern_is_collected() -> None:
    assert len(PATTERNS) > 30


@pytest.mark.parametrize(("where", "pattern"), PATTERNS, ids=[w for w, _ in PATTERNS])
def test_default_pattern_is_fast_on_adversarial_text(where: str, pattern: str) -> None:
    compiled = patterns.compile_pattern(pattern)
    for text in TEXTS:
        bounded = text[: patterns.MAX_MATCH_CHARS]
        started = time.perf_counter()
        compiled.search(bounded)  # uncached, exactly what patterns.search runs
        elapsed = time.perf_counter() - started
        assert elapsed < BUDGET_SECONDS, (
            f"{where}: {pattern!r} took {elapsed * 1000:.1f} ms on {text[:30]!r}..."
        )


@pytest.mark.parametrize(("where", "pattern"), PATTERNS, ids=[w for w, _ in PATTERNS])
def test_searching_a_whole_long_cell_stays_bounded(where: str, pattern: str) -> None:
    for text in TEXTS[::3]:  # a sample: each window is already timed above
        # Distinct cells: the pattern cache must not hide the cost.
        cell = (text * (LONGEST_CELL // len(text) + 1))[: LONGEST_CELL - 8] + f" {where[:6]}"
        started = time.perf_counter()
        search(pattern, cell)
        search_all(pattern, cell)
        elapsed = time.perf_counter() - started
        assert elapsed < WHOLE_CELL_BUDGET_SECONDS, (
            f"{where}: {pattern!r} took {elapsed * 1000:.1f} ms on a cell of {text[:30]!r}..."
        )


def test_token_masking_is_linear() -> None:
    for text in TEXTS:
        cell = (text * (LONGEST_CELL // len(text) + 1))[:LONGEST_CELL]
        started = time.perf_counter()
        masked = mask_tokens(cell)
        elapsed = time.perf_counter() - started
        assert len(masked) == len(cell)
        assert elapsed < BUDGET_SECONDS, f"masking took {elapsed * 1000:.1f} ms on {text[:30]!r}"


def _letters(number: int) -> str:
    """A letters-only suffix ("aaa", "baa", ...): words with digits are not compared."""
    return "".join(chr(97 + (number // 26**place) % 26) for place in range(3))


def test_the_typo_check_compares_through_an_index_not_every_pair(boq_profile) -> None:
    # 20,000 words used once and 2,000 used three times: comparing every pair would take
    # 40 million distance computations.
    texts: list[list[str]] = [
        [f"Rohrleitungsabschnitt{_letters(i * 25 + j)}" for j in range(25)] for i in range(800)
    ]
    for k in range(2000):
        for use in range(3):
            texts[(3 * k + use) % 800].append(f"Schachtbauwerk{_letters(k)}")
    lines = [item(f"{i // 100}.{i % 100}", "Position", " ".join(t)) for i, t in enumerate(texts)]
    dataset = bill(boq_profile, lines)
    started = time.perf_counter()
    run(BoqTyposDetector, dataset, boq_profile)
    assert time.perf_counter() - started < 10.0
