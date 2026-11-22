"""XLSX adapter: typed values, formulas and cached results, sheet structure, limits and hostile
workbooks."""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

import openpyxl
import openpyxl.xml
import pytest
from openpyxl.chart import BarChart, Reference
from openpyxl.worksheet.formula import ArrayFormula

from app.core.config import IngestionLimits
from app.core.errors import ExtractionError
from app.ingestion import xlsx_adapter
from app.ingestion.base import MergedRange, RawCell, RawSheet, RawValueType, RawWorkbook
from app.ingestion.xlsx_adapter import XlsxAdapter
from app.models.dataset import ExtractionWarning
from app.models.document import DocumentFormat
from app.models.source import SourceKind, SourceLocation
from tests.support.xlsx_fixtures import (
    CachedError,
    CachedNumberText,
    inject_cached_values,
    write_billion_laughs,
    write_encrypted_entry,
    write_external_entity,
    write_formatted_rows,
    write_hostile_entry_name,
    write_missing_part,
    write_padded_sheet,
    write_range_bomb,
    write_shared_formula_bomb,
    write_shared_strings,
    write_sheet_xml,
    write_undefined_number_format,
    write_xlsx,
)

FIRST_SHEET = "xl/worksheets/sheet1.xml"
Builder = Callable[[Path], Path]


def _extract(path: Path, limits: IngestionLimits | None = None) -> RawWorkbook:
    return XlsxAdapter().extract(path, limits or IngestionLimits())


def _only_sheet(path: Path, limits: IngestionLimits | None = None) -> RawSheet:
    [sheet] = _extract(path, limits).sheets
    return sheet


def _cell(sheet: RawSheet, row: int, column: int) -> RawCell:
    cell = sheet.get(row, column)
    assert cell is not None, f"no cell at row {row}, column {column}"
    return cell


def _raw_sheet(tmp_path: Path, rows_xml: str, before_sheet_data: str = "") -> Path:
    """A workbook whose only sheet ("Sheet1") is exactly ``<sheetData>rows_xml</sheetData>``."""
    return write_sheet_xml(tmp_path / "raw.xlsx", rows_xml, before_sheet_data=before_sheet_data)


def _write_with_chartsheet(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    data = workbook.active
    data.title = "Data"
    data.append(["Menge", 3])
    chart_sheet = workbook.create_chartsheet("Chart")
    chart = BarChart()
    chart.add_data(Reference(data, min_col=2, min_row=1, max_row=1))
    chart_sheet.add_chart(chart)
    workbook.create_sheet("After").append(["x"])
    workbook.save(path)
    return path


def _not_a_zip(path: Path) -> Path:
    path.write_bytes(b"not a zip archive")
    return path


def _truncated(path: Path) -> Path:
    data = write_xlsx(path, {"LV": [["x"]]}).read_bytes()
    path.write_bytes(data[: len(data) // 2])
    return path


@pytest.fixture
def no_openpyxl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the workbook reaches openpyxl: the pre-parse scan must reject it."""

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("openpyxl was asked to load a workbook the scan should reject")

    monkeypatch.setattr(openpyxl, "load_workbook", refuse)


class TestValues:
    def test_numbers_and_booleans(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "values.xlsx",
            {
                "LV": [
                    ["Pos", "Menge", "Preis", "Aktiv"],
                    ["01.001", 12, 0.1, True],
                    ["01.002", -3, 1 / 3, False],
                    [None, 1e20, 1.5e-7, None],
                ]
            },
        )
        sheet = _only_sheet(book)
        expected_numbers = {
            (2, 2): (Decimal(12), "12"),
            (2, 3): (Decimal("0.1"), "0.1"),  # not Decimal(0.1) = 0.1000000000000000055...
            (3, 2): (Decimal(-3), "-3"),
            (3, 3): (Decimal("0.333333333333333"), "0.333333333333333"),
            (4, 2): (Decimal("1E+20"), "100000000000000000000"),
            (4, 3): (Decimal("1.5E-7"), "0.00000015"),
        }
        for (row, column), (number, text) in expected_numbers.items():
            cell = _cell(sheet, row, column)
            assert (cell.value_type, cell.number, cell.text) == (RawValueType.NUMBER, number, text)
            assert cell.boolean is None
        true, false = _cell(sheet, 2, 4), _cell(sheet, 3, 4)
        assert (true.value_type, true.boolean, true.text, true.number) == (
            RawValueType.BOOLEAN,
            True,
            "TRUE",
            None,
        )
        assert (false.boolean, false.text) == (False, "FALSE")
        assert (4, 1) not in sheet.cells

    def test_numbers_as_excel_stores_them(self, tmp_path: Path) -> None:
        # Excel writes up to 17 significant digits; openpyxl's writer would round to 16.
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>3.3000000000000003</v></c>'
            '<c r="B1"><v>12345678901234567890</v></c><c r="C1"><v>0.30000000000000004</v></c>'
            '<c r="D1"><v>-0</v></c></row>',
        )
        sheet = _only_sheet(book)
        assert [_cell(sheet, 1, column).number for column in range(1, 5)] == [
            Decimal("3.3"),  # binary noise removed: 15 significant digits, as Excel shows
            Decimal(12345678901234567890),  # integers stay exact
            Decimal("0.3"),
            Decimal(0),
        ]

    def test_text_is_kept_verbatim(self, tmp_path: Path) -> None:
        texts = ["  padded  ", "007", "Größe m²", "Zeile\nzwei", "   "]
        sheet = _only_sheet(write_xlsx(tmp_path / "text.xlsx", {"LV": [texts]}))
        assert [_cell(sheet, 1, c).text for c in range(1, 6)] == texts
        assert {cell.value_type for cell in sheet.cells.values()} == {RawValueType.STRING}

    def test_dates_times_and_durations(self, tmp_path: Path) -> None:
        values = [
            datetime(2026, 1, 15, 8, 30),
            date(2026, 2, 1),
            time(12, 30),
            timedelta(days=1, hours=2),
        ]
        sheet = _only_sheet(write_xlsx(tmp_path / "dates.xlsx", {"Termine": [values]}))
        moment, day, clock, duration = (_cell(sheet, 1, c) for c in range(1, 5))
        assert (moment.value_type, moment.temporal, moment.text) == (
            RawValueType.DATETIME,
            datetime(2026, 1, 15, 8, 30),
            "2026-01-15T08:30:00",
        )
        assert moment.number_format == "yyyy-mm-dd h:mm:ss"
        # Excel stores no date-only type: a date is a datetime at midnight in its date format.
        assert (day.temporal, day.text, day.number_format) == (
            datetime(2026, 2, 1),
            "2026-02-01T00:00:00",
            "yyyy-mm-dd",
        )
        assert (clock.value_type, clock.temporal, clock.text) == (
            RawValueType.DATETIME,
            time(12, 30),
            "12:30:00",
        )
        assert (duration.value_type, duration.text, duration.temporal) == (
            RawValueType.STRING,
            "1 day, 2:00:00",
            None,
        )

    def test_error_values(self, tmp_path: Path) -> None:
        sheet = _only_sheet(
            write_xlsx(tmp_path / "err.xlsx", {"LV": [["#DIV/0!", "#N/A", "#REF!"]]})
        )
        assert [(c.value_type, c.text) for c in sheet.cells.values()] == [
            (RawValueType.ERROR, "#DIV/0!"),
            (RawValueType.ERROR, "#N/A"),
            (RawValueType.ERROR, "#REF!"),
        ]

    def test_cell_types_as_written_by_other_producers(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1" t="inlineStr"><is><t>inline</t></is></c>'
            '<c r="B1" t="d"><v>2026-01-15T00:00:00</v></c><c r="C1" t="b"><v>1</v></c>'
            '<c r="D1" t="e"><v>#VALUE!</v></c><c r="E1"><v>1E-3</v></c>'
            '<c r="F1" t="str"><v>text</v></c><c r="G1"/><c r="H1"><v>1e999</v></c></row>',
        )
        sheet = _only_sheet(book)
        assert {key: (c.value_type, c.text) for key, c in sheet.cells.items()} == {
            (1, 1): (RawValueType.STRING, "inline"),
            (1, 2): (RawValueType.DATETIME, "2026-01-15T00:00:00"),
            (1, 3): (RawValueType.BOOLEAN, "TRUE"),
            (1, 4): (RawValueType.ERROR, "#VALUE!"),
            (1, 5): (RawValueType.NUMBER, "0.001"),
            (1, 6): (RawValueType.STRING, "text"),
            (1, 8): (RawValueType.ERROR, "#NUM!"),  # 1e999 overflows: not a number
        }
        assert _cell(sheet, 1, 8).number is None
        assert [(w.code, w.count, w.needs_review) for w in sheet.warnings] == [
            ("non_finite_number", 1, True)
        ]

    def test_number_formats(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "formats.xlsx",
            {"LV": [[12.5, 3]]},
            number_formats={("LV", "A1"): "#,##0.00 €"},
        )
        sheet = _only_sheet(book)
        assert (_cell(sheet, 1, 1).number_format, _cell(sheet, 1, 2).number_format) == (
            "#,##0.00 €",
            "General",
        )

    def test_spreadsheet_cells_carry_no_text_layout_metadata(self, tmp_path: Path) -> None:
        sheet = _only_sheet(write_xlsx(tmp_path / "meta.xlsx", {"LV": [["a", 1]]}))
        for cell in sheet.cells.values():
            assert (cell.line_number, cell.page_number, cell.bbox, cell.confidence) == (None,) * 4


class TestFormulas:
    def test_cached_results_of_every_type(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "formulas.xlsx",
            {
                "LV": [
                    ["Menge", "Preis", "Betrag", "Label", "Check", "Quote", "Rund"],
                    [2, 3.5, "=A2*B2", '=IF(A2>1,"viele","eins")', "=A2>1", "=A2/0", "=1.1*3"],
                ]
            },
        )
        inject_cached_values(
            book,
            {
                ("LV", "C2"): 7,
                ("LV", "D2"): "viele",
                ("LV", "E2"): True,
                ("LV", "F2"): CachedError("#DIV/0!"),
                ("LV", "G2"): 3.3000000000000003,
            },
        )
        workbook = _extract(book)
        sheet = workbook.sheets[0]
        cells = [_cell(sheet, 2, column) for column in range(3, 8)]
        assert [(c.value_type, c.text, c.formula) for c in cells] == [
            (RawValueType.NUMBER, "7", "=A2*B2"),
            (RawValueType.STRING, "viele", '=IF(A2>1,"viele","eins")'),
            (RawValueType.BOOLEAN, "TRUE", "=A2>1"),
            (RawValueType.ERROR, "#DIV/0!", "=A2/0"),
            (RawValueType.NUMBER, "3.3", "=1.1*3"),
        ]
        assert cells[0].number == Decimal(7)
        assert workbook.details["formula_cells"] == 5
        assert workbook.details["formula_cells_without_cached_value"] == 0

    def test_formula_without_cached_result_is_unavailable(self, tmp_path: Path) -> None:
        book = write_xlsx(tmp_path / "nocache.xlsx", {"LV": [[2, 3, "=A1*B1", "=A1+B1"]]})
        inject_cached_values(book, {("LV", "D1"): 5})
        workbook = _extract(book)
        cell = _cell(workbook.sheets[0], 1, 3)
        assert (cell.value_type, cell.text, cell.number, cell.formula) == (
            RawValueType.UNAVAILABLE,
            None,
            None,
            "=A1*B1",
        )
        assert workbook.details["formula_cells"] == 2
        assert workbook.details["formula_cells_without_cached_value"] == 1

    def test_formula_cells_keep_their_number_format(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "fmt.xlsx",
            {"LV": [[2, "=A1*2", "=A1*3"]]},
            number_formats={("LV", "B1"): "0.00", ("LV", "C1"): "0.0%"},
        )
        inject_cached_values(book, {("LV", "B1"): 4})
        sheet = _only_sheet(book)
        assert (_cell(sheet, 1, 2).number_format, _cell(sheet, 1, 3).number_format) == (
            "0.00",
            "0.0%",
        )

    def test_shared_formulas_are_translated_for_each_cell(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>1</v></c>'
            '<c r="B1"><f t="shared" ref="B1:B3" si="0">A1*2</f><v>2</v></c></row>'
            '<row r="2"><c r="A2"><v>2</v></c><c r="B2"><f t="shared" si="0"/><v>4</v></c></row>'
            '<row r="3"><c r="A3"><v>3</v></c><c r="B3"><f t="shared" si="0"/></c></row>',
        )
        sheet = _only_sheet(book)
        assert [(c.formula, c.text) for c in (_cell(sheet, r, 2) for r in (1, 2, 3))] == [
            ("=A1*2", "2"),
            ("=A2*2", "4"),
            ("=A3*2", None),
        ]

    def test_array_formula(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "array.xlsx", {"LV": [[1, 2, ArrayFormula("C1", "=SUM(A1:B1)")]]}
        )
        assert _cell(_only_sheet(book), 1, 3).formula == "=SUM(A1:B1)"

    def test_data_table_formulas(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="2">'
            '<c r="B2"><f t="dataTable" ref="B2:C3" dt2D="1" dtr="1" r1="A1" r2="A2"/><v>5</v></c>'
            '<c r="D2"><f t="dataTable" ref="D2:D4" dt2D="0" dtr="0" r1="A3"/></c>'
            '<c r="E2"><f t="dataTable" ref="E2:G2" dtr="1" r1="A4"/></c></row>',
        )
        sheet = _only_sheet(book)
        assert [(c.formula, c.text) for c in (_cell(sheet, 2, col) for col in (2, 4, 5))] == [
            ("=TABLE(A1,A2)", "5"),  # two inputs: row input, column input
            ("=TABLE(,A3)", None),  # one column input
            ("=TABLE(A4,)", None),  # one row input
        ]

    def test_cached_results_keep_the_cell_order(self, tmp_path: Path) -> None:
        book = write_xlsx(tmp_path / "order.xlsx", {"LV": [["=1+1", "x"], [1, "=A2*2"]]})
        inject_cached_values(book, {("LV", "A1"): 2, ("LV", "B2"): 2})
        sheet = _only_sheet(book)
        assert list(sheet.cells) == [(1, 1), (1, 2), (2, 1), (2, 2)]

    def test_cached_results_need_a_second_load_only_with_formulas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loads: list[dict[str, Any]] = []
        real_load = openpyxl.load_workbook

        def recording_load(*args: Any, **kwargs: Any) -> Any:
            loads.append(kwargs)
            return real_load(*args, **kwargs)

        monkeypatch.setattr(openpyxl, "load_workbook", recording_load)
        _extract(write_xlsx(tmp_path / "plain.xlsx", {"LV": [[1, 2]]}))
        assert [load["data_only"] for load in loads] == [False]
        loads.clear()
        _extract(write_xlsx(tmp_path / "formula.xlsx", {"LV": [[1, "=A1*2"]]}))
        assert [load["data_only"] for load in loads] == [False, True]
        for load in loads:  # never runs macros, never follows external links
            assert (load["keep_vba"], load["keep_links"]) == (False, False)


class TestSheets:
    def test_workbook_structure(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "sheets.xlsx",
            {
                "Deckblatt": [["Titel"]],
                "LV": [["Pos"], ["01.001"]],
                "Hilfe": [[1]],
                "Geheim": [[2]],
            },
            hidden=["Hilfe"],
            very_hidden=["Geheim"],
        )
        workbook = _extract(book)
        assert (workbook.format, workbook.adapter_id, workbook.adapter_version) == (
            DocumentFormat.XLSX,
            "xlsx.openpyxl",
            "1.1.0",
        )
        assert [(s.name, s.index, s.hidden) for s in workbook.sheets] == [
            ("Deckblatt", 0, False),
            ("LV", 1, False),
            ("Hilfe", 2, True),
            ("Geheim", 3, True),
        ]
        assert {s.source_kind for s in workbook.sheets} == {SourceKind.SPREADSHEET}
        assert workbook.details == {
            "openpyxl_version": openpyxl.__version__,
            "worksheets": 4,
            "formula_cells": 0,
            "formula_cells_without_cached_value": 0,
        }
        assert workbook.warnings == []

    def test_merged_ranges(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "merged.xlsx",
            {"LV": [["Titel"], [], ["Abschnitt", 1], [None, 2]]},
            merged={"LV": ["A1:C1", "A3:A4"]},
        )
        sheet = _only_sheet(book)
        assert sheet.merged_ranges == [MergedRange(1, 1, 1, 3), MergedRange(3, 1, 4, 1)]
        assert set(sheet.cells) == {(1, 1), (3, 1), (3, 2), (4, 2)}  # covered cells hold nothing
        assert _cell(sheet, 1, 1).text == "Titel"

    def test_chart_sheets_are_skipped(self, tmp_path: Path) -> None:
        workbook = _extract(_write_with_chartsheet(tmp_path / "chart.xlsx"))
        assert [(s.name, s.index) for s in workbook.sheets] == [("Data", 0), ("After", 2)]
        [warning] = workbook.warnings
        assert warning.code == "chartsheet_skipped"
        assert warning.source == SourceLocation(
            kind=SourceKind.SPREADSHEET, sheet_name="Chart", sheet_index=1
        )
        assert warning.needs_review is False
        assert workbook.details["worksheets"] == 2

    def test_formatting_does_not_inflate_the_extent(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "styled.xlsx",
            {"LV": [["Pos", "Menge"], ["01.001", 3]]},
            number_formats={("LV", "XFD1048576"): "0.00"},  # one styled, empty cell
        )
        assert openpyxl.load_workbook(book)["LV"].max_row == 1_048_576
        sheet = _only_sheet(book, IngestionLimits(max_rows_per_table=10, max_columns_per_table=5))
        assert (sheet.max_row, sheet.max_column, len(sheet.cells)) == (2, 2, 4)

    def test_empty_sheet(self, tmp_path: Path) -> None:
        workbook = _extract(write_xlsx(tmp_path / "empty.xlsx", {"Leer": [], "LV": [["x"]]}))
        empty = workbook.sheets[0]
        assert (empty.name, empty.cells, empty.max_row, empty.max_column) == ("Leer", {}, 0, 0)

    def test_stored_original_without_extension(self, tmp_path: Path) -> None:
        book = write_xlsx(tmp_path / "book.xlsx", {"LV": [["x"]]})
        stored = tmp_path / ("ab" * 32)
        shutil.copyfile(book, stored)
        assert _cell(_only_sheet(stored), 1, 1).text == "x"


class TestLimits:
    def test_sheet_count(self, tmp_path: Path) -> None:
        book = write_xlsx(tmp_path / "many.xlsx", {"A": [[1]], "B": [[2]], "C": [[3]]})
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_sheets=2))
        assert excinfo.value.details == {"limit": "max_sheets", "maximum": 2}
        assert len(_extract(book, IngestionLimits(max_sheets=3)).sheets) == 3

    @pytest.mark.parametrize(
        ("rows", "limits", "limit"),
        [
            ([["a"], ["b"], ["c"]], IngestionLimits(max_rows_per_table=2), "max_rows_per_table"),
            ([["a", "b", "c"]], IngestionLimits(max_columns_per_table=2), "max_columns_per_table"),
            (
                [["a", "b"], ["c", "d"]],
                IngestionLimits(max_cells_per_sheet=3),
                "max_cells_per_sheet",
            ),
            ([["123456"]], IngestionLimits(max_cell_chars=5), "max_cell_chars"),
            ([[1, "=SUM(A1:A9)"]], IngestionLimits(max_cell_chars=5), "max_cell_chars"),
        ],
    )
    def test_exceeded(
        self, tmp_path: Path, rows: list[list[Any]], limits: IngestionLimits, limit: str
    ) -> None:
        with pytest.raises(ExtractionError) as excinfo:
            _extract(write_xlsx(tmp_path / "limits.xlsx", {"LV": rows}), limits)
        assert excinfo.value.details["limit"] == limit
        assert str(tmp_path) not in excinfo.value.message


class TestHostileWorkbooks:
    @pytest.mark.parametrize("builder", [write_billion_laughs, write_external_entity])
    @pytest.mark.parametrize(
        "part", [FIRST_SHEET, "xl/workbook.xml", "xl/styles.xml", "[Content_Types].xml"]
    )
    @pytest.mark.usefixtures("no_openpyxl")
    def test_document_type_declarations_are_refused(
        self, tmp_path: Path, builder: Callable[[Path, str], Path], part: str
    ) -> None:
        with pytest.raises(ExtractionError) as excinfo:
            _extract(builder(tmp_path / "dtd.xlsx", part))
        assert "document type declaration" in excinfo.value.message
        assert "root:" not in excinfo.value.message  # nothing of /etc/passwd

    @pytest.mark.parametrize("kind", ["merge", "hyperlink", "comment"])
    @pytest.mark.usefixtures("no_openpyxl")
    def test_ranges_covering_the_whole_sheet(self, tmp_path: Path, kind: str) -> None:
        with pytest.raises(ExtractionError) as excinfo:
            _extract(write_range_bomb(tmp_path / "bomb.xlsx", kind))
        assert excinfo.value.details["limit"] == "max_cells_per_sheet"

    @pytest.mark.parametrize("kind", ["merge", "hyperlink", "comment"])
    def test_range_cells_count_against_the_cell_limit(self, tmp_path: Path, kind: str) -> None:
        limits = IngestionLimits(max_cells_per_sheet=100)
        small = write_range_bomb(tmp_path / "small.xlsx", kind, ref="A1:J9")  # 90 cells
        assert _only_sheet(small, limits).get(1, 1) is not None
        large = write_range_bomb(tmp_path / "large.xlsx", kind, ref="A1:J11")  # 110 cells
        with pytest.raises(ExtractionError) as excinfo:
            _extract(large, limits)
        assert excinfo.value.details["limit"] == "max_cells_per_sheet"

    @pytest.mark.parametrize("kind", ["merge", "hyperlink", "comment"])
    def test_range_fixtures_reach_openpyxl_amplification(self, tmp_path: Path, kind: str) -> None:
        # Guards the fixtures: openpyxl creates an object for every covered cell, which is the
        # amplification the scan exists for.
        book = write_range_bomb(tmp_path / "probe.xlsx", kind, ref="A1:J10")
        assert len(openpyxl.load_workbook(book)["Sheet1"]._cells) >= 100

    @pytest.mark.usefixtures("no_openpyxl")
    def test_shared_formula_amplification(self, tmp_path: Path) -> None:
        # About 19,000 characters re-created for each of 20,000 cells: 378 MB of formula text.
        book = write_shared_formula_bomb(
            tmp_path / "f.xlsx", formula_chars=20_000, dependents=20_000
        )
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book)
        assert excinfo.value.details["limit"] == "max_uncompressed_bytes"
        assert "shared formulas" in excinfo.value.message

    def test_shared_formulas_count_against_the_byte_budget(self, tmp_path: Path) -> None:
        book = write_shared_formula_bomb(tmp_path / "f.xlsx", formula_chars=600, dependents=200)
        formula = _cell(_only_sheet(book), 2, 1).formula
        assert formula is not None
        assert formula.startswith("=B2+B3+")  # translated from the master formula in A1
        with zipfile.ZipFile(book) as archive:
            plain_bytes = sum(info.file_size for info in archive.infolist())
        # The parts alone fit; the ~390 characters re-created for each of 200 cells do not.
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_uncompressed_bytes=plain_bytes + 10_000))
        assert excinfo.value.details["limit"] == "max_uncompressed_bytes"

    @pytest.mark.usefixtures("no_openpyxl")
    def test_decompressed_xml_is_capped(self, tmp_path: Path) -> None:
        book = write_padded_sheet(tmp_path / "padded.xlsx", padding_bytes=2_000_000)
        assert book.stat().st_size < 100_000
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_uncompressed_bytes=1_000_000))
        assert excinfo.value.details == {
            "limit": "max_uncompressed_bytes",
            "maximum": 1_000_000,
        }

    @pytest.mark.parametrize(
        "build",
        [
            _not_a_zip,
            _truncated,
            write_encrypted_entry,
            partial(write_hostile_entry_name, name="../evil.xml"),
            partial(write_missing_part, part="xl/workbook.xml"),
        ],
        ids=["not-a-zip", "truncated", "encrypted", "entry-name", "missing-workbook"],
    )
    def test_unreadable_archives(self, tmp_path: Path, build: Builder) -> None:
        path = tmp_path / "private-folder" / "upload.xlsx"
        path.parent.mkdir()
        build(path)
        with pytest.raises(ExtractionError) as excinfo:
            _extract(path)
        assert excinfo.value.code == "extraction_failed"
        assert excinfo.value.message.startswith("The workbook could not be read (")
        assert "private-folder" not in excinfo.value.message

    def test_requires_defused_xml_parsing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(openpyxl.xml, "DEFUSEDXML", False)
        with pytest.raises(RuntimeError, match="defusedxml"):
            XlsxAdapter()


def _warnings(sheet: RawSheet) -> dict[str, ExtractionWarning]:
    """The sheet's warnings by code (each code occurs at most once per sheet)."""
    by_code = {warning.code: warning for warning in sheet.warnings}
    assert len(by_code) == len(sheet.warnings)
    return by_code


class TestNonFiniteNumbers:
    def test_overflowing_values_are_errors_with_a_warning(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>1E999</v></c><c r="B1"><v>-1e999</v></c>'
            '<c r="C1"><v>1.7976931348623157E308</v></c><c r="D1"><v>2</v></c></row>',
        )
        sheet = _only_sheet(book)
        for column in (1, 2):
            cell = _cell(sheet, 1, column)
            assert (cell.value_type, cell.text, cell.number) == (RawValueType.ERROR, "#NUM!", None)
        largest = _cell(sheet, 1, 3)  # finite: still a number, 15 significant digits
        assert (largest.value_type, largest.number) == (
            RawValueType.NUMBER,
            Decimal("1.79769313486232E+308"),
        )
        warning = _warnings(sheet)["non_finite_number"]
        assert (warning.count, warning.needs_review) == (2, True)
        assert warning.source == SourceLocation(
            kind=SourceKind.SPREADSHEET, sheet_name="Sheet1", sheet_index=0
        )
        assert "#NUM!" in warning.message

    def test_non_finite_cached_result_keeps_its_formula(self, tmp_path: Path) -> None:
        book = write_xlsx(tmp_path / "f.xlsx", {"LV": [[1, "=A1*1E308*10", "=A1*2"]]})
        inject_cached_values(book, {("LV", "B1"): CachedNumberText("1E999"), ("LV", "C1"): 2})
        workbook = _extract(book)
        sheet = workbook.sheets[0]
        cell = _cell(sheet, 1, 2)
        assert (cell.value_type, cell.text, cell.number, cell.formula) == (
            RawValueType.ERROR,
            "#NUM!",
            None,
            "=A1*1E308*10",
        )
        assert _warnings(sheet)["non_finite_number"].count == 1
        assert workbook.details["formula_cells_without_cached_value"] == 0

    def test_finite_values_produce_no_warning(self, tmp_path: Path) -> None:
        sheet = _only_sheet(write_xlsx(tmp_path / "ok.xlsx", {"LV": [[1.5, 2, True]]}))
        assert sheet.warnings == []

    def test_integers_stay_exact_and_booleans_are_not_numbers(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>123456789012345678901234567890</v></c>'
            '<c r="B1" t="b"><v>1</v></c><c r="C1" t="b"><v>0</v></c></row>',
        )
        sheet = _only_sheet(book)
        assert _cell(sheet, 1, 1).number == Decimal(123456789012345678901234567890)
        assert [(_cell(sheet, 1, c).value_type, _cell(sheet, 1, c).number) for c in (2, 3)] == [
            (RawValueType.BOOLEAN, None),
            (RawValueType.BOOLEAN, None),
        ]


class TestErrorTyping:
    def test_only_cells_typed_as_errors_are_errors(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1" t="inlineStr"><is><t>#N/A</t></is></c>'
            '<c r="B1" t="e"><v>#N/A</v></c>'
            '<c r="C1" t="str"><f>"#REF!"</f><v>#REF!</v></c>'
            '<c r="D1" t="e"><f>1/0</f><v>#DIV/0!</v></c></row>',
        )
        sheet = _only_sheet(book)
        assert [(_cell(sheet, 1, c).value_type, _cell(sheet, 1, c).text) for c in range(1, 5)] == [
            (RawValueType.STRING, "#N/A"),  # text that looks like an error stays text
            (RawValueType.ERROR, "#N/A"),
            (RawValueType.STRING, "#REF!"),  # a formula returning the text "#REF!"
            (RawValueType.ERROR, "#DIV/0!"),
        ]


class TestNumberFormatLimits:
    LONG = '#,##0.00 "' + "x" * 289 + '"'  # 300 characters

    def test_formats_over_the_limit_are_not_read(self, tmp_path: Path) -> None:
        exact = '0.00 "' + "y" * 248 + '"'  # 255 characters: Excel's limit, still read
        assert (len(self.LONG), len(exact)) == (300, 255)
        book = write_xlsx(
            tmp_path / "formats.xlsx",
            {"LV": [[1.5, 2.5, 3.5, "=A1*2"]]},
            number_formats={
                ("LV", "A1"): self.LONG,
                ("LV", "B1"): self.LONG,
                ("LV", "C1"): exact,
                ("LV", "D1"): self.LONG,
            },
        )
        inject_cached_values(book, {("LV", "D1"): 3})
        sheet = _only_sheet(book)
        assert [_cell(sheet, 1, column).number_format for column in range(1, 5)] == [
            None,
            None,
            exact,
            None,
        ]
        assert _cell(sheet, 1, 1).number == Decimal("1.5")  # the value is unaffected
        warning = _warnings(sheet)["number_format_too_long"]
        assert (warning.count, warning.needs_review) == (3, True)  # the formula counts once
        assert "255" in warning.message

    def test_the_limit_is_configurable(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "f.xlsx", {"LV": [[1.5]]}, number_formats={("LV", "A1"): "0.000"}
        )
        sheet = _only_sheet(book, IngestionLimits(max_number_format_chars=4))
        assert _cell(sheet, 1, 1).number_format is None
        assert _warnings(sheet)["number_format_too_long"].count == 1

    def test_undefined_number_format_reference(self, tmp_path: Path) -> None:
        sheet = _only_sheet(write_undefined_number_format(tmp_path / "styles.xlsx"))
        broken, plain = _cell(sheet, 1, 1), _cell(sheet, 1, 2)
        assert (broken.value_type, broken.number, broken.number_format) == (
            RawValueType.NUMBER,
            Decimal("1.5"),
            None,
        )
        assert plain.number_format == "General"
        warning = _warnings(sheet)["number_format_invalid"]
        assert (warning.count, warning.needs_review) == (1, True)


class TestHiddenRowsAndColumns:
    def test_hidden_rows_columns_and_outline_levels(self, tmp_path: Path) -> None:
        rows = [[f"{column}{row}" for column in "ABCDEF"] for row in range(1, 7)]
        book = write_xlsx(
            tmp_path / "hidden.xlsx",
            {"LV": rows},
            hidden_rows={"LV": [3, 5]},
            hidden_columns={"LV": ["B:D", "F"]},
            outline_levels={"LV": {2: 1, 3: 2, 4: 7}},
        )
        sheet = _only_sheet(book)
        assert sheet.hidden_rows == {3, 5}
        assert sheet.hidden_columns == {2, 3, 4, 6}
        assert sheet.row_outline_levels == {2: 1, 3: 2, 4: 7}
        assert len(sheet.cells) == 36  # hidden content is extracted, never dropped
        assert _cell(sheet, 3, 3).text == "C3"
        assert sheet.warnings == []

    def test_zero_height_rows_and_zero_width_columns_are_hidden(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>1</v></c><c r="B1"><v>2</v></c><c r="C1"><v>3</v></c></row>'
            '<row r="2" ht="0" customHeight="1"><c r="A2"><v>4</v></c></row>'
            '<row r="3" ht="15"><c r="A3"><v>5</v></c></row>',
            before_sheet_data='<cols><col min="2" max="2" width="0" customWidth="1"/>'
            '<col min="3" max="3" width="9"/></cols>',
        )
        sheet = _only_sheet(book)
        assert (sheet.hidden_rows, sheet.hidden_columns) == ({2}, {2})

    def test_ranges_are_clamped_to_the_extent(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>1</v></c><c r="D1"><v>2</v></c></row>'
            '<row r="2" hidden="1"><c r="A2"><v>3</v></c></row>'
            '<row r="9" hidden="1" outlineLevel="3"/><row r="1048576" hidden="1"/>',
            before_sheet_data='<cols><col min="3" max="16384" hidden="1"/>'
            '<col min="2" max="1" hidden="1"/></cols>',  # the second one is reversed
        )
        sheet = _only_sheet(book)
        assert (sheet.max_row, sheet.max_column) == (2, 4)
        assert sheet.hidden_rows == {2}  # rows 9 and 1,048,576 hold nothing
        assert sheet.hidden_columns == {1, 2, 3, 4}
        assert sheet.row_outline_levels == {}

    def test_invalid_outline_levels_are_not_recorded(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1" outlineLevel="9"><c r="A1"><v>1</v></c></row>'
            '<row r="2" outlineLevel="-1"><c r="A2"><v>2</v></c></row>'
            '<row r="3" outlineLevel="2"><c r="A3"><v>3</v></c></row>',
        )
        sheet = _only_sheet(book)
        assert sheet.row_outline_levels == {3: 2}
        assert len(sheet.cells) == 3
        warning = _warnings(sheet)["outline_level_invalid"]
        assert (warning.count, warning.needs_review) == (2, False)

    def test_rows_hidden_by_default_are_reported(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>1</v></c></row>',
            before_sheet_data='<sheetFormatPr defaultRowHeight="15" zeroHeight="1"/>',
        )
        sheet = _only_sheet(book)
        warning = _warnings(sheet)["rows_hidden_by_default"]
        assert (warning.count, warning.needs_review) == (None, True)
        assert _cell(sheet, 1, 1).number == Decimal(1)

    def test_reading_dimensions_creates_no_row_or_column_objects(self, tmp_path: Path) -> None:
        loaded: list[Any] = []
        real_load = openpyxl.load_workbook

        def keep(*args: Any, **kwargs: Any) -> Any:
            workbook = real_load(*args, **kwargs)
            loaded.append(workbook)
            return workbook

        book = write_xlsx(tmp_path / "plain.xlsx", {"LV": [["a", "b"], ["c", "d"]]})
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(openpyxl, "load_workbook", keep)
            _extract(book)
        [workbook] = loaded
        assert (len(workbook["LV"].row_dimensions), len(workbook["LV"].column_dimensions)) == (
            0,
            0,
        )


class TestHiddenSheets:
    def test_hidden_and_very_hidden_sheets_are_extracted_in_full(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "sheets.xlsx",
            {
                "LV": [["Pos", "Betrag"], ["01", "=Kalk!A1"]],
                "Kalk": [[125.5], ["=A1*2"]],
                "Geheim": [["Hinweis an die KI"], [42]],
            },
            hidden=["Kalk"],
            very_hidden=["Geheim"],
        )
        inject_cached_values(book, {("LV", "B2"): 125.5, ("Kalk", "A2"): 251})
        workbook = _extract(book)
        _, kalk, geheim = workbook.sheets
        assert [(s.name, s.index, s.hidden) for s in workbook.sheets] == [
            ("LV", 0, False),
            ("Kalk", 1, True),
            ("Geheim", 2, True),
        ]
        assert _cell(kalk, 2, 1).number == Decimal(251)
        assert _cell(kalk, 2, 1).formula == "=A1*2"
        assert _cell(geheim, 1, 1).text == "Hinweis an die KI"
        assert (geheim.max_row, geheim.max_column) == (2, 1)
        assert workbook.warnings == []  # normalization reports skipped hidden sheets (ADR 0002)
        assert workbook.details["worksheets"] == 3


class TestWorkbookCellLimit:
    BOOK = {"A": [[1, 2], [3, 4]], "B": [[5, 6], [7, 8]], "C": [[9, 10]]}  # 10 cells

    def test_the_limit_applies_across_sheets(self, tmp_path: Path) -> None:
        book = write_xlsx(tmp_path / "book.xlsx", self.BOOK)
        limits = IngestionLimits(max_cells_per_sheet=4, max_cells_per_workbook=10)
        assert sum(len(s.cells) for s in _extract(book, limits).sheets) == 10
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_cells_per_sheet=4, max_cells_per_workbook=9))
        assert excinfo.value.details == {"limit": "max_cells_per_workbook", "maximum": 9}
        assert "per workbook" in excinfo.value.message
        assert str(tmp_path) not in excinfo.value.message

    @pytest.mark.usefixtures("no_openpyxl")
    def test_the_scan_rejects_before_openpyxl(self, tmp_path: Path) -> None:
        book = write_xlsx(tmp_path / "book.xlsx", self.BOOK)
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_cells_per_sheet=4, max_cells_per_workbook=9))
        assert excinfo.value.details["limit"] == "max_cells_per_workbook"

    def test_ranges_in_several_sheets_add_up(self, tmp_path: Path) -> None:
        book = write_xlsx(
            tmp_path / "merged.xlsx",
            {"A": [["x"]], "B": [["y"]]},
            merged={"A": ["A1:E10"], "B": ["A1:E10"]},
        )  # the scan counts 51 objects per sheet: one cell element and 50 covered cells
        limits = IngestionLimits(max_cells_per_sheet=51, max_cells_per_workbook=102)
        assert len(_extract(book, limits).sheets) == 2
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_cells_per_sheet=51, max_cells_per_workbook=101))
        assert excinfo.value.details["limit"] == "max_cells_per_workbook"

    def test_stored_cells_are_counted_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Defence in depth: the limit holds even if the scan were to miss a cell.
        monkeypatch.setattr(xlsx_adapter, "_scan_archive", lambda path, limits: None)
        book = write_xlsx(tmp_path / "book.xlsx", self.BOOK)
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_cells_per_sheet=4, max_cells_per_workbook=9))
        assert excinfo.value.details == {"limit": "max_cells_per_workbook", "maximum": 9}
        assert excinfo.value.message.startswith("The workbook has more than 9 non-empty cells")


class TestMalformedSheets:
    @pytest.mark.parametrize("row", ["0", "-3"])
    def test_cells_at_row_zero_or_below_are_rejected(self, tmp_path: Path, row: str) -> None:
        book = _raw_sheet(tmp_path, f'<row r="{row}"><c><v>1</v></c></row>')
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book)
        assert excinfo.value.details == {"reason": "invalid_cell_position"}

    def test_a_lying_dimension_tag_is_ignored(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>1</v></c></row><row r="2"><c r="B2"><v>2</v></c></row>',
            before_sheet_data='<dimension ref="A1:XFD1048576"/>',
        )
        limits = IngestionLimits(max_rows_per_table=2, max_columns_per_table=2)
        sheet = _only_sheet(book, limits)
        assert (sheet.max_row, sheet.max_column, len(sheet.cells)) == (2, 2, 2)

    def test_cells_in_the_first_and_last_corner(self, tmp_path: Path) -> None:
        book = _raw_sheet(
            tmp_path,
            '<row r="1"><c r="A1"><v>1</v></c></row>'
            '<row r="1048576"><c r="XFD1048576"><v>2</v></c></row>',
        )
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book)
        assert excinfo.value.details["limit"] == "max_rows_per_table"

    @pytest.mark.usefixtures("no_openpyxl")
    def test_formatted_rows_count_as_objects(self, tmp_path: Path) -> None:
        book = write_formatted_rows(tmp_path / "rows.xlsx", 50)
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_cells_per_sheet=40))
        assert excinfo.value.details["limit"] == "max_cells_per_sheet"

    def test_plain_rows_are_not_counted(self, tmp_path: Path) -> None:
        rows = "".join(f'<row r="{n}" spans="1:1"/>' for n in range(1, 51))
        book = _raw_sheet(tmp_path, rows + '<row r="51"><c r="A51"><v>1</v></c></row>')
        assert _only_sheet(book, IngestionLimits(max_cells_per_sheet=40)).max_row == 51

    @pytest.mark.filterwarnings("ignore:Title is more than 31 characters")
    def test_long_sheet_names_are_shortened_in_messages(self, tmp_path: Path) -> None:
        title = "T" * 5000  # Excel allows 31; openpyxl only warns
        book = write_xlsx(tmp_path / "name.xlsx", {title: [["a"], ["b"]]})
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_rows_per_table=1))
        assert excinfo.value.message.startswith(f"Sheet '{'T' * 40}'… has a value in row 2")
        assert len(excinfo.value.message) < 200
        warning = _only_sheet(book).warnings
        assert warning == []


class TestSharedStrings:
    @pytest.mark.usefixtures("no_openpyxl")
    def test_a_shared_string_over_the_cell_limit_is_rejected_by_the_scan(
        self, tmp_path: Path
    ) -> None:
        unused = "<si><t>" + "x" * 101 + "</t></si>"  # referenced by no cell
        book = write_shared_strings(tmp_path / "sst.xlsx", "<si><t>value</t></si>" + unused)
        with pytest.raises(ExtractionError) as excinfo:
            _extract(book, IngestionLimits(max_cell_chars=100))
        assert excinfo.value.details == {"limit": "max_cell_chars", "maximum": 100}
        assert "shared string" in excinfo.value.message

    def test_rich_text_runs_add_up_and_phonetic_runs_do_not_count(self, tmp_path: Path) -> None:
        runs = "<r><t>" + "a" * 50 + "</t></r><r><t>" + "b" * 50 + "</t></r>"
        phonetic = '<rPh sb="0" eb="1"><t>' + "p" * 500 + "</t></rPh>"
        book = write_shared_strings(tmp_path / "rich.xlsx", f"<si>{runs}{phonetic}</si>")
        assert _cell(_only_sheet(book, IngestionLimits(max_cell_chars=100)), 1, 1).text == (
            "a" * 50 + "b" * 50
        )
        longer = write_shared_strings(tmp_path / "longer.xlsx", f"<si>{runs}<r><t>c</t></r></si>")
        with pytest.raises(ExtractionError):
            _extract(longer, IngestionLimits(max_cell_chars=100))
