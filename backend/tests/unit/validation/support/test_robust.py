"""Robust statistics: hand-computed cases, edge cases and properties over seeded random data
(no extra test dependency: each property is checked on a few hundred generated cases)."""

from __future__ import annotations

import math
import random
from decimal import Decimal

import pytest

from app.validation.support.robust import (
    MAD_SCALE,
    MEAN_ABSOLUTE_DEVIATION_SCALE,
    exact_median,
    is_adjacent_digit_swap,
    modified_z,
    power_of_ten,
    robust_scale,
)

D = Decimal


def _samples(seed: int, count: int = 200) -> list[list[float]]:
    rng = random.Random(seed)
    return [
        [rng.choice((rng.uniform(-50, 50), float(rng.randint(-5, 5)))) for _ in range(size)]
        for size in (rng.randint(2, 12) for _ in range(count))
    ]


class TestRobustScale:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            # median 3, deviations 2 1 0 1 97: MAD 1
            ([1, 2, 3, 4, 100], MAD_SCALE * 1),
            # median 2, deviations 1 1: MAD 1
            ([1, 3], MAD_SCALE * 1),
            # median -2, deviations 1 0 1: MAD 1
            ([-1, -2, -3], MAD_SCALE * 1),
            # median 2.5, deviations 1.5 0.5 0.5 1.5: MAD (0.5 + 1.5) / 2 = 1
            ([1, 2, 3, 4], MAD_SCALE * 1),
            # median 5, deviations 0 0 0 4: MAD 0, mean deviation 1
            ([5, 5, 5, 9], MEAN_ABSOLUTE_DEVIATION_SCALE * 1),
            # median 0, deviations 0 0 1: MAD 0, mean deviation 1/3
            ([0, 0, 1], MEAN_ABSOLUTE_DEVIATION_SCALE / 3),
            # median 10, deviations 0 0 20 20 0: MAD 0, mean deviation 8
            ([10, 10, -10, 30, 10], MEAN_ABSOLUTE_DEVIATION_SCALE * 8),
        ],
    )
    def test_hand_computed(self, values: list[float], expected: float) -> None:
        assert robust_scale(values) == pytest.approx(expected, rel=1e-12)

    @pytest.mark.parametrize("values", [[], [7.0], [3.0, 3.0, 3.0], [0.0, 0.0], [-2.5] * 9])
    def test_no_spread_has_no_scale(self, values: list[float]) -> None:
        assert robust_scale(values) is None

    def test_the_constants(self) -> None:
        assert MAD_SCALE == 1.4826
        assert MEAN_ABSOLUTE_DEVIATION_SCALE == 1.2533
        assert pytest.approx(math.sqrt(math.pi / 2), abs=1e-4) == MEAN_ABSOLUTE_DEVIATION_SCALE

    def test_one_outlier_does_not_move_the_scale(self) -> None:
        assert robust_scale([10, 11, 12, 13, 14]) == robust_scale([10, 11, 12, 13, 1e9])

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_non_finite_values_are_refused(self, bad: float) -> None:
        with pytest.raises(ValueError, match="finite"):
            robust_scale([1.0, bad])

    def test_properties(self) -> None:
        rng = random.Random(1)
        for values in _samples(20261120):
            scale = robust_scale(values)
            shuffled = values[:]
            rng.shuffle(shuffled)
            assert robust_scale(shuffled) == scale  # order does not matter
            shift, factor = rng.uniform(-100, 100), rng.choice((-3.0, 0.5, 2.0, 7.0))
            moved = robust_scale([v + shift for v in values])
            stretched = robust_scale([v * factor for v in values])
            if scale is None:
                assert len(set(values)) == 1
                assert moved is None and stretched is None
                continue
            assert scale > 0
            assert moved == pytest.approx(scale, rel=1e-9, abs=1e-9)  # translation invariant
            assert stretched == pytest.approx(abs(factor) * scale, rel=1e-9)  # scale equivariant


class TestModifiedZ:
    def test_hand_computed(self) -> None:
        # others: median 3, MAD 1 -> scale 1.4826; (10 - 3) / 1.4826
        assert modified_z(10, [1, 2, 3, 4, 5]) == pytest.approx(7 / 1.4826, rel=1e-12)
        assert modified_z(-10, [-1, -2, -3, -4, -5]) == pytest.approx(-7 / 1.4826, rel=1e-12)
        assert modified_z(3, [1, 2, 3, 4, 5]) == 0
        # others: median 5, MAD 0, mean deviation 1 -> scale 1.2533
        assert modified_z(0, [5, 5, 5, 9]) == pytest.approx(-5 / 1.2533, rel=1e-12)

    def test_leave_one_out(self) -> None:
        # With the value among its own peers it would widen the scale it is measured with:
        # only the others count.
        others = [100.0, 101.0, 99.0, 100.0]
        assert modified_z(1000.0, others) == pytest.approx(900 / (1.4826 * 0.5), rel=1e-12)
        assert modified_z(1000.0, others) != modified_z(1000.0, [*others, 1000.0])

    @pytest.mark.parametrize("others", [[], [5.0], [4.0, 4.0, 4.0]])
    def test_no_spread_among_the_others(self, others: list[float]) -> None:
        assert modified_z(9.0, others) is None

    @pytest.mark.parametrize(("value", "others"), [(math.nan, [1.0, 2.0]), (1.0, [math.inf, 2.0])])
    def test_non_finite_values_are_refused(self, value: float, others: list[float]) -> None:
        with pytest.raises(ValueError, match="finite"):
            modified_z(value, others)

    def test_properties(self) -> None:
        rng = random.Random(2)
        for others in _samples(7):
            value = rng.uniform(-200, 200)
            z = modified_z(value, others)
            if z is None:
                assert robust_scale(others) is None
                continue
            assert modified_z(-value, [-v for v in others]) == pytest.approx(-z, abs=1e-9)
            shift = rng.uniform(-50, 50)
            assert modified_z(value + shift, [v + shift for v in others]) == pytest.approx(
                z, rel=1e-9, abs=1e-9
            )
            assert modified_z(value * 4, [v * 4 for v in others]) == pytest.approx(
                z, rel=1e-9, abs=1e-9
            )


class TestExactMedian:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            ([], None),
            ([D("2.5")], D("2.5")),
            ([D("3"), D("1"), D("2")], D("2")),
            ([D("1"), D("3")], D("2")),
            ([D("45.80"), D("54.80")], D("50.30")),
            ([D("0.01"), D("0.02")], D("0.015")),
            ([D("-1"), D("-3")], D("-2")),
            ([D("-1.5"), D("0"), D("1.5"), D("9")], D("0.75")),
            ([D("0"), D("0")], D("0")),
            ([D("1E+20"), D("1E-20")], D("50000000000000000000.000000000000000000005")),
        ],
    )
    def test_hand_computed(self, values: list[Decimal], expected: Decimal | None) -> None:
        assert exact_median(values) == expected

    def test_the_result_keeps_the_written_places(self) -> None:
        assert str(exact_median([D("45.80"), D("54.80")])) == "50.30"
        assert str(exact_median([D("12.50"), D("7.25"), D("9.00")])) == "9.00"

    def test_non_finite_values_are_refused(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            exact_median([D("1"), D("NaN")])

    def test_properties(self) -> None:
        rng = random.Random(3)
        for _ in range(300):
            values = [D(rng.randint(-(10**6), 10**6)).scaleb(-2) for _ in range(rng.randint(1, 9))]
            median = exact_median(values)
            assert median is not None
            ordered = sorted(values)
            below = sum(1 for v in values if v < median)
            above = sum(1 for v in values if v > median)
            assert below <= len(values) // 2 and above <= len(values) // 2
            if len(values) % 2 == 0:
                middle = len(values) // 2
                assert median * 2 == ordered[middle - 1] + ordered[middle]  # exact, no rounding
            else:
                assert median in values
            assert exact_median(list(reversed(values))) == median


class TestPowerOfTen:
    @pytest.mark.parametrize(
        ("ratio", "k"),
        [
            (10.0, 1),
            (0.1, -1),
            (100.0, 2),
            (0.01, -2),
            (1000.0, 3),
            (0.001, -3),
            (9.6, 1),
            (10.4, 1),
            (9.5, 1),  # exactly 5 % below
            (10.5, 1),  # exactly 5 % above
            (104.0, 2),
            (0.0951, -1),
            (1040.0, 3),
        ],
    )
    def test_named_factors(self, ratio: float, k: int) -> None:
        assert power_of_ten(ratio) == k

    @pytest.mark.parametrize(
        "ratio", [1.0, 1.04, 5.0, 9.4, 10.6, 50.0, 0.5, 0.0949, 10_000.0, 0.0001, 0.0, -10.0, -0.1]
    )
    def test_other_ratios(self, ratio: float) -> None:
        assert power_of_ten(ratio) is None

    def test_tolerance(self) -> None:
        assert power_of_ten(10.0, tolerance=0) == 1
        assert power_of_ten(10.0001, tolerance=0) is None
        assert power_of_ten(12.0, tolerance=0.25) == 1
        assert power_of_ten(12.0) is None

    @pytest.mark.parametrize("tolerance", [-0.01, 0.5, 2.0])
    def test_invalid_tolerances_are_refused(self, tolerance: float) -> None:
        with pytest.raises(ValueError, match="tolerance"):
            power_of_ten(10.0, tolerance=tolerance)

    @pytest.mark.parametrize("ratio", [math.nan, math.inf])
    def test_non_finite_ratios_are_refused(self, ratio: float) -> None:
        with pytest.raises(ValueError, match="finite"):
            power_of_ten(ratio)

    def test_properties(self) -> None:
        rng = random.Random(4)
        for _ in range(500):
            k = rng.choice((1, -1, 2, -2, 3, -3))
            inside = 10.0**k * (1 + rng.uniform(-0.049, 0.049))
            assert power_of_ten(inside) == k
            # The inverse slip: within 4.5 % of 10^k, the inverse is within 5 % of 10^-k.
            close = 10.0**k * (1 + rng.uniform(-0.045, 0.045))
            assert power_of_ten(1 / close) == -k
            outside = 10.0**k * (1 + rng.choice((-1, 1)) * rng.uniform(0.06, 0.5))
            assert power_of_ten(outside) is None


class TestAdjacentDigitSwap:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("45.80", "54.80"),
            ("45.80", "48.50"),  # the digits around the decimal point
            ("45.80", "45.08"),
            ("45.8", "54.80"),  # written with different places: compared with two
            ("12", "21"),
            ("123", "132"),
            ("-45.80", "-54.80"),
            ("0.45", "0.54"),
            ("0.05", "0.50"),
            ("1090", "1900"),
        ],
    )
    def test_swaps(self, a: str, b: str) -> None:
        assert is_adjacent_digit_swap(D(a), D(b))
        assert is_adjacent_digit_swap(D(b), D(a))

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("45.80", "45.80"),  # identical
            ("11", "11"),
            ("1E+3", "1000"),  # the same value written differently
            ("45.80", "58.40"),  # three digits differ
            ("123", "321"),  # not neighbours
            ("1234", "2143"),  # two swaps
            ("45.80", "45.81"),  # one digit
            ("100", "10"),  # a decimal slip, not a swap
            ("1.05", "10.5"),
            ("-45.80", "54.80"),  # different signs
            ("0", "0"),
            ("0", "10"),
            ("45.80", "4.580"),
        ],
    )
    def test_not_swaps(self, a: str, b: str) -> None:
        assert not is_adjacent_digit_swap(D(a), D(b))
        assert not is_adjacent_digit_swap(D(b), D(a))

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_values_are_refused(self, bad: str) -> None:
        with pytest.raises(ValueError, match="finite"):
            is_adjacent_digit_swap(D("1.00"), D(bad))

    def test_properties(self) -> None:
        rng = random.Random(5)
        for _ in range(500):
            digits = [str(rng.randint(1, 9))] + [str(rng.randint(0, 9)) for _ in range(5)]
            places = rng.randint(0, 3)
            value = D("".join(digits)).scaleb(-places)
            i = rng.randrange(len(digits) - 1)
            swapped = digits[:]
            swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
            other = D("".join(swapped)).scaleb(-places)
            expected = digits[i] != digits[i + 1] and swapped[0] != "0"
            assert is_adjacent_digit_swap(value, other) is expected, (value, other)
            assert is_adjacent_digit_swap(other, value) is expected
            assert not is_adjacent_digit_swap(value, value)
