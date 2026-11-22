"""Text recognition (OCR) for scanned PDF bills.

Most tests run everywhere: Tesseract's output is parsed from text, rendering is checked on
pixels, and the reader's safety rules run on pages marked as recognised. The tests that run
Tesseract itself are skipped where it is not installed (the Docker image has it); they scan
self-made bills with :func:`tests.support.pdf_builder.rasterize`, straight and skewed, and the
sample dataset's priced bid, whose GAEB twin gives every value."""

from __future__ import annotations

import dataclasses
import math
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from app.core.config import IngestionLimits, OcrSettings
from app.core.errors import ExtractionError
from app.ingestion.gaeb.gaeb90 import read_gaeb90
from app.ingestion.gaeb.model import EntryKind, GaebCategory, GaebEntry
from app.ingestion.pdf.adapter import PdfAdapter
from app.ingestion.pdf.bill import read_bill
from app.ingestion.pdf.layout import Line, Page, _unreadable, read_pages
from app.ingestion.pdf.ocr import TesseractOcr, _render, _skew, _words, tesseract_status
from app.models.dataset import RowKind
from app.models.source import SourceKind
from tests.support.pdf_builder import (
    OZ_X,
    TEXT_X,
    PdfPage,
    bill_header,
    build_pdf,
    item,
    rasterize,
    sample_bill,
)

SAMPLE_DATASET = Path(__file__).parents[4] / "Sample BoQ Dataset"
OCR = OcrSettings(workers=4)
needs_tesseract = pytest.mark.skipif(
    not tesseract_status(OCR.command, OCR.languages).available,
    reason="Tesseract with German and English data is not installed",
)


def _write(tmp_path: Path, content: bytes, name: str = "scan.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _items(nodes: list[GaebCategory | GaebEntry]) -> list[GaebEntry]:
    out: list[GaebEntry] = []
    for node in nodes:
        if isinstance(node, GaebCategory):
            out.extend(_items(node.children))
        elif node.kind is EntryKind.ITEM:
            out.append(node)
    return out


def _as_recognised(pages: list[Page], confidence: float = 0.9) -> list[Page]:
    """Text-layer pages turned into pages 'read by OCR': every word gets a confidence."""
    for page in pages:
        page.ocr = True
        page.lines = [
            Line([dataclasses.replace(w, confidence=confidence) for w in line.words], line.page)
            for line in page.lines
        ]
    return pages


# --------------------------------------------------------------------------- engine output
TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t2480\t3508\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t300\t600\t150\t40\t96.5\t01.10\n"
    "5\t1\t1\t1\t1\t2\t600\t600\t300\t40\t91.0\tAushub\n"
    "5\t1\t1\t1\t2\t1\t1300\t700\t125\t40\t42.0\tm?\n"
)


def test_tesseract_words_are_read_in_points_with_their_confidence() -> None:
    words, skew = _words(TSV, 300)
    assert [w.text for w in words] == ["01.10", "Aushub", "m?"]
    first = words[0]
    assert first.x0 == pytest.approx(72.0) and first.x1 == pytest.approx(108.0)
    assert first.top == pytest.approx(144.0) and first.confidence == pytest.approx(0.965)
    assert first.ocr_box == pytest.approx((72.0, 144.0, 108.0, 153.6))
    assert words[2].confidence == pytest.approx(0.42) and skew == 0.0


def _line_entries(slope: float, lines: int = 6) -> list:
    return [
        (f"w{n}", x, 100 + 30 * row + slope * x, 40, 10, 0.9, ("1", "1", str(row)))
        for row in range(lines)
        for n, x in enumerate(range(50, 550, 100))
    ]


@pytest.mark.parametrize("degrees", [1.5, -0.8, 3.0])
def test_the_skew_is_the_slope_of_the_text_lines(degrees: float) -> None:
    angle = _skew(_line_entries(math.tan(math.radians(degrees))))
    assert math.degrees(angle) == pytest.approx(degrees, abs=0.05)


def test_a_nearly_straight_scan_is_left_as_it_is() -> None:
    assert _skew(_line_entries(math.tan(math.radians(0.05)))) == 0.0
    assert _skew([]) == 0.0


def test_pages_render_rotated_and_cropped() -> None:
    page = pdfium.PdfDocument(sample_bill())[1]

    def ink(image: bytes) -> tuple[int, int, list[tuple[int, int]]]:
        header, data = image.split(b"\n", 3)[1], image.split(b"\n", 3)[3]
        width, height = map(int, header.split())
        dark = [(i % width, i // width) for i, value in enumerate(data) if value < 128]
        return width, height, dark

    width, height, straight = ink(_render(page, 72))
    assert (width, height) == (595, 842)
    assert min(x for x, _ in straight) == pytest.approx(OZ_X, abs=2)
    _, _, turned = ink(_render(page, 72, rotation=math.radians(3)))
    # turned about the centre: the left column moves down, the right column up
    left = [y for x, y in straight if x < 100]
    left_turned = [y for x, y in turned if x < 100]
    assert sum(left_turned) / len(left_turned) > sum(left) / len(left)
    crop_width, crop_height, _ = ink(_render(page, 144, crop=(50, 100, 150, 120), pad=10))
    assert (crop_width, crop_height) == (200 + 20, 40 + 20)


def test_the_engine_status_names_what_is_missing() -> None:
    missing = TesseractOcr(OcrSettings(command="no-such-ocr-engine")).status
    assert not missing.available and "not installed" in (missing.reason or "")
    off = TesseractOcr(OcrSettings(enabled=False)).status
    assert not off.available and "turned off" in (off.reason or "")


def test_unreadable_characters() -> None:
    assert _unreadable("�") and _unreadable("") and _unreadable("\x07")
    assert not _unreadable("ä") and not _unreadable("ß") and not _unreadable("1")


# --------------------------------------------------------------------------- safety rules
def test_two_quantity_lines_in_one_recognised_block_give_no_quantity(tmp_path: Path) -> None:
    """When OCR misses an item number, two items share one block: neither quantity is given to
    the item that remains (it is reported), so no value is assigned to the wrong item."""
    page = bill_header(PdfPage(), 1)
    top = item(page, 160, "01.10.", "Aushub", ["Boden lösen"], "10,000", "m3", "5,00", "50,00")
    # 01.20's number is missing (not recognised): its text and quantity follow 01.10's
    page.text(TEXT_X, top, "Verfüllen", bold=True)
    top = item(page, top, "", "", ["lagenweise"], "8,000", "m3", "4,00", "32,00")
    item(page, top, "01.30.", "Planum", ["herstellen"], "20,000", "m2", "2,00", "40,00")
    pages = read_pages(_write(tmp_path, build_pdf([page]), "bill.pdf"), 10)
    document, _ = read_bill(_as_recognised(pages))
    items = {i.number: i for i in _items(document.body)}
    assert items["01.10"].qty is None and items["01.10"].total is None
    assert items["01.30"].qty.text == "20.000"
    # the same page from a text layer keeps the last quantity line, as validated on PDFs
    document, _ = read_bill(read_pages(_write(tmp_path, build_pdf([page]), "text.pdf"), 10))
    assert {i.number: i for i in _items(document.body)}["01.10"].qty.text == "8.000"


def test_a_number_read_in_pieces_gives_no_amount(tmp_path: Path) -> None:
    page = bill_header(PdfPage(), 1)
    top = item(page, 160, "01.10.", "Aushub", ["Boden"], "10,000", "m3", None, "50,00")
    page.text(400, top - 25, "2.035,")  # OCR split "2.035,930" in two
    page.text(436, top - 25, "930")
    pages = _as_recognised(read_pages(_write(tmp_path, build_pdf([page])), 10))
    document, _ = read_bill(pages)
    [entry] = _items(document.body)
    assert entry.unit_price is None  # neither "930" nor "2.035," is taken
    assert entry.total.text == "50.00" and entry.qty.text == "10.000"


def test_an_unreadable_unit_is_kept_as_read_with_its_quantity(tmp_path: Path) -> None:
    page = bill_header(PdfPage(), 1)
    item(page, 160, "01.10.", "Aushub", ["Boden"], "10,000", "m?", None, None)
    item(page, 220, "01.20.", "Verfüllen", ["Boden"], "8,000", "m3", None, None)
    pages = _as_recognised(read_pages(_write(tmp_path, build_pdf([page])), 10))
    document, _ = read_bill(pages)
    first = _items(document.body)[0]
    assert (first.qty.text, first.unit.text) == ("10.000", "m?")
    assert first.unit.confidence == pytest.approx(0.9)


# --------------------------------------------------------------------------- without OCR
def test_a_scan_without_ocr_is_refused_and_the_reason_is_only_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path, rasterize(sample_bill(), dpi=100))
    with pytest.raises(ExtractionError) as excinfo:
        PdfAdapter(OcrSettings(enabled=False)).extract(path, IngestionLimits())
    assert excinfo.value.details["reason"] == "pdf_no_text"
    assert excinfo.value.message.startswith(
        "No text could be read from this PDF (it may be a scan)."
    )
    assert "turned off" not in excinfo.value.message
    assert "turned off" in caplog.text


def test_scanned_pages_of_a_text_pdf_are_named_when_ocr_is_off(tmp_path: Path) -> None:
    text = pdfium.PdfDocument(sample_bill())
    scanned = pdfium.PdfDocument(rasterize(sample_bill(), dpi=100))
    text.import_pages(scanned, [0])  # a scanned cover sheet appended as page 4
    out = tmp_path / "mixed.pdf"
    text.save(str(out))
    raw = PdfAdapter(OcrSettings(enabled=False)).extract(out, IngestionLimits())
    warning = next(w for w in raw.warnings if w.code == "pdf_ocr_unavailable")
    assert warning.needs_review and "pages 4 " in warning.message
    assert "turned off" not in warning.message


# --------------------------------------------------------------------------- with Tesseract
def _scan_items(tmp_path: Path, content: bytes):
    raw = PdfAdapter(OCR).extract(_write(tmp_path, content), IngestionLimits())
    pages = read_pages(_write(tmp_path, content, "again.pdf"), 10, TesseractOcr(OCR))
    document, _ = read_bill(pages)
    return raw, {entry.number: entry for entry in _items(document.body)}, pages


@needs_tesseract
@pytest.mark.parametrize("skew", [0.0, 1.5])
def test_a_scanned_bill_is_read_value_for_value(tmp_path: Path, skew: float) -> None:
    raw, items, pages = _scan_items(tmp_path, rasterize(sample_bill(), dpi=300, skew_degrees=skew))
    assert list(items) == ["01.10", "01.20", "01.30", "01.40"]
    values = {
        number: (e.qty.text, e.unit.text, e.unit_price.text, e.total.text if e.total else None)
        for number, e in items.items()
    }
    assert values == {
        "01.10": ("120.000", "m2", "4.50", "540.00"),
        "01.20": ("35.500", "m3", "18.20", "646.10"),
        "01.30": ("12.000", "m2", "3.10", "37.20"),
        "01.40": ("1.000", "psch", "250.00", None),
    }
    assert pages[1].ocr and pages[1].skew_degrees == pytest.approx(skew, abs=0.4)
    sheet = raw.sheets[0]
    assert sheet.source_kind is SourceKind.OCR
    numbers = [c for c in sheet.cells.values() if c.number is not None]
    assert numbers and all(c.confidence is not None and 0 < c.confidence <= 1 for c in numbers)
    warning = next(w for w in raw.warnings if w.code == "pdf_ocr_used")
    assert warning.needs_review and "text recognition" in warning.message
    assert raw.details["ocr_pages"] == "1-3"
    kinds = Counter(sheet.declared.row_kinds.values())
    assert kinds[RowKind.ITEM] == 4 and kinds[RowKind.GROSS_TOTAL] == 1


@needs_tesseract
def test_unit_superscripts_are_read_again_or_left_for_review(tmp_path: Path) -> None:
    page = bill_header(PdfPage(), 1)
    top = 160
    expected = {}
    for k, unit in enumerate(["m³", "m²", "m³", "m²", "m³", "m²"]):
        oz = f"01.{k + 1}0."
        top = item(page, top, oz, f"Leistung {k + 1}", ["Text"], f"{k + 1}0,000", unit, None, None)
        expected[oz.rstrip(".")] = unit
    _, items, _ = _scan_items(tmp_path, rasterize(build_pdf([page]), dpi=300))
    assert set(items) == set(expected)
    # a quantity OCR misreads ("AO,000") is missing and reported, never wrong
    quantities = {n: e.qty.text for n, e in items.items() if e.qty is not None}
    assert all(text == f"{int(n[-2])}0.000" for n, text in quantities.items())
    assert len(quantities) >= 5

    def power(unit: str) -> str | None:
        """'2' for m²/m2/M2, '3' for m³/m3; None for a unit left as read (m?, Mo)."""
        found = re.fullmatch(r"[mM]([23²³])", unit)
        return found.group(1).replace("²", "2").replace("³", "3") if found else None

    read = {number: power(entry.unit.text) for number, entry in items.items() if entry.unit}
    wanted = {number: power(unit) for number, unit in expected.items()}
    # a unit is never swapped (m³ read as m² or the other way round) ...
    assert not [n for n, p in read.items() if p is not None and p != wanted[n]]
    # ... and most are read right; the rest stay as read, for the unit check to report
    assert sum(read.get(n) == p for n, p in wanted.items()) >= 3


@needs_tesseract
@pytest.mark.skipif(not SAMPLE_DATASET.is_dir(), reason="sample dataset absent")
def test_a_scan_of_the_sample_bid_matches_its_gaeb_twin(tmp_path: Path) -> None:
    scan = rasterize((SAMPLE_DATASET / "Angebot AN24-0305.pdf").read_bytes(), dpi=300)
    document, _ = read_bill(read_pages(_write(tmp_path, scan), 100, TesseractOcr(OCR)))
    twin_path = SAMPLE_DATASET / "Angebot AN24-0305.D84"

    def key(number: str) -> str:
        return ".".join(p.lstrip("0") or "0" for p in re.split(r"[.\s]+", number.strip(". ")) if p)

    twin = {key(e.number): e for e in _items(read_gaeb90(twin_path, "84").body)}
    read = {key(e.number): e for e in _items(document.body)}
    assert set(read) == set(twin)

    def same(a, b) -> bool:
        return (Decimal(a.text) if a else None) == (Decimal(b.text) if b else None)

    assert all(same(read[k].qty, twin[k].qty) for k in twin)
    assert all(same(read[k].unit_price, twin[k].unit_price) for k in twin)
    assert all(same(read[k].total, twin[k].total) for k in twin)
    assert document.total.text == "988913.89" and document.total_gross.text == "1176807.53"
