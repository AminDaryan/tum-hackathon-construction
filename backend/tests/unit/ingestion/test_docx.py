"""Word documents (.docx): upload checks, the body reader, item lists and the adapter."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.core.config import IngestionLimits
from app.core.errors import ExtractionError, FileRejectedError, UnsupportedFormatError
from app.ingestion.base import MergedRange
from app.ingestion.docx.adapter import DocxAdapter
from app.ingestion.docx.document import Paragraph, read_body
from app.ingestion.docx.items import read_item_list
from app.ingestion.gaeb.model import EntryKind, GaebCategory, GaebEntry
from app.ingestion.security import DOCX_MEDIA_TYPE, OLE_WORD_MESSAGE, validate_upload
from app.models.dataset import RowKind
from app.models.document import DocumentFormat
from app.models.source import SourceKind, SourceLocation
from tests.support.docx_builder import (
    cell,
    heading_styles,
    numbering_parts,
    paragraph,
    run,
    table,
    table_bill,
    write_docx,
)

SAMPLE = Path(__file__).resolve().parents[4] / "Sample BoQ Dataset" / "LV-Positionen.docx"


def _paragraphs(*texts: str) -> list[Paragraph]:
    return [Paragraph(number, text) for number, text in enumerate(texts, start=1)]


# --------------------------------------------------------------------------- upload checks
class TestUploadChecks:
    def test_a_word_document_is_accepted(self, tmp_path: Path, limits: IngestionLimits) -> None:
        path = write_docx(tmp_path / "LV.docx", paragraph("Text"))
        check = validate_upload(path, "LV.docx", limits)
        assert (check.format, check.media_type, check.warnings) == (
            DocumentFormat.DOCX,
            DOCX_MEDIA_TYPE,
            [],
        )

    def test_extension_and_content_must_agree(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        word = write_docx(tmp_path / "a.docx", paragraph("Text"))
        with pytest.raises(
            UnsupportedFormatError,
            match=r"is a Word document \(DOCX\)\. Upload it with the extension \.docx",
        ):
            validate_upload(word, "LV.xlsx", limits)
        book = tmp_path / "book.xlsx"
        Workbook().save(book)
        with pytest.raises(
            UnsupportedFormatError,
            match=r"is an XLSX workbook\. Upload it with the extension \.xlsx",
        ):
            validate_upload(book, "LV.docx", limits)

    def test_a_legacy_doc_gets_advice(self, tmp_path: Path, limits: IngestionLimits) -> None:
        path = tmp_path / "LV.doc"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
        with pytest.raises(
            UnsupportedFormatError,
            match=r"Legacy Word \.doc files are not supported\. Save the document as \.docx",
        ):
            validate_upload(path, "LV.doc", limits)

    def test_a_protected_word_document_is_named_as_such(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        path = tmp_path / "LV.docx"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
        with pytest.raises(UnsupportedFormatError) as raised:
            validate_upload(path, "LV.docx", limits)
        assert raised.value.args[0] == OLE_WORD_MESSAGE

    def test_the_container_is_checked_like_a_workbook(self, tmp_path: Path) -> None:
        bomb = write_docx(
            tmp_path / "bomb.docx", paragraph("x"), extra={"word/media/pad.xml": b"0" * 2_000_000}
        )
        with pytest.raises(
            FileRejectedError, match="An entry of the document archive is compressed more than"
        ):
            validate_upload(bomb, "bomb.docx", IngestionLimits(max_compression_ratio=50))
        macro = write_docx(
            tmp_path / "macro.docx", paragraph("x"), extra={"word/vbaProject.bin": b"vba"}
        )
        check = validate_upload(macro, "macro.docx", IngestionLimits())
        assert [w.message for w in check.warnings] == [
            "The document contains a VBA macro project. Macros are ignored and never executed."
        ]

    def test_a_zip_without_the_main_part_is_not_a_word_document(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        path = tmp_path / "x.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
        with pytest.raises(
            UnsupportedFormatError, match="neither a valid XLSX workbook nor a Word document"
        ):
            validate_upload(path, "x.docx", limits)


# --------------------------------------------------------------------------- the body
class TestBody:
    def test_paragraph_text_is_what_word_shows(self, tmp_path: Path) -> None:
        shown = (
            "<w:p>"
            "<w:hyperlink><w:r><w:t>2.3.10</w:t></w:r></w:hyperlink>"
            "<w:r><w:tab/><w:t>Asphalt</w:t></w:r>"
            "<w:del><w:r><w:delText>gelöscht</w:delText></w:r></w:del>"
            '<w:ins><w:r><w:t xml:space="preserve"> neu</w:t></w:r></w:ins>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText>PAGE</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>[m²]</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            "<w:r><w:br/><w:t>zweite Zeile</w:t><w:noBreakHyphen/></w:r>"
            "</w:p>"
        )
        sdt = f"<w:sdt><w:sdtContent>{paragraph('im Steuerelement')}</w:sdtContent></w:sdt>"
        body = read_body(write_docx(tmp_path / "a.docx", shown + paragraph() + sdt))
        assert [p.text for p in body.paragraphs] == [
            "2.3.10\tAsphalt neu[m²]\nzweite Zeile-",
            "",
            "im Steuerelement",
        ]
        assert [p.number for p in body.paragraphs] == [1, 2, 3]

    def test_headings_and_automatic_numbers(self, tmp_path: Path) -> None:
        body_xml = (
            paragraph("Erdarbeiten", style="berschrift1")
            + paragraph("Aushub", style="berschrift2")
            + paragraph("Gliederung", outline=2)
            + paragraph("Normal", style="Standard")
            + paragraph("nummeriert", numbering=(1, 0))
            + paragraph("Aufzählung", numbering=(2, 0))
        )
        path = write_docx(
            tmp_path / "a.docx", body_xml, styles=heading_styles(), numbering=numbering_parts()
        )
        body = read_body(path)
        assert [(p.heading_level, p.auto_numbered) for p in body.paragraphs] == [
            (1, False),
            (2, False),
            (3, False),
            (None, False),
            (None, True),
            (None, False),  # a bullet is not a number
        ]

    def test_tables_keep_words_grid(self, tmp_path: Path) -> None:
        nested = table([["a", "b"], ["c", "d"]])
        rows = [["Titel", "", ""], ["A", "B", "C"], ["x", "y", "z"], ["", "w", "v"]]
        layout = {
            (0, 0): cell("Titel", span=3),
            (2, 0): cell("x", merge="restart"),
            (3, 0): cell("", merge="continue"),
            (3, 2): cell("v", raw=nested),
        }
        # the title row has one cell spanning three columns
        xml = table(rows, cells=layout).replace(cell("") + cell(""), "", 1)
        body = read_body(write_docx(tmp_path / "t.docx", paragraph("vor") + xml))
        [tbl] = body.tables
        assert (tbl.number, tbl.rows, tbl.columns, tbl.nested) == (1, 4, 3, 1)
        assert tbl.cells[(1, 1)] == "Titel"
        assert tbl.cells[(3, 1)] == "x" and (4, 1) not in tbl.cells
        assert tbl.cells[(4, 3)] == "v\na\tb\nc\td"
        assert sorted(tbl.merged, key=lambda m: m.min_row) == [
            MergedRange(1, 1, 1, 3),
            MergedRange(3, 1, 4, 1),
        ]

    def test_damaged_and_hostile_xml_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<w:document")
        with pytest.raises(ExtractionError, match="not well-formed XML"):
            read_body(path)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr(
                "word/document.xml",
                '<!DOCTYPE d [<!ENTITY e "x">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
            )
        with pytest.raises(UnsupportedFormatError, match="DOCTYPE"):
            read_body(path)


# --------------------------------------------------------------------------- item lists
class TestItemList:
    def test_a_list_of_items_with_groups_and_links(self) -> None:
        bill = read_item_list(
            _paragraphs(
                "Allgemein",
                "1.1.10 – Baustelleneinrichtung [psch]",
                "1.1.20 – Baustelleneinrichtung vorhalten [Mt.]",
                "…",
                "",
                "Asphalt",
                "2.3.10 – Straßendecke schneiden [m]",
                "oder",
                "2.3.20 – Asphalt fräsen [m²]",
                "Fräsgut wird Eigentum des AN.",
                "",
                "Abzweigschacht",
            )
        )
        assert bill is not None
        assert (bill.items, bill.sections, bill.notes) == (4, 3, 2)
        first, second, last = bill.document.body
        assert isinstance(first, GaebCategory) and first.label == "Allgemein" and first.line == 1
        item = first.children[0]
        assert isinstance(item, GaebEntry)
        assert (item.number, item.short_text, item.unit.text if item.unit else None, item.line) == (
            "1.1.10",
            "Baustelleneinrichtung",
            "psch",
            2,
        )
        assert isinstance(first.children[2], GaebEntry) and first.children[2].kind is EntryKind.NOTE
        assert isinstance(second, GaebCategory) and second.label == "Asphalt"
        kinds = [(c.kind, c.short_text) for c in second.children if isinstance(c, GaebEntry)]
        assert kinds[1] == (EntryKind.NOTE, "oder")
        milled = second.children[2]
        assert isinstance(milled, GaebEntry) and milled.long_text == "Fräsgut wird Eigentum des AN."
        assert (
            isinstance(last, GaebCategory) and last.label == "Abzweigschacht"
        )  # after an empty line

    def test_tab_separated_columns_carry_quantity_and_prices(self) -> None:
        bill = read_item_list(
            _paragraphs(
                "01.0010\tMauerwerk KS 17,5 cm\tm2\t120,000\t45,50\t5.460,00 €",
                "01.0020\tBeton C25/30\tm3\t18\t165,00\t2.970,00",
                "Pos. 01.0030 Betonstahl [t]",
            )
        )
        assert bill is not None
        wall, _, steel = bill.document.body
        assert isinstance(wall, GaebEntry) and isinstance(steel, GaebEntry)
        assert wall.short_text == "Mauerwerk KS 17,5 cm"
        assert [
            v.text if v else None for v in (wall.qty, wall.unit, wall.unit_price, wall.total)
        ] == [
            "120.000",
            "m2",
            "45.50",
            "5460.00",
        ]
        assert (steel.number, steel.unit.text if steel.unit else None, steel.qty) == (
            "01.0030",
            "t",
            None,
        )

    def test_numbered_groups_and_headings_nest(self) -> None:
        paragraphs = [
            Paragraph(1, "Rohbau", heading_level=1),
            Paragraph(2, "2 Erdarbeiten"),  # a one-part group number that items begin with
            Paragraph(3, "2.3 Asphalt"),
            Paragraph(4, "2.3.10 Straßendecke schneiden [m]"),
            Paragraph(5, "2.3.20 Asphalt fräsen [m²]"),
            Paragraph(6, "3.1 Kanal"),
            Paragraph(7, "3.1.10 Rohr DN 150 [m]"),
        ]
        bill = read_item_list(paragraphs)
        assert bill is not None
        [rohbau] = bill.document.body
        assert isinstance(rohbau, GaebCategory) and rohbau.level == 1
        groups = [
            (c.number, c.label, c.level) for c in rohbau.children if isinstance(c, GaebCategory)
        ]
        # 3.1 leaves 2.3 and 2: it is not inside either
        assert groups == [("2", "Erdarbeiten", 2), ("3.1", "Kanal", 2)]
        erdarbeiten = rohbau.children[0]
        assert isinstance(erdarbeiten, GaebCategory)
        nested = [(c.number, c.level) for c in erdarbeiten.children if isinstance(c, GaebCategory)]
        assert nested == [("2.3", 3)]

    def test_numbered_text_is_not_a_bill(self) -> None:
        conditions = _paragraphs(
            "1.1 Geltungsbereich",
            "Diese Bedingungen gelten für alle Leistungen.",
            "1.2 Abrechnung",
            "1.3 Gewährleistung",
            "2.1 Abnahme [siehe VOB/B]",
        )
        assert read_item_list(conditions) is None


# --------------------------------------------------------------------------- the adapter
class TestAdapter:
    def test_a_table_bill_becomes_a_table_with_words_coordinates(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        book = DocxAdapter().extract(write_docx(tmp_path / "LV.docx", table_bill()), limits)
        [sheet] = book.sheets
        assert (sheet.name, sheet.index, sheet.source_kind, sheet.declared) == (
            "Table 1",
            0,
            SourceKind.WORD,
            None,
        )
        assert sheet.get(2, 1).text == "Pos." and sheet.get(4, 6).text == "5.460,00"
        assert sheet.merged_ranges == [MergedRange(1, 1, 1, 6)]
        assert [w.code for w in book.warnings] == ["docx_tables_read"]
        location = SourceLocation(
            kind=SourceKind.WORD, sheet_name="Table 1", row_number=4, column_number=6
        )
        assert location.describe() == "Word Table 1, row 4, column 6"

    def test_an_item_list_and_a_table_side_by_side(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        body = (
            paragraph("Erdarbeiten")
            + paragraph("1.10 – Oberboden abtragen [m²]")
            + paragraph("1.20 – Boden lösen [m³]")
            + paragraph("1.30 – Boden einbauen [m³]")
            + paragraph("Zusammenstellung")
            + table([["Titel", "Betrag"], ["Erdarbeiten", "1.000,00"]])
        )
        book = DocxAdapter().extract(write_docx(tmp_path / "LV.docx", body), limits)
        assert [(s.name, s.index) for s in book.sheets] == [("LV", 0), ("Table 1", 1)]
        bill = book.sheets[0]
        assert bill.source_kind is SourceKind.WORD
        assert bill.declared is not None and bill.declared.row_kinds[4] is RowKind.ITEM
        assert bill.get(4, 1).text == "1.10" and bill.get(4, 1).line_number == 2
        assert SourceLocation(kind=SourceKind.WORD, line_number=2).describe() == "Word paragraph 2"
        assert [w.code for w in book.warnings] == ["docx_list_read", "docx_tables_read"]
        assert book.details == {"paragraphs": 5, "tables": 1, "item_paragraphs": 3}

    def test_what_is_not_read_is_said(self, tmp_path: Path, limits: IngestionLimits) -> None:
        box = (
            "<w:r><w:pict><w:txbxContent><w:p><w:r><w:t>im Textfeld</w:t></w:r></w:p>"
            "</w:txbxContent></w:pict></w:r>"
        )
        body = (
            paragraph("Mauerwerk [m²]", numbering=(1, 0))
            + paragraph("Beton [m³]", numbering=(1, 0))
            + paragraph("", raw=box)
            + table([["Pos.", "Text"], ["1", "a"]])
        )
        path = write_docx(tmp_path / "LV.docx", body, numbering=numbering_parts())
        book = DocxAdapter().extract(path, limits)
        warnings = {w.code: w for w in book.warnings}
        assert set(warnings) == {
            "docx_tables_read",
            "docx_automatic_numbering",
            "docx_text_boxes_ignored",
        }
        assert warnings["docx_automatic_numbering"].needs_review
        assert "(paragraphs 1, 2)" in warnings["docx_automatic_numbering"].message
        assert book.sheets[0].get(2, 2).text == "a"
        assert "im Textfeld" not in {c.text for c in book.sheets[0].cells.values()}

    def test_a_document_without_a_bill_is_refused(
        self, tmp_path: Path, limits: IngestionLimits
    ) -> None:
        path = write_docx(
            tmp_path / "Brief.docx",
            paragraph("Sehr geehrte Damen und Herren,") + paragraph(run("anbei")),
        )
        with pytest.raises(ExtractionError, match="No table and no list of items was found"):
            DocxAdapter().extract(path, limits)

    def test_the_table_limit_applies(self, tmp_path: Path) -> None:
        body = "".join(table([["a", "b"]]) for _ in range(3))
        with pytest.raises(ExtractionError, match="has 3 tables; the limit is 2"):
            DocxAdapter().extract(
                write_docx(tmp_path / "t.docx", body), IngestionLimits(max_sheets=2)
            )

    @pytest.mark.skipif(not SAMPLE.exists(), reason="the sample dataset is not in this checkout")
    def test_the_sample_list_is_read_whole(self, limits: IngestionLimits) -> None:
        book = DocxAdapter().extract(SAMPLE, limits)
        [sheet] = book.sheets
        assert book.details["item_paragraphs"] == 40
        assert sheet.declared is not None
        items = [r for r, kind in sheet.declared.row_kinds.items() if kind is RowKind.ITEM]
        assert len(items) == 40
        units = {sheet.get(r, 5).text for r in items if sheet.get(r, 5) is not None}
        assert {"psch", "m", "m²", "St."} <= units


def test_the_upload_check_reads_only_the_central_directory(
    tmp_path: Path, limits: IngestionLimits
) -> None:
    # a .docx whose document.xml is not XML still passes the upload check; the adapter refuses it
    path = tmp_path / "x.docx"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "not xml")
    path.write_bytes(buffer.getvalue())
    assert validate_upload(path, "x.docx", limits).format is DocumentFormat.DOCX
    with pytest.raises(ExtractionError):
        DocxAdapter().extract(path, limits)
