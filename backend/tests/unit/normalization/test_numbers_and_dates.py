"""Number and date parsing: pure functions, German and English formats, no float."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.values import DateTimeValue, DateValue, ParseStatus
from app.normalization.dates import AmbiguousDate, DateReading, parse_date
from app.normalization.numbers import (
    AmbiguousNumber,
    NumberReading,
    OutOfRange,
    ParenthesizedNumber,
    parse_number,
)
from app.profiles.currency import CurrencyResolver

CURRENCIES = CurrencyResolver()


def read(text: str, parentheses: str = "negative") -> object:
    return parse_number(text, currencies=CURRENCIES, parentheses=parentheses)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "value", "evidence"),
    [
        ("1234", "1234", None),
        ("0012", "12", None),
        ("1.234,50", "1234.50", ","),
        ("1,234.50", "1234.50", "."),
        ("1.234.567", "1234567", ","),
        ("1,234,567", "1234567", "."),
        ("1 234,56", "1234.56", ","),
        ("1 234,56", "1234.56", ","),
        ("1'234.50", "1234.50", "."),
        ("12,5", "12.5", ","),
        ("1234.5", "1234.5", "."),
        ("0,125", "0.125", ","),
        ("-5", "-5", None),
        ("−5", "-5", None),
        ("+7,25", "7.25", ","),
        ("1234,50-", "-1234.50", ","),
        ("(1.234,50)", "-1234.50", ","),
        ("  42  ", "42", None),
    ],
)
def test_unambiguous_numbers(text: str, value: str, evidence: str | None) -> None:
    reading = read(text)
    assert isinstance(reading, NumberReading)
    assert reading.value == Decimal(value)
    assert str(reading.value) == value  # exact digits, never a float round trip
    assert reading.decimal_evidence == evidence
    assert reading.currency is None
    assert not reading.is_percent


@pytest.mark.parametrize(
    ("text", "value", "currency"),
    [
        ("€ 1.234,50", "1234.50", "EUR"),
        ("1.234,50 €", "1234.50", "EUR"),
        ("1,234.50 EUR", "1234.50", "EUR"),
        ("CHF 1'250.00", "1250.00", "CHF"),
    ],
)
def test_currency_markers(text: str, value: str, currency: str) -> None:
    reading = read(text)
    assert isinstance(reading, NumberReading)
    assert reading.value == Decimal(value)
    assert reading.currency == currency


def test_percent_is_divided_by_100_and_marked() -> None:
    reading = read("19 %")
    assert isinstance(reading, NumberReading)
    assert reading.value == Decimal("0.19")
    assert reading.is_percent
    german = read("12,5%")
    assert isinstance(german, NumberReading)
    assert german.value == Decimal("0.125")


@pytest.mark.parametrize("text", ["1.234", "1,234", "12.500", "999,000"])
def test_a_single_separator_before_three_digits_is_ambiguous(text: str) -> None:
    reading = read(text)
    assert isinstance(reading, AmbiguousNumber)
    as_point = reading.resolve(".")
    as_comma = reading.resolve(",")
    assert {as_point.value, as_comma.value} == {reading.as_decimal, reading.as_grouping}
    assert reading.as_grouping == Decimal(text.replace(".", "").replace(",", ""))


def test_parentheses_can_be_left_unread() -> None:
    assert isinstance(read("(1.234,00)", parentheses="ambiguous"), ParenthesizedNumber)
    negative = read("(1.234,00)")
    assert isinstance(negative, NumberReading)
    assert negative.value == Decimal("-1234.00")


def test_values_outside_the_supported_range() -> None:
    assert isinstance(read("1e30"), OutOfRange)
    assert isinstance(read("12345678901234567890123456789"), OutOfRange)  # 29 digits


@pytest.mark.parametrize(
    "text",
    [
        "approx. 5",
        "5-10",
        "1.2.3",
        "n/a",
        "incl.",
        "-",
        "",
        "   ",
        "1" * 31,
        "abc 5",
        "1.23.456",
        "12,34,56",
        "nan",
        "inf",
    ],
)
def test_not_numbers(text: str) -> None:
    assert read(text) is None


def test_iso_dates_are_exact() -> None:
    reading = parse_date("2026-03-04", "auto")
    assert isinstance(reading, DateReading)
    assert reading.value == DateValue(value=date(2026, 3, 4))
    assert reading.status is ParseStatus.EXACT
    timed = parse_date("2026-03-04T10:30:00", "auto")
    assert isinstance(timed, DateReading)
    assert timed.value == DateTimeValue(value=datetime(2026, 3, 4, 10, 30))


def test_day_month_order_from_the_profile_is_inferred() -> None:
    german = parse_date("04.03.2026", "DMY")
    assert isinstance(german, DateReading)
    assert german.value == DateValue(value=date(2026, 3, 4))
    assert german.status is ParseStatus.INFERRED
    assert german.note
    american = parse_date("03/04/2026", "MDY")
    assert isinstance(american, DateReading)
    assert american.value == DateValue(value=date(2026, 3, 4))


def test_auto_order_only_when_the_text_decides_it() -> None:
    decided = parse_date("13.03.2026", "auto")
    assert isinstance(decided, DateReading)
    assert decided.value == DateValue(value=date(2026, 3, 13))
    assert decided.status is ParseStatus.EXACT
    assert isinstance(parse_date("04.03.2026", "auto"), AmbiguousDate)


@pytest.mark.parametrize("text", ["31.02.2026", "2026-13-01", "Mai 2026", "4.3."])
def test_not_dates(text: str) -> None:
    assert parse_date(text, "DMY") is None


def test_the_cell_parser_marker_table_agrees_with_the_profile(boq_profile) -> None:
    from app.models.profile import FieldRole
    from app.normalization.cells import CellParser
    from app.profiles.units import UnitCatalog

    parser = CellParser(boq_profile, UnitCatalog.from_profile(boq_profile), CURRENCIES, {})
    texts = [t for rule in boq_profile.value_markers for t in rule.tokens]
    texts += [" Incl. ", "NUR EP", "12,5", "", "x" * 41, "entfällt ", "psch", "Pauschal"]
    for role in FieldRole:
        for text in texts:
            assert parser.marker(text, role) == boq_profile.match_marker(text, role), (text, role)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-03-04 10:30", datetime(2026, 3, 4, 10, 30)),
        ("2026-03-04T10:30:15", datetime(2026, 3, 4, 10, 30, 15)),
    ],
)
def test_iso_datetimes_read_optional_seconds(text: str, expected: datetime) -> None:
    reading = parse_date(text, "auto")
    assert isinstance(reading, DateReading)
    assert reading.value == DateTimeValue(value=expected)
    assert reading.status is ParseStatus.EXACT


@pytest.mark.parametrize("text", ["2026-02-30T10:30", "2026-03-04 24:00", "2026-03-04 10:60:00"])
def test_impossible_iso_datetimes_are_not_dates(text: str) -> None:
    assert parse_date(text, "auto") is None


def test_a_draft_hands_out_its_reading_only_as_the_type_its_kind_holds() -> None:
    from app.normalization.cells import Draft

    number = NumberReading(Decimal("12.5"), decimal_evidence=",")
    assert Draft("number", number).reading_as(NumberReading) is number
    with pytest.raises(TypeError, match="'number' draft holds NoneType"):
        Draft("number").reading_as(NumberReading)
    with pytest.raises(TypeError, match="'date' draft holds NumberReading"):
        Draft("date", number).reading_as(DateReading)
