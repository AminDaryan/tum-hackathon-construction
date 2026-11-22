"""Robust statistics for the comparison checks.

Floats live only inside these statistics: a scale or a z-score decides whether a value is
compared further, and everything shown to people (prices, quantities, medians) comes from the
exact ``Decimal`` values (:func:`exact_median`). Inputs must be finite; a NaN or an infinity is
a programming error and raises :class:`ValueError` instead of spreading silently.

* :func:`robust_scale`: the median absolute deviation (MAD) scaled to estimate a standard
  deviation, with the mean absolute deviation as the fallback when more than half the values
  equal the median (the scale of the modified z-score of Iglewicz and Hoaglin, 1993).
* :func:`modified_z`: how many robust scales a value lies from the median of the *other*
  members of its group (leave one out, so a single wrong value cannot hide by moving the
  median and widening the scale it is measured with).
* :func:`power_of_ten` and :func:`is_adjacent_digit_swap`: the two typing slips that explain a
  deviating number by themselves (a misplaced decimal point or unit, two swapped digits).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

import numpy as np

from app.validation.contracts.decimal_math import exact_context

# 1 / Φ⁻¹(3/4): MAD × 1.4826 estimates the standard deviation of normally distributed data.
MAD_SCALE = 1.4826
# √(π / 2): the mean absolute deviation × 1.2533 estimates it when the MAD is 0.
MEAN_ABSOLUTE_DEVIATION_SCALE = 1.2533
# k of the factors 10^k that power_of_ten recognizes, nearest first.
_POWERS = (1, -1, 2, -2, 3, -3)


def _finite_array(values: Sequence[float]) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if not np.all(np.isfinite(array)):
        raise ValueError("robust statistics need finite values")
    return array


def robust_scale(values: Sequence[float]) -> float | None:
    """1.4826 × the median absolute deviation from the median; 1.2533 × the mean absolute
    deviation from the median when that is 0 (more than half the values are equal); ``None``
    for a constant group, a single value or no values (no spread to measure)."""
    array = _finite_array(values)
    if array.size == 0:
        return None
    deviations = np.abs(array - np.median(array))
    mad = float(np.median(deviations))
    if mad > 0:
        return MAD_SCALE * mad
    mean_deviation = float(np.mean(deviations))
    if mean_deviation > 0:
        return MEAN_ABSOLUTE_DEVIATION_SCALE * mean_deviation
    return None


def modified_z(value: float, others: Sequence[float]) -> float | None:
    """``(value - median(others)) / robust_scale(others)``: the distance of ``value`` from the
    other members of its group, in robust scales, signed (positive = above them). ``others``
    must not contain ``value``'s own entry. ``None`` when the others have no spread (fewer than
    two values, or all equal)."""
    if not math.isfinite(value):
        raise ValueError("robust statistics need finite values")
    array = _finite_array(others)
    scale = robust_scale(others)
    if scale is None:
        return None
    return (value - float(np.median(array))) / scale


def exact_median(decimals: Sequence[Decimal]) -> Decimal | None:
    """The exact median of decimal values (the mean of the two middle values for an even
    count), for display; ``None`` for no values. Raises :class:`ArithmeticError` rather than
    round (values read from documents always fit the exact 100-digit context)."""
    if not decimals:
        return None
    if not all(value.is_finite() for value in decimals):
        raise ValueError("exact_median needs finite values")
    ordered = sorted(decimals)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    with exact_context():
        return (ordered[middle - 1] + ordered[middle]) / 2


def power_of_ten(ratio: float, tolerance: float = 0.05) -> int | None:
    """``k`` in ±1, ±2, ±3 when ``ratio`` lies within ``tolerance`` (relative) of ``10**k``:
    the factor a misplaced decimal point or a unit slip (cm written as m) leaves behind.
    ``None`` otherwise, also for ratios that are not positive."""
    if not 0 <= tolerance < 0.5:
        raise ValueError(f"tolerance must be in [0, 0.5), got {tolerance}")
    if not math.isfinite(ratio):
        raise ValueError("power_of_ten needs a finite ratio")
    if ratio <= 0:
        return None
    for k in _POWERS:
        factor = 10.0**k
        if abs(ratio - factor) <= tolerance * factor:
            return k
    return None


def is_adjacent_digit_swap(a: Decimal, b: Decimal) -> bool:
    """Whether ``b`` is ``a`` with two neighbouring, different digits swapped (45.80 and 54.80;
    45.80 and 48.50). Both are written with the same number of decimal places (the larger of
    the two) and compared digit by digit, sign and decimal point aside; values of different
    signs, different lengths or with any other difference are not swaps."""
    if not (a.is_finite() and b.is_finite()):
        raise ValueError("is_adjacent_digit_swap needs finite values")
    if a.is_signed() != b.is_signed() or a.is_zero() or b.is_zero():
        return False
    places = max(0, -_exponent(a), -_exponent(b))
    first, second = _digits(a, places), _digits(b, places)
    if len(first) != len(second):
        return False
    different = [index for index, (x, y) in enumerate(zip(first, second, strict=True)) if x != y]
    if len(different) != 2 or different[1] != different[0] + 1:
        return False
    i, j = different
    return first[i] == second[j] and first[j] == second[i]


def _exponent(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):  # pragma: no cover - finite values have int exponents
        raise ValueError("finite decimal expected")
    return exponent


def _digits(value: Decimal, places: int) -> str:
    """The digits of ``|value|`` written in fixed point with ``places`` decimals."""
    return format(abs(value), f".{places}f").replace(".", "")
