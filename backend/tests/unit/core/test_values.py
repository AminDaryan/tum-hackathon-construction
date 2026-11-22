"""Bounds of document numbers (``BoundedDecimal`` through ``NumberValue``), the agreement of
``is_bounded_decimal`` with the validator, exact decimals for computed amounts
(``ExactDecimal``) and ``value_to_display`` for percent and currency values.

Bounds: at most 28 significant digits (trailing and leading zeros do not count), the most
significant digit at most 1E+24 and the least significant digit at least 1E-20.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models.values import (
    MAX_ADJUSTED_EXPONENT,
    MAX_SIGNIFICANT_DIGITS,
    MIN_ADJUSTED_EXPONENT,
    ExactDecimal,
    NumberValue,
    is_bounded_decimal,
    significant_digits,
    value_to_display,
)

D = Decimal
DIGITS_28 = "1234567890.123456789012345678"  # 10 + 18 significant digits
DIGITS_29 = "1234567890.1234567890123456789"

ACCEPTED = [
    D(DIGITS_28),
    D("-" + DIGITS_28),
    D("12345678.12345678901234567890"),  # 28 digits ending exactly at 1E-20
    D("9999999999999999999999999.999"),  # 28 digits starting exactly at 1E+24
    D("9.999999999999999999999999999E+24"),
    D("1E+24"),  # largest accepted adjusted exponent
    D("-1E+24"),
    D("1" + "0" * 24),  # the same value written out: trailing zeros do not count
    D("100E+22"),
    D("1E-20"),  # smallest accepted digit
    D("0.00000000000000000001"),  # leading zeros do not count either
    D("1." + "0" * 40),  # a 1 followed by a decimal point and 40 zeros
    D("0" * 40 + "1"),
    D("0"),
    D("-0"),  # negative zero
    D("0.00"),
    D("0E-20"),
    D("0E+24"),
]

REJECTED = [
    D("1." + "0" * 57 + "1"),  # 59 significant digits: the old normalize() bug
    D(3.7),  # a binary float converted to Decimal: 51 significant digits
    D(0.1),
    D(DIGITS_29),
    D("-" + DIGITS_29),
    D("1E+999999"),
    D("1E+25"),  # one past the largest adjusted exponent
    D("-1E+25"),
    D("1" + "0" * 25),
    D("1E-21"),  # one past the smallest digit
    D("1.5E-20"),  # its last digit sits at 1E-21
    D("0.000000000000000000015"),
    D("12345678.123456789012345678901"),  # 29 digits, last at 1E-21
    D("NaN"),
    D("sNaN"),
    D("Infinity"),
    D("-Infinity"),
]


def _accepted(value: object) -> bool:
    try:
        NumberValue(value=value)
    except ValidationError:
        return False
    return True


class TestBoundedDecimal:
    def test_bound_constants(self) -> None:
        assert (MAX_SIGNIFICANT_DIGITS, MAX_ADJUSTED_EXPONENT, MIN_ADJUSTED_EXPONENT) == (
            28,
            24,
            -20,
        )

    @pytest.mark.parametrize("value", ACCEPTED, ids=str)
    def test_accepted(self, value: Decimal) -> None:
        number = NumberValue(value=value)
        assert number.value == value
        assert str(number.value) == str(value)  # kept as written, never normalized or rounded

    @pytest.mark.parametrize("value", REJECTED, ids=lambda v: str(v)[:40])
    def test_rejected(self, value: Decimal) -> None:
        with pytest.raises(ValidationError):
            NumberValue(value=value)

    @pytest.mark.parametrize("value", ACCEPTED + REJECTED, ids=lambda v: str(v)[:40])
    def test_is_bounded_decimal_agrees_with_the_validator(self, value: Decimal) -> None:
        assert is_bounded_decimal(value) is _accepted(value)

    def test_negative_zero_keeps_its_sign(self) -> None:
        assert NumberValue(value=D("-0")).value.is_signed()

    @pytest.mark.parametrize("value", [3.7, 0.5, 1e300, float("nan"), float("inf")])
    def test_python_floats_are_rejected(self, value: float) -> None:
        with pytest.raises(ValidationError, match="floats are not accepted"):
            NumberValue(value=value)  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [True, False])
    def test_booleans_are_rejected(self, value: bool) -> None:
        with pytest.raises(ValidationError, match="booleans are not numbers"):
            NumberValue(value=value)  # type: ignore[arg-type]

    def test_json_strings_round_trip_at_the_bounds(self) -> None:
        for value in (D(DIGITS_28), D("1E+24"), D("1E-20"), D("-0")):
            number = NumberValue(value=value)
            restored = NumberValue.model_validate(number.model_dump(mode="json"))
            assert str(restored.value) == str(value)

    @pytest.mark.parametrize(
        ("value", "count", "last_exponent"),
        [
            (D("1." + "0" * 57 + "1"), 59, -58),
            (D("1." + "0" * 40), 1, 0),
            (D("1200"), 2, 2),
            (D("0.00120"), 2, -4),
            (D(DIGITS_28), 28, -18),
        ],
    )
    def test_significant_digits_are_counted_without_context_rounding(
        self, value, count, last_exponent
    ) -> None:
        assert significant_digits(value) == (count, last_exponent)

    # A zero with an extreme exponent would otherwise pass and value_to_display would render
    # 0E-999999 as a 1,000,001-character string.
    @pytest.mark.parametrize("text", ["0E-999999", "-0E-999999", "0E+999999"])
    def test_zeros_with_extreme_exponents_are_rejected(self, text: str) -> None:
        assert not is_bounded_decimal(D(text))
        with pytest.raises(ValidationError):
            NumberValue(value=D(text))


class TestExactDecimal:
    adapter = TypeAdapter(ExactDecimal)

    @pytest.mark.parametrize(
        "value",
        [
            D("NaN"),
            D("sNaN"),
            D("Infinity"),
            D("-Infinity"),
            "NaN",
            "Infinity",
            "-inf",
            True,
            False,
            1.0,
            "twelve",
        ],
        ids=repr,
    )
    def test_rejects_non_finite_values_booleans_floats_and_text(self, value) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python(value)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("12.50", D("12.50")), (" 3 ", D(3)), (7, D(7)), (D("-0.00"), D("-0.00"))],
    )
    def test_accepts_exact_input(self, value, expected) -> None:
        result = self.adapter.validate_python(value)
        assert result == expected and str(result) == str(expected)

    def test_computed_amounts_are_not_bounded_like_document_numbers(self) -> None:
        # Sums and products of document values may exceed 28 digits; only finiteness applies.
        assert self.adapter.validate_python(D(DIGITS_29) * D(DIGITS_29)) == D(DIGITS_29) ** 2


class TestDisplay:
    @pytest.mark.parametrize(
        ("number", "text"),
        [
            (NumberValue(value=D("0.155"), is_percent=True), "15.5 %"),
            (NumberValue(value=D("1"), is_percent=True), "100 %"),  # not "1E+2 %"
            (NumberValue(value=D("0.5"), is_percent=True), "50 %"),
            (NumberValue(value=D("-0.07"), is_percent=True), "-7 %"),
            (NumberValue(value=D("0.1900"), is_percent=True), "19 %"),
            (NumberValue(value=D("1E-20"), is_percent=True), "0.000000000000000001 %"),
            (NumberValue(value=D(DIGITS_28), is_percent=True), "123456789012.3456789012345678 %"),
            (NumberValue(value=D("0.5"), is_percent=True, currency="EUR"), "50 % EUR"),
            (NumberValue(value=D("1234.50"), currency="EUR"), "1234.50 EUR"),
            (NumberValue(value=D("1.2E+3"), currency="USD"), "1200 USD"),
            (NumberValue(value=D("-0.01"), currency="CHF"), "-0.01 CHF"),
            (NumberValue(value=D("1E+24"), currency="EUR"), "1" + "0" * 24 + " EUR"),
            (NumberValue(value=D("1E-20")), "0.00000000000000000001"),
            (NumberValue(value=D("-0")), "-0"),
        ],
        ids=lambda v: v if isinstance(v, str) else None,
    )
    def test_percent_and_currency_values(self, number: NumberValue, text: str) -> None:
        assert value_to_display(number) == text

    @pytest.mark.parametrize("value", ACCEPTED, ids=str)
    def test_display_of_accepted_values_is_short_and_plain(self, value: Decimal) -> None:
        text = value_to_display(NumberValue(value=value))
        assert "E" not in text
        assert len(text) <= 48  # no exponent expansion: at most what the source wrote
