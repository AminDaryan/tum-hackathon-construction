"""Upload checks: file names, format sniffing, XLSX container inspection, limit guard."""

from __future__ import annotations

import unicodedata
import zipfile
from pathlib import Path

import pytest

from app.core.config import IngestionLimits
from app.core.errors import (
    ExtractionError,
    FileRejectedError,
    UnsupportedFormatError,
)
from app.ingestion.security import (
    REQUIRED_XLSX_PARTS,
    XLSX_MEDIA_TYPE,
    TableLimitGuard,
    WorkbookCellBudget,
    detect_format,
    inspect_xlsx_container,
    sanitize_filename,
    validate_upload,
)
from app.models.document import DocumentFormat
from tests.support.xlsx_fixtures import (
    OLE2_SIGNATURE,
    rewrite_parts,
    write_encrypted_entry,
    write_hostile_entry_name,
    write_many_entries,
    write_missing_part,
    write_ole2_container,
    write_xlsx,
    write_zip_bomb,
)

OLE_HEADER = OLE2_SIGNATURE + bytes(504)


def _file(tmp_path: Path, data: bytes, name: str = "upload.bin") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _book(tmp_path: Path) -> Path:
    return write_xlsx(tmp_path / "book.xlsx", {"LV": [["Qty", "Rate"], [2, 3.5]]})


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("tender.xlsx", "tender.xlsx"),
            ("../../etc/passwd", "passwd"),
            ("C:\\Users\\me\\Desktop\\LV final.xlsx", "LV final.xlsx"),
            ("dir/sub\\name.csv", "name.csv"),
            ("bad\x00na\x1fme\x7f.csv", "badname.csv"),
            ("line\nbreak\t.csv", "linebreak.csv"),
            ('in<va>l:i"d|n?a*me.csv', "in_va_l_i_d_n_a_me.csv"),
            ("C:drive-relative.csv", "C_drive-relative.csv"),
            ("a;b.csv", "a_b.csv"),  # ';' would end a Content-Disposition parameter
            ('x"; filename=evil.html', "x__ filename=evil.html"),
            ("<>|", "___"),
            ("invoice\u202exslx.csv", "invoicexslx.csv"),  # right-to-left override removed
            ("in\u2066vis\u2069ible\u200b.csv", "invisible.csv"),  # isolates, zero width (Cf)
            ("line\u2028sep\u2029.csv", "linesep.csv"),  # Zl and Zp
            ("lone\ud800surrogate.csv", "lonesurrogate.csv"),  # Cs
            ("  spaced name.csv  ", "spaced name.csv"),
            ("trailing.csv. . ", "trailing.csv"),
            ("..hidden.csv", "hidden.csv"),
            (". .\u00a0lead.csv", "lead.csv"),
            ("Größe ÄÖÜ €.csv", "Größe ÄÖÜ €.csv"),
            ("Gro\u0308sse.csv", "Gr\u00f6sse.csv"),  # decomposed umlaut normalized to NFC
        ],
    )
    def test_cleans_names(self, raw: str, expected: str) -> None:
        assert sanitize_filename(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "dir/", "..", "...", "\x00\x01", "a/."])
    def test_never_empty(self, raw: str | None) -> None:
        assert sanitize_filename(raw) == "upload"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("CON", "_CON"),
            ("con.xlsx", "_con.xlsx"),
            ("Nul.tar.gz", "_Nul.tar.gz"),
            ("aux .csv", "_aux .csv"),  # Windows ignores the space before the dot
            ("COM1.csv", "_COM1.csv"),
            ("lpt9", "_lpt9"),
            ("COM\u00b9.csv", "_COM\u00b9.csv"),  # superscript one is reserved too
            ("prn.", "_prn"),
            ("console.csv", "console.csv"),
            ("COM10.csv", "COM10.csv"),
            ("my con.csv", "my con.csv"),
            ("x.con", "x.con"),
        ],
    )
    def test_reserved_device_names(self, raw: str, expected: str) -> None:
        assert sanitize_filename(raw) == expected

    def test_caps_length_and_keeps_the_extension(self) -> None:
        result = sanitize_filename("a" * 400 + ".xlsx")
        assert len(result) == 255
        assert result.endswith(".xlsx")

    def test_caps_length_without_extension(self) -> None:
        assert sanitize_filename("b" * 400) == "b" * 255

    @pytest.mark.parametrize("char", ["\u00e4", "\u20ac", "\u6f22", "\U0001f600"])  # 2-4 bytes
    def test_caps_utf8_bytes_at_a_character_boundary(self, char: str) -> None:
        result = sanitize_filename(char * 300 + ".xlsx")
        encoded = result.encode("utf-8")
        assert len(encoded) <= 255
        assert len(encoded) > 255 - len(char.encode("utf-8"))  # at most one character less
        assert result.endswith(".xlsx")
        assert set(result.removesuffix(".xlsx")) == {char}

    def test_long_extension_is_cut_with_the_name(self) -> None:
        assert sanitize_filename("n." + "e" * 300) == "n." + "e" * 253

    def test_truncation_does_not_leave_trailing_dots_or_spaces(self) -> None:
        assert sanitize_filename("a" * 253 + " ." + "b" * 40) == "a" * 253

    @pytest.mark.parametrize(
        "raw",
        [
            '../../a\\b/c:d*e?f"g<h>i|j;k.csv',
            "\u202e\x00\ud800\u2028x.csv",
            "CON" + "." * 300,
            "\u00e4" * 200 + "." + "\u20ac" * 10,
        ],
    )
    def test_result_is_always_display_safe(self, raw: str) -> None:
        result = sanitize_filename(raw)
        assert result
        assert not set(result) & set('\\/:*?"<>|;')
        assert all(unicodedata.category(c) not in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in result)
        assert result == unicodedata.normalize("NFC", result)
        assert len(result.encode("utf-8")) <= 255
        assert not result.startswith((".", " "))
        assert not result.endswith((".", " "))


class TestDetectFormat:
    def test_xlsx(self, tmp_path: Path) -> None:
        assert detect_format(_book(tmp_path), "LV.xlsx") is DocumentFormat.XLSX

    @pytest.mark.parametrize("name", ["data.csv", "data.tsv", "data.txt", "DATA.CSV", "x/y.Txt"])
    def test_delimited_text(self, tmp_path: Path, name: str) -> None:
        path = _file(tmp_path, b"a;b\n1;2\n")
        assert detect_format(path, name) is DocumentFormat.CSV

    def test_extension_is_read_from_the_sanitized_name(self, tmp_path: Path) -> None:
        assert detect_format(_book(tmp_path), "C:\\fakepath\\Book1.XLSX") is DocumentFormat.XLSX

    def test_utf16_text_with_byte_order_mark_is_text(self, tmp_path: Path) -> None:
        path = _file(tmp_path, "Menge\tEinheit\n12,5\tm²\n".encode("utf-16"))
        assert detect_format(path, "export.txt") is DocumentFormat.CSV

    def test_utf16_text_with_nul_characters_is_binary(self, tmp_path: Path) -> None:
        path = _file(tmp_path, "a\x00b\n".encode("utf-16"))
        with pytest.raises(UnsupportedFormatError) as excinfo:
            detect_format(path, "export.txt")
        assert excinfo.value.details["detected"] == "binary"

    def test_xlsx_renamed_to_csv(self, tmp_path: Path) -> None:
        with pytest.raises(UnsupportedFormatError) as excinfo:
            detect_format(_book(tmp_path), "prices.csv")
        assert excinfo.value.details == {"extension": ".csv", "detected": "xlsx"}
        assert ".xlsx" in excinfo.value.message

    def test_csv_renamed_to_xlsx(self, tmp_path: Path) -> None:
        with pytest.raises(UnsupportedFormatError) as excinfo:
            detect_format(_file(tmp_path, b"a,b\n1,2\n"), "prices.xlsx")
        assert excinfo.value.details["detected"] == "text"

    @pytest.mark.parametrize(
        ("data", "name", "detected"),
        [
            (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n", "report.csv", "pdf"),
            (OLE_HEADER, "legacy.xlsx", "ole"),
            (OLE_HEADER, "legacy.csv", "ole"),
            (b"PK\x03\x04" + bytes(40), "broken.xlsx", "zip"),
            (b"name;value\nx;\x00\x01\x02\n", "data.csv", "binary"),
        ],
    )
    def test_content_mismatch(self, tmp_path: Path, data: bytes, name: str, detected: str) -> None:
        with pytest.raises(UnsupportedFormatError) as excinfo:
            detect_format(_file(tmp_path, data), name)
        assert excinfo.value.details["detected"] == detected

    @pytest.mark.parametrize("name", ["tender.xlsx", "tender.csv", "tender.txt"])
    def test_ole2_container_is_rejected_before_any_parser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        def no_parser(*args: object, **kwargs: object) -> None:
            raise AssertionError("a parser looked at an OLE2 file")

        monkeypatch.setattr(zipfile, "ZipFile", no_parser)
        with pytest.raises(UnsupportedFormatError) as excinfo:
            detect_format(write_ole2_container(tmp_path / "upload.bin"), name)
        assert excinfo.value.message == (
            "Password-protected workbook or legacy .xls file (not supported)."
        )
        assert excinfo.value.code == "unsupported_format"
        assert isinstance(excinfo.value, FileRejectedError)  # rejected, never stored
        assert excinfo.value.details["detected"] == "ole"

    def test_ole2_container_is_rejected_by_validate_upload(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        with pytest.raises(UnsupportedFormatError, match="Password-protected workbook"):
            validate_upload(_file(tmp_path, OLE_HEADER), "encrypted.xlsx", limits)

    def test_zip_without_workbook_parts_is_not_xlsx(self, tmp_path: Path) -> None:
        path = tmp_path / "other.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "not a workbook")
        with pytest.raises(UnsupportedFormatError) as excinfo:
            detect_format(path, "other.xlsx")
        assert excinfo.value.details["detected"] == "zip"

    def test_only_the_first_64_kib_are_sniffed_for_nul_bytes(self, tmp_path: Path) -> None:
        path = _file(tmp_path, b"a;b\n" * 20_000 + b"\x00")  # NUL at byte 80,000
        assert detect_format(path, "data.csv") is DocumentFormat.CSV

    @pytest.mark.parametrize(
        "name", ["scan.png", "tool.exe", "noextension", "book.xls", "book.xlsm", "a.xlsx.zip"]
    )
    def test_unknown_extensions(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(UnsupportedFormatError) as excinfo:
            detect_format(_file(tmp_path, b"a;b\n"), name)
        assert excinfo.value.code == "unsupported_format"
        assert ".xlsx" in excinfo.value.message  # names the supported types

    def test_empty_file_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(FileRejectedError) as excinfo:
            detect_format(_file(tmp_path, b""), "empty.csv")
        assert excinfo.value.code == "file_rejected"


class TestInspectXlsxContainer:
    def test_clean_workbook(self, tmp_path: Path, limits: IngestionLimits) -> None:
        assert inspect_xlsx_container(_book(tmp_path), limits) == []

    def test_reads_only_the_central_directory(
        self, tmp_path: Path, limits: IngestionLimits, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _book(tmp_path)

        def no_decompression(*args: object, **kwargs: object) -> None:
            raise AssertionError("an entry was opened")

        monkeypatch.setattr(zipfile.ZipFile, "open", no_decompression)
        assert inspect_xlsx_container(book, limits) == []

    def test_too_many_entries(self, tmp_path: Path) -> None:
        book = write_many_entries(tmp_path / "many.xlsx", 10)
        with zipfile.ZipFile(book) as archive:
            entries = len(archive.infolist())
        assert inspect_xlsx_container(book, IngestionLimits(max_zip_entries=entries)) == []
        with pytest.raises(FileRejectedError) as excinfo:
            inspect_xlsx_container(book, IngestionLimits(max_zip_entries=entries - 1))
        assert excinfo.value.details["reason"] == "too_many_entries"

    def test_total_uncompressed_size(self, tmp_path: Path) -> None:
        book = _book(tmp_path)
        with zipfile.ZipFile(book) as archive:
            total = sum(info.file_size for info in archive.infolist())
        assert inspect_xlsx_container(book, IngestionLimits(max_uncompressed_bytes=total)) == []
        with pytest.raises(FileRejectedError) as excinfo:
            inspect_xlsx_container(book, IngestionLimits(max_uncompressed_bytes=total - 1))
        assert excinfo.value.details["reason"] == "uncompressed_size"

    def test_compression_ratio_zip_bomb(self, tmp_path: Path, limits: IngestionLimits) -> None:
        bomb = write_zip_bomb(tmp_path / "bomb.xlsx")
        with pytest.raises(FileRejectedError) as excinfo:
            inspect_xlsx_container(bomb, limits)
        assert excinfo.value.details["reason"] == "compression_ratio"
        assert inspect_xlsx_container(bomb, IngestionLimits(max_compression_ratio=5000)) == []

    def test_encrypted_entry(self, tmp_path: Path, limits: IngestionLimits) -> None:
        with pytest.raises(FileRejectedError) as excinfo:
            inspect_xlsx_container(write_encrypted_entry(tmp_path / "enc.xlsx"), limits)
        assert excinfo.value.details["reason"] == "encrypted_entry"

    @pytest.mark.parametrize(
        "name",
        [
            "../evil.xml",
            "xl/../../evil.xml",
            "/etc/evil.xml",
            "C:/evil.xml",
            "c:evil.xml",
            "xl\\worksheets\\evil.xml",
            "xl/ev\x00il.xml",
        ],
    )
    def test_unsafe_entry_names(self, tmp_path: Path, limits: IngestionLimits, name: str) -> None:
        book = write_hostile_entry_name(tmp_path / "names.xlsx", name)
        with pytest.raises(FileRejectedError) as excinfo:
            inspect_xlsx_container(book, limits)
        assert excinfo.value.details["reason"] == "unsafe_entry_name"

    @pytest.mark.parametrize("part", sorted(REQUIRED_XLSX_PARTS))
    def test_required_parts(self, tmp_path: Path, limits: IngestionLimits, part: str) -> None:
        with pytest.raises(UnsupportedFormatError):
            inspect_xlsx_container(write_missing_part(tmp_path / "part.xlsx", part), limits)

    def test_not_a_zip(self, tmp_path: Path, limits: IngestionLimits) -> None:
        with pytest.raises(UnsupportedFormatError):
            inspect_xlsx_container(_file(tmp_path, b"PK\x03\x04 truncated"), limits)

    def test_macro_project_is_a_warning(self, tmp_path: Path, limits: IngestionLimits) -> None:
        book = rewrite_parts(_book(tmp_path), extra=[("xl/vbaProject.bin", OLE_HEADER)])
        [warning] = inspect_xlsx_container(book, limits)
        assert warning.code == "macro_project_ignored"
        assert warning.count == 1
        assert warning.needs_review is False

    def test_external_links_are_a_warning(self, tmp_path: Path, limits: IngestionLimits) -> None:
        links = [
            ("xl/externalLinks/externalLink1.xml", b"<externalLink/>"),
            ("xl/externalLinks/externalLink2.xml", b"<externalLink/>"),
            ("xl/externalLinks/_rels/externalLink1.xml.rels", b"<Relationships/>"),
        ]
        [warning] = inspect_xlsx_container(rewrite_parts(_book(tmp_path), extra=links), limits)
        assert warning.code == "external_links_ignored"
        assert warning.count == 2


class TestValidateUpload:
    @pytest.mark.parametrize(
        ("name", "media_type"),
        [("a.csv", "text/csv"), ("a.tsv", "text/tab-separated-values"), ("a.TXT", "text/plain")],
    )
    def test_delimited_text(
        self, tmp_path: Path, limits: IngestionLimits, name: str, media_type: str
    ) -> None:
        check = validate_upload(_file(tmp_path, b"a\tb\n"), name, limits)
        assert (check.format, check.media_type, check.warnings) == (
            DocumentFormat.CSV,
            media_type,
            [],
        )

    def test_xlsx_with_container_warnings(self, tmp_path: Path, limits: IngestionLimits) -> None:
        book = rewrite_parts(_book(tmp_path), extra=[("xl/vbaProject.bin", OLE_HEADER)])
        check = validate_upload(book, "tender.xlsx", limits)
        assert check.format is DocumentFormat.XLSX
        assert check.media_type == XLSX_MEDIA_TYPE
        assert [w.code for w in check.warnings] == ["macro_project_ignored"]

    def test_container_checks_run_for_xlsx(self, tmp_path: Path, limits: IngestionLimits) -> None:
        with pytest.raises(FileRejectedError) as excinfo:
            validate_upload(write_zip_bomb(tmp_path / "bomb.xlsx"), "bomb.xlsx", limits)
        assert excinfo.value.code == "file_rejected"

    def test_format_mismatch_is_reported_first(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        with pytest.raises(UnsupportedFormatError):
            validate_upload(_file(tmp_path, b"a;b\n"), "book.xlsx", limits)

    def test_messages_do_not_contain_paths(self, tmp_path: Path, limits: IngestionLimits) -> None:
        failures = [
            (write_zip_bomb(tmp_path / "bomb.xlsx"), "bomb.xlsx"),
            (_file(tmp_path, b"a;b\n"), "book.xlsx"),
            (_file(tmp_path, b"PK\x03\x04 truncated", "broken"), "broken.xlsx"),
        ]
        for path, name in failures:
            with pytest.raises(FileRejectedError) as excinfo:
                validate_upload(path, name, limits)
            assert str(tmp_path) not in excinfo.value.message


class TestTableLimitGuard:
    LIMITS = IngestionLimits(
        max_rows_per_table=2, max_columns_per_table=3, max_cells_per_sheet=4, max_cell_chars=5
    )

    def test_admits_cells_within_the_limits(self) -> None:
        guard = TableLimitGuard("Sheet 'LV'", self.LIMITS)
        for row, column in [(1, 1), (1, 3), (2, 2), (2, 3)]:
            guard.admit(row, column)
        guard.check_text("12345", 1, 1)
        guard.check_text(None, 1, 1)

    @pytest.mark.parametrize(
        ("row", "column", "limit"),
        [(3, 1, "max_rows_per_table"), (1, 4, "max_columns_per_table")],
    )
    def test_extent(self, row: int, column: int, limit: str) -> None:
        with pytest.raises(ExtractionError) as excinfo:
            TableLimitGuard("Sheet 'LV'", self.LIMITS).admit(row, column)
        assert excinfo.value.details["limit"] == limit
        assert "Sheet 'LV'" in excinfo.value.message

    def test_cell_count(self) -> None:
        guard = TableLimitGuard("The file", self.LIMITS)
        for column in (1, 2, 3):
            guard.admit(1, column)
        guard.admit(2, 1)
        with pytest.raises(ExtractionError) as excinfo:
            guard.admit(2, 2)
        assert excinfo.value.details == {"limit": "max_cells_per_sheet", "maximum": 4}

    def test_text_length(self) -> None:
        with pytest.raises(ExtractionError) as excinfo:
            TableLimitGuard("The file", self.LIMITS).check_text("123456", 2, 3)
        assert excinfo.value.details["limit"] == "max_cell_chars"
        assert "row 2, column 3" in excinfo.value.message

    @pytest.mark.parametrize(("row", "column"), [(0, 1), (-3, 1), (1, 0)])
    def test_positions_start_at_one(self, row: int, column: int) -> None:
        with pytest.raises(ExtractionError) as excinfo:
            TableLimitGuard("Sheet 'LV'", self.LIMITS).admit(row, column)
        assert excinfo.value.details == {"reason": "invalid_cell_position"}
        assert "malformed" in excinfo.value.message

    def test_workbook_budget_is_shared_by_all_tables(self) -> None:
        limits = IngestionLimits(max_cells_per_sheet=4, max_cells_per_workbook=6)
        budget = WorkbookCellBudget("The workbook", limits)
        first = TableLimitGuard("Sheet 'A'", limits, budget)
        second = TableLimitGuard("Sheet 'B'", limits, budget)
        for column in (1, 2, 3, 4):  # sheet A at its own limit
            first.admit(1, column)
        second.admit(1, 1)
        second.admit(1, 2)
        with pytest.raises(ExtractionError) as excinfo:
            second.admit(1, 3)  # 3 cells in sheet B, 7 in the workbook
        assert excinfo.value.details == {"limit": "max_cells_per_workbook", "maximum": 6}
        assert excinfo.value.message.startswith("The workbook has more than 6 non-empty cells")

    def test_a_table_without_a_shared_budget_is_its_own_workbook(self) -> None:
        guard = TableLimitGuard("The file", IngestionLimits(max_cells_per_workbook=2))
        guard.admit(1, 1)
        guard.admit(1, 2)
        with pytest.raises(ExtractionError) as excinfo:
            guard.admit(2, 1)
        assert excinfo.value.details["limit"] == "max_cells_per_workbook"
        assert excinfo.value.message.startswith("The file has more than 2")

    def test_the_sheet_limit_is_reported_before_the_workbook_limit(self) -> None:
        limits = IngestionLimits(max_cells_per_sheet=2, max_cells_per_workbook=2)
        guard = TableLimitGuard("Sheet 'A'", limits, WorkbookCellBudget("The workbook", limits))
        guard.admit(1, 1)
        guard.admit(1, 2)
        with pytest.raises(ExtractionError) as excinfo:
            guard.admit(1, 3)
        assert excinfo.value.details["limit"] == "max_cells_per_sheet"
