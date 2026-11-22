"""Shared deterministic-detector helpers (``app.validation.deterministic._support``) and the
code canonicalization they re-export from ``app.core.codes``: edge cases beyond
``tests/unit/core/test_codes.py`` (Unicode digit systems, segment bounds before zero
stripping, segment-wise prefixes), ``row_guard``, ``fmt``, ``row_label``, ``field_label`` and
``refs``."""

from __future__ import annotations

import decimal
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.core import codes
from app.core.errors import NotFoundError
from app.models.dataset import Dataset
from app.validation.contracts.detector import DetectorResult
from app.validation.contracts.issue_factory import IssuePolicyError
from app.validation.contracts.limits import DetectorStopped, IssueLimitReached, TimeLimitReached
from app.validation.deterministic import _support
from tests.support.builders import DatasetBuilder, make_context

SEGMENTERS = pytest.mark.parametrize(
    "segments", [codes.code_segments, _support.code_segments], ids=["core", "support"]
)


class TestCodeSegments:
    @SEGMENTERS
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("١٢", ("١٢",)),  # Arabic-Indic digits stay text (never int()-converted)
            ("٠١٢.3", ("٠١٢", "3")),  # ... and keep their leading zero
            ("१२.०३", ("१२", "०३")),  # Devanagari likewise
            ("０１.０２", ("1", "2")),  # full-width digits are ASCII after NFKC
            ("007a.0", ("007a", "0")),  # zeros are stripped only from all-digit segments
            ("000", ("0",)),
            ("01.10", ("1", "10")),
            ("1/2.3", ("1", "2", "3")),
        ],
    )
    def test_digits_and_leading_zeros(self, segments, text, expected) -> None:
        assert segments(text) == expected

    @SEGMENTERS
    def test_unicode_digits_never_equal_ascii_digits(self, segments) -> None:
        assert segments("١٢") != segments("12")
        assert segments("०१") != segments("1")

    @SEGMENTERS
    @pytest.mark.parametrize(
        "text",
        [
            "0" * 33,  # length is checked before zero stripping
            "1.2." + "3" * 33,  # one implausible segment invalidates the whole code
            "١" * 33,
            "a" * (codes.MAX_CODE_SEGMENT_CHARS + 1),
        ],
    )
    def test_segments_over_32_characters_are_not_codes(self, segments, text) -> None:
        assert segments(text) is None

    @SEGMENTERS
    def test_a_32_character_segment_is_still_a_code(self, segments) -> None:
        assert segments("0" * 32) == ("0",)
        assert segments("01." + "9" * 32) == ("1", "9" * 32)

    @SEGMENTERS
    @pytest.mark.parametrize(
        "text", ["\x00", "./.", "٫٬", "9" * 10_000, "1." * 99 + "1", "\ud800", "🙂.🙂", "--1"]
    )
    def test_document_text_never_raises(self, segments, text) -> None:
        result = segments(text)
        assert result is None or all(isinstance(part, str) and part for part in result)

    # Invisible format characters (Unicode Cf) are not part of a code.
    @pytest.mark.parametrize("invisible", ["​", "­", "﻿", "⁠"])
    def test_invisible_format_characters_do_not_change_a_code(self, invisible) -> None:
        assert codes.code_segments(f"{invisible}01.{invisible}02") == ("1", "2")


class TestStrictPrefix:
    @pytest.mark.parametrize(
        ("prefix", "code", "expected"),
        [
            ("01", "1.2", True),
            ("01.02", "1.2.0030", True),
            ("1", "12", False),  # segment-wise, not character-wise
            ("01.1", "01.10", False),
            ("1.2", "1.2", False),  # equal is not strict
            ("1.2.3", "1.2", False),
            ("١", "١.2", True),
            ("1", "١.2", False),
        ],
    )
    def test_segment_prefixes(self, prefix, code, expected) -> None:
        assert (
            _support.is_strict_prefix(_support.code_segments(prefix), _support.code_segments(code))
            is expected
        )

    def test_none_is_never_a_prefix_or_a_code(self) -> None:
        assert not _support.is_strict_prefix(("1",), None)
        assert not _support.is_strict_prefix(None, None)
        assert not _support.is_strict_prefix(("1",), _support.code_segments("1" * 40))


@pytest.fixture
def dataset(boq_profile) -> Dataset:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", [("Qty", "quantity"), ("Rate", "unit_price"), ("Note", None)])
    for index in range(25):
        table.row([str(index + 1), "2.50", "x"])
    return builder.build()


class _Payload(BaseModel):
    amount: int


def _pydantic_error() -> ValidationError:
    try:
        _Payload.model_validate({"amount": "Geheimer Text"})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a validation error")


class TestRowGuard:
    def test_failed_rows_are_counted_and_at_most_twenty_are_listed(self, dataset) -> None:
        table = dataset.tables[0]
        result = DetectorResult()
        continued = 0
        for row in table.rows:
            with _support.row_guard(result, table, row):
                if row.source_row_number % 2:
                    raise decimal.InvalidOperation("Geheimer Text 1E+999999")
                raise ValueError("Geheimer Text")
            continued += 1  # the guard swallowed the error: the detector goes on
        assert continued == 25
        assert result.coverage == {"rows_failed": 25}
        assert len(result.notes) == 20
        assert result.notes[0] == "'LV' row 2 could not be checked (ValueError); it was skipped."
        assert result.notes[1] == (
            "'LV' row 3 could not be checked (InvalidOperation); it was skipped."
        )
        assert result.notes[-1].startswith("'LV' row 21 ")
        # Exception text can carry document content: only the type is shown.
        assert not any("Geheim" in note for note in result.notes)

    def test_rows_that_pass_are_not_counted(self, dataset) -> None:
        table = dataset.tables[0]
        result = DetectorResult()
        for row in table.rows[:3]:
            with _support.row_guard(result, table, row):
                result.count("rows_checked")
        with _support.row_guard(result, table, table.rows[3]):
            _ = Decimal(1) / Decimal(0)
        assert result.coverage == {"rows_checked": 3, "rows_failed": 1}
        assert result.notes == ["'LV' row 5 could not be checked (DivisionByZero); it was skipped."]

    @pytest.mark.parametrize(
        "error",
        [
            IssuePolicyError("undeclared evidence class"),
            _pydantic_error(),  # a ValueError subclass, but a programming error
            TimeLimitReached("Stopped after the time limit of 1 s."),
            IssueLimitReached("Stopped at the limit of 1 findings for this check."),
            DetectorStopped("stopped"),
            NotFoundError("no such cell"),
            KeyError("column"),
        ],
        ids=lambda e: type(e).__name__,
    )
    def test_programming_errors_and_run_limits_propagate(self, dataset, error) -> None:
        table = dataset.tables[0]
        result = DetectorResult()
        with pytest.raises(type(error)), _support.row_guard(result, table, table.rows[0]):
            raise error
        assert result.coverage == {} and result.notes == []


class TestFormatting:
    @pytest.mark.parametrize(
        ("value", "text"),
        [
            (Decimal("1E+3"), "1000"),
            (Decimal("1.20E+2"), "120"),
            (Decimal("1E+24"), "1" + "0" * 24),
            (Decimal("12.50"), "12.50"),  # trailing zeros are kept: they are what was written
            (Decimal("1E-20"), "0.00000000000000000001"),
            (Decimal("-1.5E-7"), "-0.00000015"),
            (Decimal("0E-5"), "0.00000"),
            # Zeros are written unsigned: -1 × 0.00 = -0.00 must not read "expected -0.00".
            (Decimal("-0"), "0"),
            (Decimal("-0.00"), "0.00"),
        ],
    )
    def test_fmt_is_plain_decimal_text(self, value, text) -> None:
        assert _support.fmt(value) == text
        assert "E" not in _support.fmt(value)

    def test_fmt_keeps_none(self) -> None:
        assert _support.fmt(None) is None

    def test_row_label(self, dataset) -> None:
        table = dataset.tables[0]
        assert _support.row_label(table, table.rows[12]) == "'LV' row 14"

    def test_field_label(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        assert _support.field_label(context, "unit_price") == "Unit price"
        assert _support.field_label(context, "quantity") == "Quantity"
        assert _support.field_label(context, "no_such_field") == "no_such_field"

    def test_refs_skip_unmapped_fields(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        refs = _support.refs(context, table, row, ["quantity", "line_total", "unit_price"])
        assert [r.source.a1 for r in refs] == ["A2", "B2"]
