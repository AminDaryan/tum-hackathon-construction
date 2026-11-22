"""Delimited-text adapter: encodings, delimiters, records, warnings and limits."""

from __future__ import annotations

import codecs
import csv
from pathlib import Path

import pytest

from app.core.config import IngestionLimits
from app.core.errors import ExtractionError
from app.ingestion import csv_adapter
from app.ingestion.base import RawSheet, RawValueType, RawWorkbook
from app.ingestion.csv_adapter import TABLE_NAME, CsvAdapter, decode_text, detect_delimiter
from app.models.document import DocumentFormat
from app.models.source import SourceKind, SourceLocation

GERMAN_BOQ = (
    "Position;Kurztext;Menge;Einheit;Einheitspreis\n"
    "01.001;Oberboden abtragen, Stärke 30 cm;450;m²;3,80 €\n"
    "01.002;Aushub Baugrube für Fundamente;120;m³;18,50 €\n"
    "01.003;Schüttung aus Kies, verdichtet;85;m³;24,00 €\n"
)


def _extract(
    tmp_path: Path, data: bytes | str, limits: IngestionLimits | None = None
) -> RawWorkbook:
    path = tmp_path / "upload.csv"
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return CsvAdapter().extract(path, limits or IngestionLimits())


def _sheet(tmp_path: Path, data: bytes | str, limits: IngestionLimits | None = None) -> RawSheet:
    [sheet] = _extract(tmp_path, data, limits).sheets
    return sheet


def _rows(sheet: RawSheet) -> list[list[str | None]]:
    """The sheet as a grid of texts; empty cells are ``None``."""
    return [
        [
            cell.text if (cell := sheet.get(row, column)) is not None else None
            for column in range(1, sheet.max_column + 1)
        ]
        for row in range(1, sheet.max_row + 1)
    ]


def _codes(workbook: RawWorkbook) -> list[str]:
    return [w.code for w in workbook.warnings + workbook.sheets[0].warnings]


class TestEncoding:
    def test_utf8(self, tmp_path: Path) -> None:
        workbook = _extract(tmp_path, "Menge;Einheit\n12,5;m²\n")
        assert workbook.details["encoding"] == "utf-8"
        assert workbook.details["encoding_detection"] == "utf8_strict"
        assert _rows(workbook.sheets[0]) == [["Menge", "Einheit"], ["12,5", "m²"]]
        assert _codes(workbook) == []

    def test_utf8_byte_order_mark_is_not_part_of_the_text(self, tmp_path: Path) -> None:
        workbook = _extract(tmp_path, codecs.BOM_UTF8 + "Pos;Text\n1;Größe\n".encode())
        assert (workbook.details["encoding"], workbook.details["encoding_detection"]) == (
            "utf-8-sig",
            "bom",
        )
        assert _rows(workbook.sheets[0]) == [["Pos", "Text"], ["1", "Größe"]]
        assert _codes(workbook) == []

    @pytest.mark.parametrize(
        ("bom", "codec"),
        [(codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")],
    )
    def test_utf16_with_byte_order_mark(self, tmp_path: Path, bom: bytes, codec: str) -> None:
        workbook = _extract(tmp_path, bom + "Menge\tEinheit\n12,5\tm²\n".encode(codec))
        assert workbook.details["encoding"] == codec
        assert workbook.details["encoding_detection"] == "bom"
        assert workbook.details["delimiter"] == "tab"
        assert _rows(workbook.sheets[0]) == [["Menge", "Einheit"], ["12,5", "m²"]]

    def test_windows_1252_is_guessed_and_flagged(self, tmp_path: Path) -> None:
        workbook = _extract(tmp_path, GERMAN_BOQ.encode("cp1252"))
        assert workbook.details["encoding"] == "cp1252"
        assert workbook.details["encoding_detection"] == "charset_normalizer"
        rows = _rows(workbook.sheets[0])
        assert rows[1] == ["01.001", "Oberboden abtragen, Stärke 30 cm", "450", "m²", "3,80 €"]
        assert rows[3][1:4] == ["Schüttung aus Kies, verdichtet", "85", "m³"]
        [warning] = workbook.warnings
        assert warning.code == "encoding_guessed"
        assert warning.needs_review is True
        assert "cp1252" in warning.message

    def test_ties_prefer_the_common_code_page(self) -> None:
        # charset_normalizer rates cp932 (Shift JIS), cp1250 and cp1252 equally for this sample
        # and lists cp932 first, which would turn "m²" into a katakana.
        text = "Menge;Einheit\n12,5;m²\n3;m³\n"
        decoded = decode_text(text.encode("cp1252"))
        assert (decoded.text, decoded.encoding) == (text, "cp1252")

    def test_cyrillic_code_page(self) -> None:
        text = "Наименование;Ед. изм.;Количество\nБетон;м3;12\nАрматура;т;3,5\nКирпич;шт;1200\n"
        decoded = decode_text(text.encode("cp1251"))
        assert (decoded.text, decoded.encoding, decoded.guessed) == (text, "cp1251", True)

    def test_invalid_data_after_a_byte_order_mark_is_guessed(self) -> None:
        decoded = decode_text(codecs.BOM_UTF8 + "Größe;m²\n".encode("cp1252"))
        assert decoded.detection != "bom"
        assert decoded.guessed

    def test_fallbacks_when_nothing_can_be_guessed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(csv_adapter, "_guess_encoding", lambda data: None)
        assert decode_text("Größe;€\n".encode("cp1252")) == csv_adapter.DecodedText(
            "Größe;€\n", "cp1252", "fallback"
        )
        # 0x81 is undefined in cp1252; latin-1 decodes every byte.
        assert decode_text(b"a\x81b") == csv_adapter.DecodedText("a\x81b", "latin-1", "fallback")

    def test_a_guess_must_decode_the_whole_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(csv_adapter, "_guess_encoding", lambda data: "cp1251")
        decoded = decode_text(b"x\x98y")  # 0x98 is undefined in cp1251
        assert (decoded.encoding, decoded.detection) == ("cp1252", "fallback")


class TestDelimiter:
    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("Pos;Menge;Preis\n1;12,5;3,75\n2;1.000,00;7,5\n", "semicolon"),
            ("a,b,c\n1,2,3\n", "comma"),
            ("a\tb\n1\t2\n", "tab"),
            ("a|b\n1|2\n", "pipe"),
            ("a,b,c;d\n1,2,3;4\n", "comma"),  # more fields per record beats the order
            ("a;b,c\n1;2,3\n", "semicolon"),  # a full tie goes to the order
            ('name,text\n1,"x; y; z"\n2,"u; v"\n', "comma"),  # quoted delimiters do not count
            (";;;\n;;;\n", "semicolon"),  # records of empty fields count, blank lines do not
        ],
    )
    def test_detection(self, text: str, name: str) -> None:
        assert detect_delimiter(text).name == name

    def test_splitting_beats_a_consistent_single_column(self) -> None:
        # Every record has one ';'-field, but only ',' splits the records at all.
        choice = detect_delimiter("a,b\n1,2,3\n4\n5,6,7,8\n")
        assert (choice.name, choice.splits) == ("comma", True)

    def test_decimal_commas_stay_in_their_fields(self, tmp_path: Path) -> None:
        sheet = _sheet(tmp_path, "Pos;Menge;Preis\n1;12,5;3,75\n2;1.000,00;7,5\n")
        assert _rows(sheet) == [
            ["Pos", "Menge", "Preis"],
            ["1", "12,5", "3,75"],
            ["2", "1.000,00", "7,5"],
        ]


class TestRecords:
    def test_quotes_resolved_and_line_numbers(self, tmp_path: Path) -> None:
        text = (
            "Pos;Text;Menge\r\n"
            '1;"Beton; C25/30";3\r\n'
            '2;"Zeile eins\r\nZeile zwei";4\r\n'
            '3;"Er sagte ""ja""";5\r\n'
        )
        workbook = _extract(tmp_path, text)
        sheet = workbook.sheets[0]
        assert _rows(sheet) == [
            ["Pos", "Text", "Menge"],
            ["1", "Beton; C25/30", "3"],
            ["2", "Zeile eins\r\nZeile zwei", "4"],
            ["3", 'Er sagte "ja"', "5"],
        ]
        lines = {row: sheet.get(row, 1).line_number for row in range(1, 5)}
        assert lines == {1: 1, 2: 2, 3: 3, 4: 5}
        assert workbook.details["records"] == 4
        assert _codes(workbook) == []

    def test_empty_fields_are_not_stored(self, tmp_path: Path) -> None:
        workbook = _extract(tmp_path, "a;;c\n;;\n1;;3\n")
        sheet = workbook.sheets[0]
        assert set(sheet.cells) == {(1, 1), (1, 3), (3, 1), (3, 3)}
        assert (sheet.max_row, sheet.max_column) == (3, 3)
        assert workbook.details["records"] == 3

    def test_text_is_kept_verbatim(self, tmp_path: Path) -> None:
        sheet = _sheet(tmp_path, 'a; b ;" c "\n007;1e5;=SUM(A1)\n')
        assert _rows(sheet) == [["a", " b ", " c "], ["007", "1e5", "=SUM(A1)"]]
        for cell in sheet.cells.values():
            assert cell.value_type is RawValueType.STRING
            assert (cell.number, cell.boolean, cell.temporal, cell.formula) == (None,) * 4
            assert (cell.number_format, cell.page_number, cell.bbox, cell.confidence) == (None,) * 4

    def test_blank_lines_count_as_records(self, tmp_path: Path) -> None:
        workbook = _extract(tmp_path, "a;b\n\n1;2\n")
        cell = workbook.sheets[0].get(3, 1)
        assert cell is not None
        assert (cell.row, cell.line_number, cell.text) == (3, 3, "1")
        assert workbook.details["records"] == 3
        assert _codes(workbook) == []

    @pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
    def test_line_endings(self, tmp_path: Path, newline: str) -> None:
        sheet = _sheet(tmp_path, f"a;b{newline}1;2{newline}")
        assert _rows(sheet) == [["a", "b"], ["1", "2"]]
        assert [sheet.get(row, 1).line_number for row in (1, 2)] == [1, 2]

    def test_missing_final_newline(self, tmp_path: Path) -> None:
        assert _rows(_sheet(tmp_path, "a;b\n1;2")) == [["a", "b"], ["1", "2"]]

    @pytest.mark.parametrize("text", ["", "\n\n", ";;\n;\n"])
    def test_no_values(self, tmp_path: Path, text: str) -> None:
        workbook = _extract(tmp_path, text)
        sheet = workbook.sheets[0]
        assert (sheet.cells, sheet.max_row, sheet.max_column) == ({}, 0, 0)
        assert _codes(workbook) == []


class TestWarnings:
    def test_ragged_rows(self, tmp_path: Path) -> None:
        sheet = _sheet(tmp_path, "a;b;c\n1;2;3\n4;5\n6;7;8\n9;10;11;12\n")
        [warning] = sheet.warnings
        assert warning.code == "ragged_rows"
        assert warning.count == 2
        assert warning.source == SourceLocation(
            kind=SourceKind.DELIMITED_TEXT, row_number=3, line_number=3
        )
        assert "usual 3" in warning.message
        assert _rows(sheet)[2] == ["4", "5", None, None]  # values stay where they were written
        assert _rows(sheet)[4] == ["9", "10", "11", "12"]

    def test_ragged_location_is_the_physical_line(self, tmp_path: Path) -> None:
        [warning] = _sheet(tmp_path, 'a;b\n1;"x\ny"\n2\n').warnings
        assert warning.source is not None
        assert (warning.source.row_number, warning.source.line_number) == (3, 4)

    def test_single_column_file(self, tmp_path: Path) -> None:
        workbook = _extract(tmp_path, "Beschreibung\nAushub\nBeton\n")
        assert _codes(workbook) == ["single_column_file"]
        assert workbook.details["delimiter"] == "semicolon"
        assert _rows(workbook.sheets[0]) == [["Beschreibung"], ["Aushub"], ["Beton"]]


class TestLimits:
    @pytest.mark.parametrize(
        ("text", "limits", "limit"),
        [
            ("a\nb\nc\n", IngestionLimits(max_rows_per_table=2), "max_rows_per_table"),
            ("a;b;c\n", IngestionLimits(max_columns_per_table=2), "max_columns_per_table"),
            ("a;b\nc;d\ne\n", IngestionLimits(max_cells_per_sheet=4), "max_cells_per_sheet"),
            ("abc;abcdef\n", IngestionLimits(max_cell_chars=5), "max_cell_chars"),
        ],
    )
    def test_exceeded(self, tmp_path: Path, text: str, limits: IngestionLimits, limit: str) -> None:
        with pytest.raises(ExtractionError) as excinfo:
            _extract(tmp_path, text, limits)
        assert excinfo.value.details["limit"] == limit
        assert excinfo.value.message.startswith("The file ")
        assert str(tmp_path) not in excinfo.value.message

    def test_limits_apply_to_values_not_to_blank_records(self, tmp_path: Path) -> None:
        limits = IngestionLimits(max_rows_per_table=2, max_columns_per_table=2)
        sheet = _sheet(tmp_path, "a;b;;\n1;2;;\n\n\n;\n", limits)
        assert (sheet.max_row, sheet.max_column) == (2, 2)

    def test_field_larger_than_the_csv_module_accepts(self, tmp_path: Path) -> None:
        limits = IngestionLimits(max_cell_chars=200_000)
        with pytest.raises(ExtractionError) as excinfo:
            _extract(tmp_path, "a;b\n1;" + "x" * 140_000 + "\n", limits)
        assert "near line 2" in excinfo.value.message
        assert isinstance(excinfo.value.__cause__, csv.Error)
        assert str(tmp_path) not in excinfo.value.message
        assert csv.field_size_limit() == 131_072  # the process-wide limit is left alone


class TestWorkbook:
    def test_structure(self, tmp_path: Path) -> None:
        workbook = _extract(tmp_path, "Pos;Menge\n1;2\n")
        assert (workbook.format, workbook.adapter_id, workbook.adapter_version) == (
            DocumentFormat.CSV,
            "csv.stdlib",
            "1.0.0",
        )
        assert workbook.details == {
            "encoding": "utf-8",
            "encoding_detection": "utf8_strict",
            "delimiter": "semicolon",
            "records": 2,
        }
        [sheet] = workbook.sheets
        assert (sheet.name, sheet.index, sheet.source_kind) == (
            TABLE_NAME,
            0,
            SourceKind.DELIMITED_TEXT,
        )
        assert (sheet.hidden, sheet.merged_ranges, sheet.max_row, sheet.max_column) == (
            False,
            [],
            2,
            2,
        )
        assert list(sheet.cells) == sorted(sheet.cells)


class TestVisibilityAndWorkbookLimit:
    def test_nothing_is_hidden_in_delimited_text(self, tmp_path: Path) -> None:
        sheet = _sheet(tmp_path, "a;b\n1;2\n\n3;4\n")
        assert (sheet.hidden, sheet.hidden_rows, sheet.hidden_columns) == (False, set(), set())
        assert sheet.row_outline_levels == {}

    def test_the_workbook_cell_limit_applies_to_the_file(self, tmp_path: Path) -> None:
        limits = IngestionLimits(max_cells_per_sheet=10, max_cells_per_workbook=3)
        assert len(_sheet(tmp_path, "a;b\nc\n", limits).cells) == 3
        with pytest.raises(ExtractionError) as excinfo:
            _extract(tmp_path, "a;b\nc;d\n", limits)
        assert excinfo.value.details == {"limit": "max_cells_per_workbook", "maximum": 3}
        assert excinfo.value.message.startswith("The file has more than 3 non-empty cells")
