"""Exact decimal arithmetic and the shared rounding/tolerance policy.

All reconciliation math (quantity × price, subtotals, grand totals) goes through this module so
rounding and tolerance behave identically in every detector. Floating point is never used for
money: values are :class:`~decimal.Decimal`.

Exactness contract: :func:`multiply`, :func:`add_all` and :func:`subtract` either return the
exact result or raise :class:`decimal.Inexact` / :class:`decimal.InvalidOperation` (both are
:class:`ArithmeticError`). Values read from documents are bounded (see
``app.models.values.BoundedDecimal``: at most 28 significant digits between 1E-20 and 1E+24),
so the products, differences and sums of document values that detectors compute fit the
100-digit context exactly. Detectors still guard each row (``_support.row_guard``) so an
unexpected arithmetic error skips that row visibly instead of failing the detector.
"""

from __future__ import annotations

import decimal
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.models.base import FrozenModel
from app.models.values import ExactDecimal

_PRECISION = 100


@contextmanager
def exact_context() -> Iterator[decimal.Context]:
    """100-digit context that raises instead of rounding, overflowing or producing NaN."""
    with decimal.localcontext() as ctx:
        ctx.prec = _PRECISION
        ctx.rounding = decimal.ROUND_HALF_EVEN
        ctx.traps[decimal.InvalidOperation] = True
        ctx.traps[decimal.DivisionByZero] = True
        ctx.traps[decimal.Overflow] = True
        ctx.traps[decimal.Inexact] = True
        yield ctx


@contextmanager
def _rounding_context() -> Iterator[decimal.Context]:
    """Context for deliberate rounding (quantize, tolerances, ratios): no Inexact trap."""
    with decimal.localcontext() as ctx:
        ctx.prec = _PRECISION
        ctx.rounding = decimal.ROUND_HALF_EVEN
        ctx.traps[decimal.InvalidOperation] = True
        ctx.traps[decimal.DivisionByZero] = True
        ctx.traps[decimal.Overflow] = True
        ctx.traps[decimal.Inexact] = False
        yield ctx


def multiply(*factors: Decimal) -> Decimal:
    with exact_context():
        result = Decimal(1)
        for factor in factors:
            result *= factor
        return +result


def add_all(values: Iterable[Decimal]) -> Decimal:
    with exact_context():
        total = Decimal(0)
        for value in values:
            total += value
        return +total


def subtract(a: Decimal, b: Decimal) -> Decimal:
    with exact_context():
        return a - b


class RoundingMode(StrEnum):
    HALF_UP = "half_up"  # commercial rounding (kaufmännisch), the usual BoQ convention
    HALF_EVEN = "half_even"  # banker's rounding
    DOWN = "down"  # truncate toward zero
    UP = "up"  # away from zero


_ROUNDING = {
    RoundingMode.HALF_UP: decimal.ROUND_HALF_UP,
    RoundingMode.HALF_EVEN: decimal.ROUND_HALF_EVEN,
    RoundingMode.DOWN: decimal.ROUND_DOWN,
    RoundingMode.UP: decimal.ROUND_UP,
}


class RoundingSpec(FrozenModel):
    """How a recomputed value is rounded before comparison. ``decimal_places=None`` keeps the
    exact result."""

    decimal_places: int | None = Field(default=2, ge=0, le=10)
    mode: RoundingMode = RoundingMode.HALF_UP

    def apply(self, value: Decimal) -> Decimal:
        if self.decimal_places is None:
            return value
        with _rounding_context():
            return value.quantize(
                Decimal(1).scaleb(-self.decimal_places), rounding=_ROUNDING[self.mode]
            )

    def with_places(self, decimal_places: int | None) -> RoundingSpec:
        return self.evolve(decimal_places=decimal_places)

    def describe(self) -> str:
        if self.decimal_places is None:
            return "exact (no rounding)"
        places = "decimal place" if self.decimal_places == 1 else "decimal places"
        return f"{self.decimal_places} {places}, {self.mode.value.replace('_', ' ')}"


class TolerancePolicy(FrozenModel):
    """Allowed difference between a reported and a recomputed value.

    ``allowed = max(absolute + per_term_absolute × terms, relative × |expected|)``

    ``per_term_absolute`` absorbs rounding drift when summing values that were *displayed*
    rounded while the printed total was computed from unrounded values. It defaults to 0:
    summing reported values exactly has no drift, so a per-term allowance would only hide real
    differences. Detectors apply a drift band only where the source is known to be
    display-rounded (e.g. delimited text exports) and report differences inside it.
    """

    # Bounded as defence in depth (tolerances are profile-controlled, never plannable): no
    # configuration can make a reconciliation accept arbitrary differences.
    absolute: ExactDecimal = Field(default=Decimal("0.01"), ge=0, le=Decimal(1_000_000))
    relative: ExactDecimal = Field(default=Decimal("0"), ge=0, le=Decimal("0.5"))
    per_term_absolute: ExactDecimal = Field(default=Decimal("0"), ge=0, le=1)

    def allowed_difference(self, expected: Decimal, terms: int = 1) -> Decimal:
        with _rounding_context():
            additive = self.absolute + self.per_term_absolute * max(terms, 1)
            proportional = self.relative * abs(expected)
            return max(additive, proportional)

    def difference(self, observed: Decimal, expected: Decimal) -> Decimal:
        return subtract(observed, expected)

    def within(self, observed: Decimal, expected: Decimal, terms: int = 1) -> bool:
        return abs(self.difference(observed, expected)) <= self.allowed_difference(expected, terms)

    def describe(self, expected: Decimal, terms: int = 1) -> str:
        allowed = self.allowed_difference(expected, terms)
        return f"±{format(allowed, 'f')}"


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Outcome of comparing a reported value with a recomputation.

    ``convention`` records which reading matched: the exact result or the result rounded per
    the :class:`RoundingSpec` (documents differ in whether they round before reporting).
    """

    matched: bool
    convention: Literal["exact", "rounded"] | None
    exact: Decimal
    expected: Decimal  # the rounded recomputation (the exact one when rounding is None)
    difference: Decimal  # reported - expected
    allowed: Decimal


def reconcile(
    reported: Decimal,
    exact: Decimal,
    *,
    rounding: RoundingSpec,
    tolerance: TolerancePolicy,
    terms: int = 1,
) -> Reconciliation:
    """A reported value passes when it is within tolerance of the exact *or* the rounded
    recomputation. On a mismatch the rounded recomputation is the expected value."""
    rounded = rounding.apply(exact)
    allowed = tolerance.allowed_difference(rounded, terms)
    candidates: tuple[tuple[Literal["exact", "rounded"], Decimal], ...] = (
        ("rounded", rounded),
        ("exact", exact),
    )
    for convention, candidate in candidates:
        if abs(subtract(reported, candidate)) <= allowed:
            return Reconciliation(
                matched=True,
                convention=convention,
                exact=exact,
                expected=candidate,
                difference=subtract(reported, candidate),
                allowed=allowed,
            )
    return Reconciliation(
        matched=False,
        convention=None,
        exact=exact,
        expected=rounded,
        difference=subtract(reported, rounded),
        allowed=allowed,
    )


_SCALING_RATIO_TOLERANCE = Decimal("0.005")


def power_of_ten_factor(
    observed: Decimal,
    expected_exact: Decimal,
    *,
    quantum: Decimal = Decimal("0.01"),
    max_exponent: int = 6,
) -> int | None:
    """Return ``k`` when ``observed ≈ expected × 10**k`` (k ≠ 0, |k| ≤ max_exponent).

    Ratio-based on purpose: ``|observed / (expected × 10**k) − 1| ≤ 0.5 %``, and the observed
    value must have at least three significant digits above the rounding ``quantum`` so tiny
    values do not "match" by accident. Pass the *exact* recomputation. A match is evidence of a
    decimal-point or scaling error, reported as context, never as proof.
    """
    if observed.is_zero() or expected_exact.is_zero():
        return None
    with _rounding_context():
        if abs(observed) < quantum * 100:
            return None
        for exponent in range(1, max_exponent + 1):
            for k in (exponent, -exponent):
                scaled = expected_exact * Decimal(1).scaleb(k)
                ratio = observed / scaled
                if abs(ratio - 1) <= _SCALING_RATIO_TOLERANCE:
                    return k
    return None


def format_decimal(value: Decimal) -> str:
    """Plain (non-scientific) string for a Decimal, e.g. ``Decimal('1E+3')`` -> ``'1000'``.
    Zeros are written without a sign (``-0.00`` -> ``'0.00'``): a reviewer should never read
    "expected -0.00"."""
    if value.is_zero():
        value = value.copy_abs()
    return format(value, "f")


def format_amount(value: Decimal) -> str:
    """An amount of money for a sentence: at least two decimal places and no trailing zeros
    beyond them, never rounded: ``2000.0`` -> ``'2000.00'``, ``1800`` -> ``'1800.00'``,
    ``13.4750`` -> ``'13.475'``."""
    whole, _, fraction = format_decimal(value).partition(".")
    return f"{whole}.{(fraction[:2] + fraction[2:].rstrip('0')).ljust(2, '0')}"
