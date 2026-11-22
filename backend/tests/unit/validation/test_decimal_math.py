"""Exact arithmetic, rounding and tolerance policy shared by all reconciliation detectors."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.validation.contracts.decimal_math import (
    RoundingMode,
    RoundingSpec,
    TolerancePolicy,
    add_all,
    format_decimal,
    multiply,
    power_of_ten_factor,
    reconcile,
    subtract,
)

D = Decimal


def test_multiplication_is_exact_beyond_default_precision() -> None:
    # 28 significant digits (Python's default context) would round this product.
    a = D("123456789012345.6789")
    b = D("98765432109876.54321")
    exact = D(f"{1234567890123456789 * 9876543210987654321}E-9")  # exact: integer math
    assert a * b != exact  # the default 28-digit context really does round here
    assert multiply(a, b) == exact


def test_sum_of_many_cents_has_no_drift() -> None:
    assert add_all([D("0.10")] * 1000) == D("100.00")


def test_float_noise_never_appears() -> None:
    assert add_all([D("0.1"), D("0.2")]) == D("0.3")


@pytest.mark.parametrize(
    ("mode", "value", "expected"),
    [
        (RoundingMode.HALF_UP, "2.675", "2.68"),
        (RoundingMode.HALF_EVEN, "2.665", "2.66"),
        (RoundingMode.HALF_UP, "-2.675", "-2.68"),
        (RoundingMode.DOWN, "2.679", "2.67"),
        (RoundingMode.UP, "2.671", "2.68"),
    ],
)
def test_rounding_modes(mode: RoundingMode, value: str, expected: str) -> None:
    assert RoundingSpec(decimal_places=2, mode=mode).apply(D(value)) == D(expected)


def test_no_rounding_keeps_exact_value() -> None:
    assert RoundingSpec(decimal_places=None).apply(D("1.23456")) == D("1.23456")


class TestTolerance:
    def test_absolute(self) -> None:
        tol = TolerancePolicy(absolute=D("0.01"))
        assert tol.within(D("100.01"), D("100.00"))
        assert not tol.within(D("100.02"), D("100.00"))

    def test_relative_wins_when_larger(self) -> None:
        tol = TolerancePolicy(absolute=D("0.01"), relative=D("0.001"))
        assert tol.allowed_difference(D("10000")) == D("10.000")
        assert tol.within(D("10009.99"), D("10000"))

    def test_per_term_absorbs_rounding_drift(self) -> None:
        tol = TolerancePolicy(absolute=D("0.01"), per_term_absolute=D("0.005"))
        assert tol.allowed_difference(D("500"), terms=10) == D("0.060")

    def test_negative_tolerances_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TolerancePolicy(absolute=D("-1"))

    def test_symmetric(self) -> None:
        tol = TolerancePolicy(absolute=D("0.5"))
        assert tol.within(D("9.5"), D("10")) and tol.within(D("10.5"), D("10"))


class TestPowerOfTen:
    @pytest.mark.parametrize(
        ("observed", "expected", "factor"),
        [("5000", "500", 1), ("50", "500", -1), ("125000", "125", 3), ("1.25", "125", -2)],
    )
    def test_detects_scaling(self, observed: str, expected: str, factor: int) -> None:
        assert power_of_ten_factor(D(observed), D(expected)) == factor

    def test_ignores_unrelated_values(self) -> None:
        assert power_of_ten_factor(D("512"), D("500")) is None

    def test_zero_never_matches(self) -> None:
        assert power_of_ten_factor(D("0"), D("500")) is None

    @pytest.mark.parametrize(
        ("observed", "expected"),
        [("0.01", "500"), ("0.009", "3"), ("0.01", "0.5"), ("1040", "105")],
    )
    def test_no_spurious_matches_for_tiny_or_loose_ratios(
        self, observed: str, expected: str
    ) -> None:
        assert power_of_ten_factor(D(observed), D(expected)) is None


class TestReconcile:
    tol = TolerancePolicy(absolute=D("0"))
    rounding = RoundingSpec(decimal_places=2)

    def test_rounded_reporting_matches(self) -> None:
        result = reconcile(D("4.67"), D("4.666"), rounding=self.rounding, tolerance=self.tol)
        assert result.matched and result.convention == "rounded"

    def test_unrounded_reporting_matches(self) -> None:
        result = reconcile(D("4.9995"), D("4.9995"), rounding=self.rounding, tolerance=self.tol)
        assert result.matched and result.convention == "exact"

    def test_mismatch_reports_rounded_expectation(self) -> None:
        result = reconcile(D("5000"), D("500.004"), rounding=self.rounding, tolerance=self.tol)
        assert not result.matched
        assert result.expected == D("500.00")
        assert result.difference == D("4500.00")


def test_exact_operations_raise_instead_of_rounding() -> None:
    big = D("9" * 60)  # the square has 120 digits: more than the 100-digit exact context
    with pytest.raises(ArithmeticError):
        multiply(big, big)


def test_bounded_document_values_stay_exact() -> None:
    # Extremes allowed for document values: 28 digits, from 1E-20 up to 1E+24.
    large = D("9999999999999999999999999")  # 25 digits, most significant digit at 1E+24
    tiny = D("0.00000000000000000001")  # 1E-20
    product = multiply(large, D("1234567890.123456789012345678"))
    difference = subtract(product, tiny)
    assert len(difference.as_tuple().digits) > 50  # far beyond the default 28 digits
    assert add_all([difference, tiny]) == product
    assert add_all([large, tiny, large]) == D("19999999999999999999999998.00000000000000000001")


def test_tolerances_reject_floats() -> None:
    with pytest.raises(ValidationError):
        TolerancePolicy(absolute=0.01)  # type: ignore[arg-type]
    assert TolerancePolicy(absolute="0.01").absolute == D("0.01")


def test_format_decimal_is_plain() -> None:
    assert format_decimal(D("1E+3")) == "1000"
    assert format_decimal(D("0.00001")) == "0.00001"
