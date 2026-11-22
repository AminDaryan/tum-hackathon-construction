"""build_dataset: headers, mapping, cells, rows, sections, totals, decisions and warnings."""

from __future__ import annotations

import copy
import time
from decimal import Decimal

import pytest

from app.core.errors import ExtractionError
from app.ingestion.base import MergedRange, RawCell, RawValueType
from app.models.dataset import ExtractionQuality, HeaderMethod, MappingMethod, RowKind
from app.models.document import DocumentFormat
from app.models.profile import DomainProfile
from app.models.schema import SchemaDecisions, TableDecisions
from app.models.source import SourceKind
from app.models.values import DataType, NumberValue, ParseStatus, TextValue, ValueMarker
from tests.unit.normalization.raw_builders import (
    ENGLISH_BOQ,
    GERMAN_LV,
    by_source_row,
    cell,
    codes,
    formula,
    kinds,
    normalize,
    sheet,
    workbook,
)

HEADER = ["OZ", "Kurztext", "Menge", "ME", "EP", "GP"]


def section_row(table, row_id: str | None) -> int | None:
    return table.row(row_id).source_row_number if row_id else None


# ---------------------------------------------------------------------------- headers


class TestHeaders:
    def test_german_lv_with_title_block(self, boq_profile: DomainProfile) -> None:
        table = normalize(workbook(sheet(GERMAN_LV)), boq_profile).tables[0]
        assert table.header.header_row_numbers == [4]
        assert table.header.method is HeaderMethod.PROFILE_SYNONYMS
        assert table.header.note == "Rows 1-2 above the header were treated as a title block."
        fields = [c.mapped_semantic_field for c in table.columns]
        assert fields == [
            "item_code",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "line_total",
        ]
        assert [c.normalized_name for c in table.columns] == [
            "oz",
            "kurztext",
            "menge",
            "me",
            "ep",
            "gp",
        ]
        assert min(r.source_row_number for r in table.rows) == 5  # title rows are not data

    def test_english_boq(self, boq_profile: DomainProfile) -> None:
        table = normalize(workbook(sheet(ENGLISH_BOQ)), boq_profile).tables[0]
        assert table.header.header_row_numbers == [1]
        assert table.column_for_field("unit_price").original_header == "Rate"  # type: ignore[union-attr]
        assert table.column_for_field("line_total").original_header == "Amount"  # type: ignore[union-attr]

    def test_two_row_header_with_merged_price_cell(self, boq_profile: DomainProfile) -> None:
        rows = [
            ["OZ", "Kurztext", "Menge", "ME", "Preis", None],
            [None, None, None, None, "EP", "GP"],
            ["1.1", "Beton", "2", "m3", "100,00", "200,00"],
        ]
        merged = [MergedRange(min_row=1, min_column=5, max_row=1, max_column=6)]
        table = normalize(workbook(sheet(rows, merged=merged)), boq_profile).tables[0]
        assert table.header.header_row_numbers == [1, 2]
        assert table.column_for_field("unit_price").source_column_number == 5  # type: ignore[union-attr]
        assert table.column_for_field("line_total").source_column_number == 6  # type: ignore[union-attr]
        assert table.column_for_field("line_total").original_header == "Preis GP"  # type: ignore[union-attr]
        assert "Two-row header (rows 1 and 2)." in (table.header.note or "")
        assert [r.source_row_number for r in table.rows] == [3]

    def test_structural_and_first_row_fallbacks(self, generic_profile: DomainProfile) -> None:
        rows = [["Report"], ["Name", "Amount", "Date"], ["a", "5", "2026-01-02"], ["b", "7", None]]
        dataset = normalize(workbook(sheet(rows)), generic_profile)
        table = dataset.tables[0]
        assert table.header.method is HeaderMethod.STRUCTURAL
        assert table.header.header_row_numbers == [2]
        uncertain = [w for w in dataset.extraction.warnings if w.code == "header_uncertain"]
        assert len(uncertain) == 1
        assert not uncertain[0].needs_review  # nothing to map in a profile without fields
        assert dataset.extraction.quality is ExtractionQuality.OK
        first = normalize(workbook(sheet([["Name", "Note"], ["a", "b"]])), generic_profile)
        assert first.tables[0].header.method is HeaderMethod.FIRST_ROW

    def test_no_header(self, generic_profile: DomainProfile) -> None:
        table = normalize(workbook(sheet([[1, 2], [3, 4]])), generic_profile).tables[0]
        assert table.header.method is HeaderMethod.NONE
        assert table.header.header_row_numbers == []
        assert [c.normalized_name for c in table.columns] == ["column_a", "column_b"]
        assert [c.original_header for c in table.columns] == [None, None]
        assert len(table.rows) == 2

    def test_uncertain_header_needs_review_for_a_profile_with_fields(
        self, boq_profile: DomainProfile
    ) -> None:
        dataset = normalize(workbook(sheet([["Foo", "Bar"], ["x", "1"]])), boq_profile)
        warning = next(w for w in dataset.extraction.warnings if w.code == "header_uncertain")
        assert warning.needs_review
        assert dataset.extraction.quality is ExtractionQuality.NEEDS_REVIEW

    def test_header_currency_only_for_money_columns(self, boq_profile: DomainProfile) -> None:
        rows = [
            ["Pos.", "Text", "Menge", "Einheit", "EP [€]", "GP [EUR]", "CAD Plan"],
            ["1", "x", "1", "m", "2,00", "2,00", "A1"],
        ]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        assert table.column_for_field("unit_price").header_currency == "EUR"  # type: ignore[union-attr]
        assert table.column_for_field("line_total").header_currency == "EUR"  # type: ignore[union-attr]
        assert table.columns[-1].header_currency is None


# ---------------------------------------------------------------------------- mapping


class TestMapping:
    def test_one_field_per_column_and_methods(self, boq_profile: DomainProfile) -> None:
        rows = [
            ["Pos.-Nr.", "Kurztext", "Menge", "Einheit", "Einheitspreis netto", "Gesamtpreis"],
            ["1", "x", "1", "m", "2", "2"],
        ]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        price = table.column_for_field("unit_price")
        assert price is not None and price.mapping is not None
        assert price.mapping.method is MappingMethod.HEADER_CONTAINS
        assert 0 < (price.mapping.similarity or 0) < 1
        fields = [c.mapped_semantic_field for c in table.columns if c.mapping]
        assert len(fields) == len(set(fields))

    def test_tied_columns_stay_unmapped(self, boq_profile: DomainProfile) -> None:
        rows = [["OZ", "Kurztext", "Kurztext", "Menge"], ["1", "a", "b", "2"]]
        dataset = normalize(workbook(sheet(rows)), boq_profile)
        table = dataset.tables[0]
        assert table.column_for_field("description") is None
        assert "column_mapping_ambiguous" in codes(dataset)

    def test_number_field_without_numbers_loses_its_mapping(
        self, boq_profile: DomainProfile
    ) -> None:
        rows = [
            ["OZ", "Kurztext", "Menge", "EP"],
            ["1", "a", "viel", "2"],
            ["2", "b", "wenig", "3"],
            ["3", "c", "etwas", "4"],
        ]
        dataset = normalize(workbook(sheet(rows)), boq_profile)
        table = dataset.tables[0]
        assert table.column_for_field("quantity") is None
        assert table.columns[2].mapping is None
        assert by_source_row(table)[2].cells[table.columns[2].column_id].data_type is DataType.TEXT
        assert "mapping_rejected_type_mismatch" in codes(dataset)

    def test_required_fields_missing(self, boq_profile: DomainProfile) -> None:
        dataset = normalize(workbook(sheet([["OZ", "Kurztext"], ["1", "x"]])), boq_profile)
        assert "required_field_unmapped" in codes(dataset)

    def test_fields_without_header_matching_need_a_declaration(
        self, boq_profile: DomainProfile
    ) -> None:
        # match_headers: false (GAEB-only fields): not even the label or field id maps them.
        rows = [
            ["OZ", "Kurztext", "Rabatt", "discount_percent", "Standard text key"],
            ["1", "x", "1.5", "2", "STLB"],
        ]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        assert [c.mapping.field_id for c in table.columns if c.mapping] == [
            "item_code",
            "description",
        ]
        declared = sheet(rows)
        declared.declared = TableDecisions(sheet_index=0, column_fields={3: "discount_percent"})
        table = normalize(workbook(declared), boq_profile).tables[0]
        assert table.column_for_field("discount_percent").source_column_number == 3  # type: ignore[union-attr]


# ---------------------------------------------------------------------------- cells


class TestCells:
    def test_german_numbers_and_units(self, boq_profile: DomainProfile) -> None:
        table = normalize(workbook(sheet(GERMAN_LV)), boq_profile).tables[0]
        quantity = cell(table, 7, "quantity")
        assert quantity.normalized_value == NumberValue(value=Decimal("1250.50"))
        assert quantity.parse_status is ParseStatus.EXACT
        assert quantity.raw_value == "1.250,50"
        assert table.column_for_field("quantity").decimal_separator == ","  # type: ignore[union-attr]
        assert cell(table, 7, "unit").normalized_value == TextValue(value="m2")
        assert cell(table, 14, "line_total").marker is ValueMarker.RATE_ONLY
        assert cell(table, 7, "quantity").extraction_confidence is None

    def test_unit_aliases_resolve_to_the_canonical_id(self, boq_profile: DomainProfile) -> None:
        rows = [HEADER, ["1", "a", "2", "m²", "1,50", "3,00"]]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        unit = cell(table, 2, "unit")
        assert unit.raw_value == "m²"
        assert unit.normalized_value == TextValue(value="m2")

    def test_formulas_typed_values_and_percent(self, boq_profile: DomainProfile) -> None:
        percent = RawCell(
            2, 7, RawValueType.NUMBER, "0.19", number=Decimal("0.19"), number_format="0%"
        )
        rows = [
            [*HEADER, "Satz"],
            ["1", "a", 2, "m", Decimal("1.5"), formula(2, 6, "=C2*E2", 3), percent],
            ["2", "b", 2, "m", Decimal("1.5"), formula(3, 6, "=C3*E3")],
        ]
        dataset = normalize(workbook(sheet(rows)), boq_profile)
        table = dataset.tables[0]
        cached = cell(table, 2, "line_total")
        assert cached.formula is not None and cached.formula.cached_result_available
        assert cached.normalized_value == NumberValue(value=Decimal(3))
        missing = cell(table, 3, "line_total")
        assert missing.parse_status is ParseStatus.UNAVAILABLE
        assert missing.normalized_value is None
        rate = by_source_row(table)[2].cells[table.columns[6].column_id]
        assert rate.normalized_value == NumberValue(value=Decimal("0.19"), is_percent=True)
        warning = next(
            w for w in dataset.extraction.warnings if w.code == "formula_without_cached_result"
        )
        assert warning.count == 1 and warning.needs_review

    def test_currency_only_from_explicit_markers(self, boq_profile: DomainProfile) -> None:
        euro = RawCell(
            2, 6, RawValueType.NUMBER, "2", number=Decimal(2), number_format='#,##0.00 "€"'
        )
        rows = [HEADER, ["1", "a", "1", "m", "€ 2,00", euro], ["2", "b", "1", "m", "2,00", "2,00"]]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        assert cell(table, 2, "unit_price").normalized_value.currency == "EUR"  # type: ignore[union-attr]
        assert cell(table, 2, "line_total").normalized_value.currency == "EUR"  # type: ignore[union-attr]
        assert cell(table, 3, "line_total").normalized_value.currency is None  # type: ignore[union-attr]

    def test_whitespace_failed_markers_and_ranges(self, boq_profile: DomainProfile) -> None:
        rows = [HEADER, ["1", "a", "   ", "m", "Incl.", "ca. 5"], ["2", "b", "1e40", "m", "1", "1"]]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        blank = cell(table, 2, "quantity")
        assert blank.data_type is DataType.EMPTY and blank.raw_value == "   "
        assert cell(table, 2, "unit_price").marker is ValueMarker.INCLUDED_ELSEWHERE
        failed = cell(table, 2, "line_total")
        assert failed.parse_status is ParseStatus.FAILED and failed.data_type is DataType.TEXT
        assert "Not a number" in (failed.parse_note or "")
        assert cell(table, 3, "quantity").parse_status is ParseStatus.FAILED

    def test_delimited_text_line_numbers_and_ocr_confidence(
        self, boq_profile: DomainProfile
    ) -> None:
        rows = [
            [
                RawCell(1, 1, RawValueType.STRING, "OZ", line_number=1),
                RawCell(1, 2, RawValueType.STRING, "Menge", line_number=1),
            ],
            [
                RawCell(2, 1, RawValueType.STRING, "1", line_number=3),
                RawCell(2, 2, RawValueType.STRING, "5", line_number=3, confidence=0.42),
            ],
        ]
        raw = workbook(sheet(rows, kind=SourceKind.DELIMITED_TEXT), fmt=DocumentFormat.CSV)
        table = normalize(raw, boq_profile).tables[0]
        quantity = cell(table, 2, "quantity")
        assert quantity.source.line_number == 3
        assert quantity.source.kind is SourceKind.DELIMITED_TEXT
        assert quantity.extraction_confidence == pytest.approx(0.42)
        assert cell(table, 2, "item_code").extraction_confidence is None


class TestSeparators:
    def test_column_evidence_resolves_ambiguous_values(self, boq_profile: DomainProfile) -> None:
        rows = [HEADER, ["1", "a", "1.234", "m", "2,5", "1,00"], ["2", "b", "2,5", "m", "1", "1"]]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        quantity = cell(table, 2, "quantity")
        assert quantity.normalized_value == NumberValue(value=Decimal(1234))
        assert quantity.parse_status is ParseStatus.INFERRED
        assert quantity.parse_note == "Decimal separator ',' inferred from 1 value in this column."

    def test_document_evidence_and_locale(self, boq_profile: DomainProfile) -> None:
        rows = [HEADER, ["1", "a", "1.234", "m", "2,50", "1,00"]]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        quantity = cell(table, 2, "quantity")
        assert quantity.normalized_value == NumberValue(value=Decimal(1234))
        assert "elsewhere in the document" in (quantity.parse_note or "")
        english = boq_profile.evolve(locale=boq_profile.locale.evolve(decimal_separator="."))
        alone = normalize(workbook(sheet([HEADER, ["1", "a", "1.234", "m"]])), english).tables[0]
        assert cell(alone, 2, "quantity").normalized_value == NumberValue(value=Decimal("1.234"))
        assert "locale" in (cell(alone, 2, "quantity").parse_note or "")

    def test_no_evidence_leaves_the_value_unread(self, boq_profile: DomainProfile) -> None:
        dataset = normalize(workbook(sheet([HEADER, ["1", "a", "1.234", "m"]])), boq_profile)
        quantity = cell(dataset.tables[0], 2, "quantity")
        assert quantity.parse_status is ParseStatus.AMBIGUOUS
        assert quantity.normalized_value is None
        assert "1.234" in (quantity.parse_note or "") and "1234" in (quantity.parse_note or "")
        warning = next(
            w for w in dataset.extraction.warnings if w.code == "number_format_ambiguous"
        )
        assert warning.count == 1
        assert dataset.extraction.quality is ExtractionQuality.NEEDS_REVIEW

    def test_conflicting_column_evidence(self, boq_profile: DomainProfile) -> None:
        rows = [HEADER, ["1", "a", "1,5", "m"], ["2", "b", "2.5", "m"], ["3", "c", "1.234", "m"]]
        dataset = normalize(workbook(sheet(rows)), boq_profile)
        assert "decimal_separator_conflict" in codes(dataset)
        assert cell(dataset.tables[0], 4, "quantity").parse_status is ParseStatus.AMBIGUOUS


# ---------------------------------------------------------------------------- rows


class TestRows:
    def test_german_lv_rows_sections_and_totals(self, boq_profile: DomainProfile) -> None:
        dataset = normalize(workbook(sheet(GERMAN_LV)), boq_profile)
        table = dataset.tables[0]
        rows = by_source_row(table)
        assert kinds(table) == {
            5: RowKind.SECTION, 6: RowKind.SECTION, 7: RowKind.ITEM, 8: RowKind.TEXT,
            9: RowKind.ITEM, 10: RowKind.SUBTOTAL, 11: RowKind.SECTION, 12: RowKind.ITEM,
            13: RowKind.ITEM, 14: RowKind.ITEM, 15: RowKind.SUBTOTAL, 16: RowKind.SUBTOTAL,
            17: RowKind.GRAND_TOTAL, 18: RowKind.TAX, 19: RowKind.GROSS_TOTAL,
        }  # fmt: skip
        assert rows[5].classification.section_level == 2  # "Titel" pattern level
        assert rows[6].classification.section_level == 3  # nested by code prefix 01 > 01.01
        assert [section_row(table, s) for s in rows[7].section_path] == [5, 6]
        assert section_row(table, rows[10].closes_section_id) == 6
        assert section_row(table, rows[15].closes_section_id) == 11
        assert section_row(table, rows[16].closes_section_id) == 5
        assert rows[17].section_path == [] and rows[17].closes_section_id is None
        assert section_row(table, rows[8].belongs_to_row_id) == 7  # long-text continuation
        assert rows[13].counts_toward_totals is None  # Bedarfsposition: the document does not say
        assert rows[13].classification.totals_rule == "contingency_unspecified"
        assert rows[14].counts_toward_totals is False  # "nur EP" in the total column
        assert rows[14].classification.totals_rule == "marker.rate_only"
        assert rows[12].counts_toward_totals is True
        assert dataset.extraction.quality is ExtractionQuality.OK

    def test_english_boq_rows(self, boq_profile: DomainProfile) -> None:
        table = normalize(workbook(sheet(ENGLISH_BOQ)), boq_profile).tables[0]
        rows = by_source_row(table)
        assert kinds(table)[7] is RowKind.ITEM  # "Section of wall" has values: an item
        assert kinds(table)[9] is RowKind.CARRY_FORWARD
        assert kinds(table)[10] is RowKind.GRAND_TOTAL
        assert kinds(table)[11] is RowKind.TAX
        assert kinds(table)[12] is RowKind.GROSS_TOTAL
        assert section_row(table, rows[5].closes_section_id) == 2
        assert rows[8].counts_toward_totals is False  # "Alternative item"

    def test_subtotal_without_sections_has_unknown_scope(self, boq_profile: DomainProfile) -> None:
        rows = [
            HEADER,
            ["1", "a", "1", "m", "2,00", "2,00"],
            [None, "Summe", None, None, None, "2,00"],
        ]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        subtotal = by_source_row(table)[3]
        assert subtotal.kind is RowKind.SUBTOTAL
        assert subtotal.closes_section_id is None

    def test_code_prefix_sections_and_unclassified_amounts(
        self, boq_profile: DomainProfile
    ) -> None:
        rows = [
            HEADER,
            ["02", "Rohbau", None, None, None, "9,00"],
            ["02.0010", "Mauerwerk", "3", "m2", "3,00", "9,00"],
            [None, "Hinweis", None, None, "5,00", None],
        ]
        dataset = normalize(workbook(sheet(rows)), boq_profile)
        table = dataset.tables[0]
        heading = by_source_row(table)[2]
        assert heading.kind is RowKind.SECTION
        assert heading.classification.rule == "code.section"
        assert "section_amount_on_heading" in codes(dataset)
        assert by_source_row(table)[4].kind is RowKind.ITEM  # a unit price makes it an item
        odd = normalize(
            workbook(
                sheet(
                    [
                        [*HEADER, "Extra"],
                        ["1", "a", "1", "m", "2,00", "2,00"],
                        [None, "x", None, None, None, None, "7"],
                    ]
                )
            ),
            boq_profile,
        )
        assert by_source_row(odd.tables[0])[3].kind is RowKind.TEXT
        warning = next(w for w in odd.extraction.warnings if w.code == "unclassified_amount_row")
        assert warning.needs_review and warning.count == 1

    def test_summary_block_lines(self, boq_profile: DomainProfile) -> None:
        rows = [
            HEADER,
            ["01", "Titel 01 Erdarbeiten"],
            ["01.0010", "Aushub", "2", "m3", "5,00", "10,00"],
            [None, "Summe Titel 01", None, None, None, "10,00"],
            [None, "Zusammenstellung"],
            [None, "Titel 01 Erdarbeiten", None, None, None, "10,00"],
            [None, "Gesamtsumme netto", None, None, None, "10,00"],
        ]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        assert kinds(table)[5] is RowKind.TEXT
        assert by_source_row(table)[5].classification.rule == "pattern.summary_block"
        assert kinds(table)[6] is RowKind.SUMMARY_LINE
        assert kinds(table)[7] is RowKind.GRAND_TOTAL

    def test_item_type_column_and_section_inheritance(self, boq_profile: DomainProfile) -> None:
        rows = [
            [*HEADER, "Positionsart"],
            ["01", "Titel 01 Wahlpositionen", None, None, None, None, None],
            ["01.0010", "Variante A", "1", "St", "5,00", "5,00", None],
            ["02", "Titel 02 Hauptleistung", None, None, None, None, None],
            ["02.0010", "Variante B", "1", "St", "5,00", "5,00", "Wahl"],
            ["02.0020", "Grund", "1", "St", "5,00", "5,00", "G"],
        ]
        table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        rows_by = by_source_row(table)
        inherited = rows_by[3]
        assert inherited.counts_toward_totals is False
        assert section_row(table, inherited.classification.not_counted_above_section_id) == 2
        assert rows_by[5].counts_toward_totals is False
        assert rows_by[5].classification.totals_rule == "type_alternative"
        assert rows_by[6].counts_toward_totals is True

    def test_repeated_page_headers_and_hidden_rows(self, boq_profile: DomainProfile) -> None:
        rows = [
            HEADER,
            ["1", "a", "1", "m", "2,00", "2,00"],
            HEADER,
            ["2", "b", "1", "m", "2,00", "2,00"],
        ]
        dataset = normalize(workbook(sheet(rows, hidden_rows=[4], outline={4: 1})), boq_profile)
        table = dataset.tables[0]
        repeated = by_source_row(table)[3]
        assert repeated.kind is RowKind.TEXT
        assert repeated.classification.rule == "repeated_header"
        assert cell(table, 3, "quantity").parse_status is ParseStatus.NOT_APPLICABLE
        hidden = by_source_row(table)[4]
        assert hidden.source_hidden and hidden.outline_level == 1 and hidden.kind is RowKind.ITEM
        warning = next(w for w in dataset.extraction.warnings if w.code == "hidden_rows_present")
        assert not warning.needs_review and warning.count == 1

    def test_generic_profile_rows_are_items(self, generic_profile: DomainProfile) -> None:
        table = normalize(
            workbook(sheet([["Name", "Value"], ["a", "1"], [], ["b", "2"]])), generic_profile
        ).tables[0]
        assert kinds(table) == {2: RowKind.ITEM, 3: RowKind.BLANK, 4: RowKind.ITEM}
        assert all(r.classification.rule in ("default.item", "blank") for r in table.rows)


# ---------------------------------------------------------------------------- sheets


class TestSheetsAndDecisions:
    def test_hidden_and_empty_sheets(self, boq_profile: DomainProfile) -> None:
        raw = workbook(
            sheet(GERMAN_LV),
            sheet([["OZ", "Menge"], ["1", "2"]], name="Alt", index=1, hidden=True),
            sheet([], name="Leer", index=2),
        )
        dataset = normalize(raw, boq_profile)
        assert [t.name for t in dataset.tables] == ["LV"]
        assert {"hidden_sheet_skipped", "empty_sheet_skipped"} <= set(codes(dataset))
        assert dataset.extraction.quality is ExtractionQuality.OK  # both are informational
        include = TableDecisions(sheet_index=1, include_hidden_sheet=True)
        included = normalize(raw, boq_profile, decisions=SchemaDecisions(tables=[include]))
        assert [t.name for t in included.tables] == ["LV", "Alt"]

    def test_no_table_raises(self, boq_profile: DomainProfile) -> None:
        with pytest.raises(ExtractionError):
            normalize(workbook(sheet([[None, "  "]])), boq_profile)

    def test_reviewer_decisions(self, boq_profile: DomainProfile) -> None:
        decisions = SchemaDecisions(
            tables=[
                TableDecisions(
                    sheet_index=0,
                    header_row_numbers=[4],
                    column_fields={3: None, 99: "quantity"},
                    row_kinds={8: RowKind.ITEM},
                    not_data_rows=[17],
                    counts_toward_totals={13: True, 500: False},
                    section_levels={5: 1},
                    closes_section={16: None},
                    unit_aliases={"Stck": "pcs", "xx": "not_a_unit"},
                )
            ]
        )
        dataset = normalize(workbook(sheet(GERMAN_LV)), boq_profile, decisions=decisions)
        table = dataset.tables[0]
        rows = by_source_row(table)
        assert table.header.method is HeaderMethod.USER
        assert table.column_for_field("quantity") is None
        assert rows[8].kind is RowKind.ITEM and rows[8].classification.rule == "user"
        assert rows[17].excluded and rows[17].kind is RowKind.GRAND_TOTAL
        assert (
            rows[13].counts_toward_totals is True and rows[13].classification.totals_rule == "user"
        )
        assert rows[5].classification.section_level == 1
        assert rows[16].closes_section_id is None
        applied = next(w for w in dataset.extraction.warnings if w.code == "decisions_applied")
        assert not applied.needs_review
        assert "Ignored 3" in applied.message

    def test_declared_structure_and_reviewer_override(self, boq_profile: DomainProfile) -> None:
        rows = [
            HEADER,
            ["01.0010", "Übertrag", None, None, None, "50,00"],
            ["01.0020", "Aushub", "2", "m3", "10,00", "20,00"],
        ]
        guessed = normalize(workbook(sheet(rows)), boq_profile).tables[0]
        assert kinds(guessed)[2] is not RowKind.ITEM  # the text reads like a carry-forward line
        declared = sheet(rows)
        declared.declared = TableDecisions(
            sheet_index=0,
            header_row_numbers=[1],
            row_kinds={2: RowKind.ITEM, 3: RowKind.ITEM},
            counts_toward_totals={3: None},
        )
        table = normalize(workbook(declared), boq_profile).tables[0]
        assert kinds(table) == {2: RowKind.ITEM, 3: RowKind.ITEM}
        assert by_source_row(table)[3].counts_toward_totals is None
        assert by_source_row(table)[3].classification.rule == "declared"
        assert by_source_row(table)[3].classification.totals_rule == "declared"
        reviewer = SchemaDecisions(
            tables=[TableDecisions(sheet_index=0, row_kinds={3: RowKind.TEXT})]
        )
        dataset = normalize(workbook(declared), boq_profile, decisions=reviewer)
        assert kinds(dataset.tables[0]) == {2: RowKind.ITEM, 3: RowKind.TEXT}
        reviewed = by_source_row(dataset.tables[0])
        assert (reviewed[2].classification.rule, reviewed[3].classification.rule) == (
            "declared",
            "user",
        )
        notes = {w.code: w for w in dataset.extraction.warnings}
        assert notes["structure_declared"].message.startswith("Structure declared by the file")
        assert notes["decisions_applied"].message == "Reviewer decisions applied: 1."
        assert not notes["structure_declared"].needs_review

    def test_reviewer_column_field_replaces_the_declared_one(self) -> None:
        declared = TableDecisions(sheet_index=0, column_fields={3: "quantity", 4: "unit"})
        reviewer = TableDecisions(sheet_index=0, column_fields={5: "quantity"})
        merged = reviewer.over(declared)
        assert merged.column_fields == {4: "unit", 5: "quantity"}
        assert reviewer.over(None) is reviewer

    def test_determinism_and_no_mutation(self, boq_profile: DomainProfile) -> None:
        raw = workbook(sheet(GERMAN_LV), sheet(ENGLISH_BOQ, name="BoQ", index=1))
        before = copy.deepcopy(raw)
        first = normalize(raw, boq_profile)
        second = normalize(raw, boq_profile)
        assert first == second
        assert raw == before
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.evaluation
@pytest.mark.performance
def test_twenty_thousand_rows_in_a_few_seconds(boq_profile: DomainProfile) -> None:
    rows: list[list[object]] = [[*HEADER, "Bemerkung", "Art"]]
    for i in range(20_000):
        rows.append(
            [f"01.{i:05d}", f"Position {i}", f"{i % 97},5", "m2", "12,40", "1.234,56", "", "G"]
        )
    raw = workbook(sheet(rows))  # type: ignore[arg-type]
    started = time.perf_counter()
    table = normalize(raw, boq_profile).tables[0]
    elapsed = time.perf_counter() - started
    assert len(table.rows) == 20_000
    assert elapsed < 20, f"normalization took {elapsed:.1f} s"
