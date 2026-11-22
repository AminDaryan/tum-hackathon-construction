"""Formula-injection protection: hostile texts are prefixed, numbers and plain text are not."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.exporters.safety import (
    clean_text,
    csv_value,
    is_plain_number,
    needs_formula_prefix,
    neutralize_formula,
)
from tests.unit.exporters.samples import HOSTILE_TEXTS

MORE_HOSTILE = (
    "=cmd|' /C calc'!A0",
    "@SUM(1)",
    "-",
    "+",
    "\t",  # a tab alone
    "\rabc",  # carriage return before harmless text
    "\n=1+1",  # a line break before the formula
    " =1+1",  # no-break space
    "　@x",  # ideographic space
    "​=1+1",  # zero-width space (format character)
    "﻿+1",  # byte-order mark
    "\x00=1+1",  # NUL before the formula
    "＝1+1",  # full-width equals sign
    "＋SUM(A1)",
    "－2",
    "＠cmd",
)
BENIGN = (
    "",
    " ",
    "Aushub BK 3",
    "a=b",
    "x-1",
    "12.50",
    "1E+3",
    '"=1+1"',  # starts with a quote character
    "'=1+1",  # already quoted
    "m²",
    "Übertrag 1.234,50 €",
    "数量",
)


@pytest.mark.parametrize("text", HOSTILE_TEXTS + MORE_HOSTILE)
def test_hostile_texts_get_one_quote_in_front(text: str) -> None:
    assert needs_formula_prefix(text)
    assert neutralize_formula(text) == "'" + text


@pytest.mark.parametrize("text", BENIGN)
def test_other_texts_are_unchanged(text: str) -> None:
    assert not needs_formula_prefix(text)
    assert neutralize_formula(text) is text


def test_neutralizing_twice_does_not_add_a_second_quote() -> None:
    once = neutralize_formula("=1+1")
    assert neutralize_formula(once) == once


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("-12.50"), "-12.50"),
        (Decimal("12.50"), "12.50"),
        (Decimal("1E+3"), "1000"),
        (Decimal("1.0E-7"), "0.00000010"),
        (Decimal("-0"), "-0"),
        (Decimal("1E+24"), "1000000000000000000000000"),
        (7, "7"),
        (-3, "-3"),
    ],
)
def test_numbers_are_plain_and_never_prefixed(value: Decimal | int, expected: str) -> None:
    assert csv_value(value, is_number=True) == expected


@pytest.mark.parametrize("text", ["-12.50", "0", "-0.001", "123456789"])
def test_number_text_that_is_a_plain_literal_is_written_as_it_is(text: str) -> None:
    assert is_plain_number(text)
    assert csv_value(text, is_number=True) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("-2+3", "'-2+3"),  # the number flag never lets a formula through
        ("=1+1", "'=1+1"),
        ("-12,50 €", "'-12,50 €"),
        ("-1.234,50", "'-1.234,50"),
        ("1,234.50", "1,234.50"),
        (" -1", "' -1"),
        ("1E-05", "1E-05"),
        ("+5", "'+5"),
    ],
)
def test_number_text_that_is_not_a_plain_literal_is_handled_as_text(
    text: str, expected: str
) -> None:
    assert not is_plain_number(text)
    assert csv_value(text, is_number=True) == expected


def test_text_always_goes_through_the_neutralizer() -> None:
    assert csv_value("-12.50", is_number=False) == "'-12.50"
    for text in HOSTILE_TEXTS:
        assert csv_value(text, is_number=False) == "'" + text


def test_none_is_an_empty_cell() -> None:
    assert csv_value(None, is_number=False) == ""
    assert csv_value(None, is_number=True) == ""


def test_nul_and_unpaired_surrogates_are_replaced() -> None:
    assert clean_text("a\x00b\ud800c") == "a�b�c"
    written = csv_value("Nul\x00Zeichen", is_number=False)
    assert written == "Nul�Zeichen"
    assert "\x00" not in csv_value("\x00=1+1", is_number=False)
    assert "\x00" not in csv_value("\x00=1+1", is_number=True)
    written.encode("utf-8")  # always encodable


def test_quotes_commas_line_breaks_and_unicode_are_kept() -> None:
    text = 'Aushub "BK 3", tief\nZeile 2 – m²'
    assert csv_value(text, is_number=False) == text


def test_misuse_is_refused() -> None:
    with pytest.raises(TypeError):
        csv_value(Decimal("1"), is_number=False)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        csv_value(True, is_number=True)
    with pytest.raises(ValueError, match="non-finite"):
        csv_value(Decimal("NaN"), is_number=True)
    with pytest.raises(ValueError, match="non-finite"):
        csv_value(Decimal("-Infinity"), is_number=True)
