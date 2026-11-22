"""The normalization output matrix for single cells (app.models.cell_rules)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models import cell_rules as rules
from app.models.dataset import FormulaInfo
from app.models.source import SourceKind, SourceLocation
from app.models.values import (
    DataType,
    DateValue,
    ErrorValue,
    NumberValue,
    ParseStatus,
    TextValue,
    ValueMarker,
)

SOURCE = SourceLocation(kind=SourceKind.SPREADSHEET, sheet_index=0, row_number=2, column_number=3)


@pytest.mark.parametrize(
    "text",
    [None, "", " ", "\t\n", " ", "  ", "​", " ​﻿ "],
)
def test_blank_text(text) -> None:
    assert rules.is_blank(text)


@pytest.mark.parametrize("text", ["0", "-", "a", " x ", "​x"])
def test_not_blank(text) -> None:
    assert not rules.is_blank(text)


def test_normalize_text_collapses_whitespace_without_folding() -> None:
    assert rules.normalize_text("  Aushub  Boden\n Klasse 3 ") == "Aushub Boden Klasse 3"
    assert rules.normalize_text("m²") == "m²"  # no NFKC: the text is still what was written
    assert rules.normalize_text("Café") == "Café"  # NFC composes


def test_blank_text_cell_is_empty_but_keeps_its_raw_text() -> None:
    cell = rules.text_cell("  ", SOURCE)
    assert cell.data_type is DataType.EMPTY
    assert cell.parse_status is ParseStatus.NOT_APPLICABLE
    assert cell.raw_value == "  "
    assert cell.parsed_value is None and cell.normalized_value is None


def test_text_cell() -> None:
    cell = rules.text_cell("  Erdaushub   BK 3 ", SOURCE)
    assert cell.data_type is DataType.TEXT
    assert cell.parsed_value == TextValue(value="  Erdaushub   BK 3 ")
    assert cell.normalized_value == TextValue(value="Erdaushub BK 3")
    assert cell.extraction_confidence is None


def test_unit_cell_normalizes_to_the_unit_id() -> None:
    assert rules.unit_cell("m²", SOURCE, "m2").normalized_value == TextValue(value="m2")
    unknown = rules.unit_cell(" VE ", SOURCE, None)
    assert unknown.normalized_value == TextValue(value="VE")
    assert rules.unit_cell(" ", SOURCE, None).is_empty


def test_number_cells_are_exact_or_inferred_only() -> None:
    value = NumberValue(value=Decimal("1234.5"))
    exact = rules.number_cell(value, SOURCE, raw="1.234,5")
    assert (exact.data_type, exact.parse_status) == (DataType.NUMBER, ParseStatus.EXACT)
    assert exact.parsed_value == exact.normalized_value == value
    inferred = rules.number_cell(
        value, SOURCE, raw="1,234.5", status=ParseStatus.INFERRED, note="from column"
    )
    assert inferred.parse_note == "from column"
    with pytest.raises(ValueError, match="exact or inferred"):
        rules.number_cell(value, SOURCE, raw="x", status=ParseStatus.AMBIGUOUS)


def test_failed_marker_ambiguous_error_unavailable() -> None:
    failed = rules.failed_cell("approx. 5", SOURCE, "Not a number: 'approx. 5'")
    assert (failed.data_type, failed.parse_status) == (DataType.TEXT, ParseStatus.FAILED)
    assert failed.normalized_value == TextValue(value="approx. 5")

    marker = rules.marker_cell(" Incl. ", SOURCE, ValueMarker.INCLUDED_ELSEWHERE)
    assert marker.parse_status is ParseStatus.MARKER
    assert marker.marker is ValueMarker.INCLUDED_ELSEWHERE
    assert marker.normalized_value == TextValue(value="Incl.")

    ambiguous = rules.ambiguous_cell("1.234", SOURCE, "Could be 1.234 or 1234")
    assert (ambiguous.data_type, ambiguous.parse_status) == (
        DataType.UNKNOWN,
        ParseStatus.AMBIGUOUS,
    )
    assert ambiguous.parsed_value is None and ambiguous.normalized_value is None

    error = rules.error_cell(
        "#REF!", SOURCE, formula=FormulaInfo(expression="=A1", cached_result_available=True)
    )
    assert error.data_type is DataType.ERROR and error.normalized_value == ErrorValue(code="#REF!")
    assert error.raw_value == "#REF!"

    formula = FormulaInfo(expression="=B2*C2", cached_result_available=False)
    unavailable = rules.unavailable_cell(SOURCE, formula)
    assert unavailable.parse_status is ParseStatus.UNAVAILABLE
    assert unavailable.data_type is DataType.UNKNOWN
    assert unavailable.parse_note == rules.UNAVAILABLE_NOTE


def test_typed_cells() -> None:
    cell = rules.typed_cell(
        DateValue(value=date(2026, 3, 1)), DataType.DATE, SOURCE, raw="1.3.2026"
    )
    assert cell.normalized_value == DateValue(value=date(2026, 3, 1))
    with pytest.raises(ValueError, match="boolean, date and datetime"):
        rules.typed_cell(DateValue(value=date(2026, 3, 1)), DataType.NUMBER, SOURCE, raw="x")


def test_confidence_is_copied_only_when_given() -> None:
    assert rules.text_cell("x", SOURCE).extraction_confidence is None
    assert rules.text_cell("x", SOURCE, confidence=0.42).extraction_confidence == 0.42
