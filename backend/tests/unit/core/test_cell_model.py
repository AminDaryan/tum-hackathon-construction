"""The ``Cell`` marker invariant, the context accessors for markers, numbers and text, the
dataset builder's automatic value markers and its extraction quality rule."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import cell_rules as rules
from app.models.dataset import Cell, Dataset, ExtractionQuality, ExtractionWarning
from app.models.source import SourceKind, SourceLocation
from app.models.values import DataType, NumberValue, ParseStatus, TextValue, ValueMarker
from tests.support.builders import (
    DatasetBuilder,
    ambiguous_cell,
    error_cell,
    failed_number_cell,
    make_context,
    number_cell,
    unavailable_formula_cell,
)

SOURCE = SourceLocation(
    kind=SourceKind.SPREADSHEET, sheet_name="LV", sheet_index=0, row_number=2, column_number=3
)
MARKER_RULE = "Cell.marker must be set exactly when parse_status is 'marker'"
COLUMNS = [
    ("Item", "item_code"),
    ("Description", "description"),
    ("Qty", "quantity"),
    ("Unit", "unit"),
    ("Rate", "unit_price"),
    ("Amount", "line_total"),
    ("Note", None),
]


def _text_cell(status: ParseStatus, marker: ValueMarker | None) -> Cell:
    return Cell(
        raw_value="Incl.",
        parsed_value=TextValue(value="Incl."),
        normalized_value=TextValue(value="Incl."),
        data_type=DataType.TEXT,
        parse_status=status,
        source=SOURCE,
        marker=marker,
    )


class TestMarkerInvariant:
    @pytest.mark.parametrize("marker", list(ValueMarker))
    def test_marker_status_with_a_marker_is_valid(self, marker: ValueMarker) -> None:
        cell = _text_cell(ParseStatus.MARKER, marker)
        assert cell.marker is marker
        assert Cell.model_validate(cell.model_dump(mode="json")) == cell

    def test_marker_status_without_a_marker_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match=MARKER_RULE):
            _text_cell(ParseStatus.MARKER, None)

    @pytest.mark.parametrize("status", [s for s in ParseStatus if s is not ParseStatus.MARKER])
    def test_a_marker_needs_the_marker_status(self, status: ParseStatus) -> None:
        with pytest.raises(ValidationError, match=MARKER_RULE):
            _text_cell(status, ValueMarker.NIL)

    def test_evolve_keeps_the_invariant_in_both_directions(self) -> None:
        marker = rules.marker_cell("Incl.", SOURCE, ValueMarker.INCLUDED_ELSEWHERE)
        with pytest.raises(ValidationError, match=MARKER_RULE):
            marker.evolve(parse_status=ParseStatus.FAILED)
        assert marker.evolve(parse_status=ParseStatus.FAILED, marker=None).marker is None
        text = rules.text_cell("Incl.", SOURCE)
        with pytest.raises(ValidationError, match=MARKER_RULE):
            text.evolve(marker=ValueMarker.NIL)
        promoted = text.evolve(marker=ValueMarker.NIL, parse_status=ParseStatus.MARKER)
        assert promoted.marker is ValueMarker.NIL


@pytest.fixture
def dataset(boq_profile) -> Dataset:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", COLUMNS)
    table.row(["01.0010", "  Aushub   BK 3 ", "10", "m3", "12.50", "125.00", "x"])
    # An item code typed as a number; lump-sum quantity; markers in both amounts.
    table.row([number_cell("110", raw=" 110 "), "Beton", "psch", "m3", "Incl.", "-", None])
    table.row(
        [
            "01.0030",
            "Schalung",
            ambiguous_cell("1.234"),
            "m2",
            failed_number_cell("approx. 5"),
            unavailable_formula_cell(),
            "   ",
        ]
    )
    table.row(
        ["01.0040", "Stahl", number_cell("3", status="inferred"), "t", error_cell(), None, None]
    )
    return builder.build()


class TestContextAccessors:
    def test_numbers_only_from_exact_or_inferred_cells(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        usable, markers, unusable, inferred = table.rows

        def numbers(field_id: str) -> list[Decimal | None]:
            return [context.number(table, row, field_id) for row in table.rows]

        assert numbers("quantity") == [Decimal(10), None, None, Decimal(3)]  # marker, ambiguous
        assert numbers("unit_price") == [Decimal("12.50"), None, None, None]  # failed, error
        assert numbers("line_total") == [Decimal("125.00"), None, None, None]  # unavailable, empty
        assert context.number_value(table, usable, "unit_price") == NumberValue(value="12.50")
        for row in (markers, unusable):
            for field_id in ("quantity", "unit_price", "line_total"):
                assert context.number_value(table, row, field_id) is None
        # The column-id accessors follow the same rules.
        for field_id in ("quantity", "unit_price", "line_total"):
            column_id = table.column_for_field(field_id).column_id
            assert [context.number_at(row, column_id) for row in table.rows] == numbers(field_id)
        assert context.number(table, inferred, "currency") is None  # unmapped field

    def test_markers(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        usable, markers, unusable, _ = table.rows
        assert context.marker(table, markers, "quantity") is ValueMarker.LUMP_SUM
        assert context.marker(table, markers, "unit_price") is ValueMarker.INCLUDED_ELSEWHERE
        assert context.marker(table, markers, "line_total") is ValueMarker.NIL
        for row in (usable, unusable):
            for field_id in ("quantity", "unit_price", "line_total"):
                assert context.marker(table, row, field_id) is None
        assert context.marker(table, markers, "currency") is None  # unmapped field
        column_id = table.column_for_field("unit_price").column_id
        assert context.marker_at(markers, column_id) is ValueMarker.INCLUDED_ELSEWHERE
        assert context.marker_at(markers, "col_does_not_exist") is None

    def test_text(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        usable, markers, unusable, inferred = table.rows
        # An item code typed as a number reads as its (stripped) raw text.
        assert context.text(table, markers, "item_code") == "110"
        assert context.number(table, markers, "item_code") == Decimal(110)
        assert context.text(table, usable, "item_code") == "01.0010"
        assert context.text(table, usable, "description") == "Aushub BK 3"  # collapsed
        assert context.text(table, markers, "unit_price") == "Incl."  # a marker is text
        assert context.text(table, unusable, "quantity") == "1.234"  # ambiguous: raw text
        assert context.text(table, unusable, "line_total") is None  # unavailable: no raw text
        assert context.text(table, inferred, "line_total") is None  # empty
        # The raw fallback covers every non-text value, including error literals; detectors
        # that read codes must leave error cells to deterministic.formula_errors.
        assert context.text(table, inferred, "unit_price") == "#REF!"
        note = table.columns[-1].column_id
        assert context.text_at(unusable, note) is None  # blank text is an empty cell
        assert context.text_at(usable, note) == "x"
        assert context.text(table, usable, "currency") is None  # unmapped field


def _single_cell(profile, header: str, field_id: str | None, value) -> Cell:
    builder = DatasetBuilder(profile)
    builder.table("LV", [("Pos", None), (header, field_id)]).row(["1", value])
    table = builder.build().tables[0]
    return table.rows[0].cells[table.columns[1].column_id]


class TestBuilderMarkers:
    @pytest.mark.parametrize(
        ("field_id", "raw", "marker"),
        [
            ("line_total", "Incl.", ValueMarker.INCLUDED_ELSEWHERE),
            ("line_total", " Incl. ", ValueMarker.INCLUDED_ELSEWHERE),
            ("quantity", "Incl.", ValueMarker.INCLUDED_ELSEWHERE),
            ("unit_price", "nur EP", ValueMarker.RATE_ONLY),
            ("quantity", "psch", ValueMarker.LUMP_SUM),
            ("quantity", "PSCH.", ValueMarker.LUMP_SUM),
            ("quantity", "entfällt", ValueMarker.NOT_APPLICABLE),
            ("line_total", "-", ValueMarker.NIL),
            ("unit_price", "nicht angeboten", ValueMarker.NOT_OFFERED),
            ("line_total", "Not offered", ValueMarker.NOT_OFFERED),
        ],
    )
    def test_profile_tokens_in_numeric_columns_become_marker_cells(
        self, boq_profile, field_id, raw, marker
    ) -> None:
        cell = _single_cell(boq_profile, "Value", field_id, raw)
        assert (cell.data_type, cell.parse_status, cell.marker) == (
            DataType.TEXT,
            ParseStatus.MARKER,
            marker,
        )
        assert cell.raw_value == raw  # never stripped
        assert cell.parsed_value == TextValue(value=raw)
        assert cell.normalized_value == TextValue(value=raw.strip())

    @pytest.mark.parametrize(
        ("field_id", "raw"),
        [
            ("unit_price", "psch"),  # lump_sum applies to quantities only
            ("quantity", "nur EP"),  # rate_only applies to monetary fields only
            ("quantity", "nicht angeboten"),  # not_offered applies to monetary fields only
            ("quantity", "approx. 5"),
        ],
    )
    def test_other_text_in_numeric_columns_is_a_failed_number(
        self, boq_profile, field_id, raw
    ) -> None:
        cell = _single_cell(boq_profile, "Value", field_id, raw)
        assert (cell.parse_status, cell.marker) == (ParseStatus.FAILED, None)

    @pytest.mark.parametrize(
        ("field_id", "raw"),
        [
            ("description", "Incl."),
            ("description", "psch"),
            ("item_code", "entfällt"),
            ("unit", "psch"),
            (None, "Incl."),  # unmapped column
        ],
    )
    def test_the_same_tokens_in_text_columns_stay_text(self, boq_profile, field_id, raw) -> None:
        cell = _single_cell(boq_profile, "Text", field_id, raw)
        assert (cell.data_type, cell.parse_status, cell.marker) == (
            DataType.TEXT,
            ParseStatus.NOT_APPLICABLE,
            None,
        )

    @pytest.mark.parametrize("raw", ["1E+999999", "1E-21", "1" * 30, "+inf", "-nan", "sNaN"])
    def test_out_of_range_number_text_becomes_a_failed_cell(self, boq_profile, raw) -> None:
        cell = _single_cell(boq_profile, "Qty", "quantity", raw)
        assert (cell.data_type, cell.parse_status, cell.raw_value) == (
            DataType.TEXT,
            ParseStatus.FAILED,
            raw,
        )

    def test_markers_are_counted_apart_in_the_type_profile(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [("Amount", "line_total")])
        for value in ("Incl.", "Incl.", "-", "125.00"):
            table.row([value])
        column = builder.build().tables[0].columns[0]
        assert column.type_profile.marker_count == 3
        assert column.type_profile.counts == {DataType.NUMBER: 1}
        assert column.type_profile.non_empty == 1
        assert column.inferred_type is DataType.NUMBER


def _warning(code: str, *, needs_review: bool) -> ExtractionWarning:
    return ExtractionWarning(code=code, message=code.replace("_", " "), needs_review=needs_review)


class TestBuilderQuality:
    @pytest.mark.parametrize(
        ("warnings", "quality"),
        [
            ([], ExtractionQuality.OK),
            ([_warning("hidden_rows_present", needs_review=False)], ExtractionQuality.OK),
            ([_warning("header_uncertain", needs_review=True)], ExtractionQuality.NEEDS_REVIEW),
            (
                [
                    _warning("hidden_rows_present", needs_review=False),
                    _warning("column_mapping_ambiguous", needs_review=True),
                ],
                ExtractionQuality.NEEDS_REVIEW,
            ),
        ],
    )
    def test_quality_is_derived_from_the_warnings(self, boq_profile, warnings, quality) -> None:
        builder = DatasetBuilder(boq_profile, warnings=warnings)
        builder.table("LV", [("Qty", "quantity")]).row(["1"])
        extraction = builder.build().extraction
        assert extraction.quality is quality
        assert extraction.warnings == warnings

    @pytest.mark.parametrize(
        "warnings", [[], [_warning("hidden_rows_present", needs_review=False)]]
    )
    def test_an_explicit_failed_quality_is_kept(self, boq_profile, warnings) -> None:
        builder = DatasetBuilder(boq_profile, quality=ExtractionQuality.FAILED, warnings=warnings)
        builder.table("LV", [("Qty", "quantity")]).row(["1"])
        assert builder.build().extraction.quality is ExtractionQuality.FAILED
