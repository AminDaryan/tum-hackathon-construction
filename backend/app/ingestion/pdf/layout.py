"""The text of a PDF as positioned words and lines: its text layer, read with PDFium
(pypdfium2), or, on a page without a usable text layer, text recognition (OCR).

A page needs OCR when its text layer is empty (a scan) or mostly unreadable (glyphs without a
Unicode mapping decode to replacement or private-use characters). Such pages are read by
:mod:`app.ingestion.pdf.ocr` when OCR is available; otherwise they stay empty and are named in
the extraction warnings. Coordinates are PDF points with the origin at the top left of the
page. OCR words carry Tesseract's confidence (0-1); text-layer words have none (they are not
estimated).

Words are built from runs of characters in the order the PDF draws them, then lines from words
that overlap vertically. Building words in drawing order (not by sorting characters by
position) keeps two texts apart that a printout draws on top of each other, such as body text
running under a shaded column header. Some programs draw one word in several pieces (a number
as ``1`` ``,000``); touching pieces on a line are joined again, numbers with a slightly larger
gap than text, because the space between two words is about as wide as the gap a bold digit
leaves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from app.core.errors import ExtractionError, UnsupportedFormatError
from app.models.source import BoundingBox

if TYPE_CHECKING:
    from app.ingestion.pdf.ocr import TesseractOcr

BOLD_WEIGHT = 600
UNREADABLE_SHARE = 0.3  # a text layer with more unreadable characters than this needs OCR
_HYPHEN_MARKERS = {0xFFFE: "-", 0x02: ""}  # PDFium's markers for a hyphen at a line break
_NUMERIC_PIECE = re.compile(r"^[-\d.,]+$")


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    bold: bool
    size: float
    confidence: float | None = None  # OCR only: Tesseract's confidence, 0-1
    ocr_box: tuple[float, float, float, float] | None = None  # OCR only: box in the image


@dataclass(slots=True)
class Line:
    words: list[Word]
    page: int

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def box(self, words: list[Word] | None = None) -> BoundingBox:
        """The box of ``words`` (default: the whole line) on this line's page."""
        chosen = words or self.words
        return BoundingBox(
            page_number=self.page,
            x0=round(min(w.x0 for w in chosen), 2),
            y0=round(min(w.top for w in chosen), 2),
            x1=round(max(w.x1 for w in chosen), 2),
            y1=round(max(w.bottom for w in chosen), 2),
            unit="pt",
        )


@dataclass(slots=True)
class Page:
    number: int  # 1-based
    lines: list[Line]
    ocr: bool = False  # read by OCR
    needs_ocr: bool = False  # no usable text layer (read by OCR when it is available)
    skew_degrees: float = 0.0  # OCR: the skew removed from the scan
    superscripts: int = 0  # OCR: units whose superscript (m², m³) was read again


def read_pages(path: Path, max_pages: int, ocr: TesseractOcr | None = None) -> list[Page]:
    """Every page's lines; pages without a usable text layer are read by ``ocr`` when it is
    given and available. :class:`ExtractionError` when the file cannot be read or has more
    than ``max_pages`` pages, :class:`UnsupportedFormatError` when it is password-protected."""
    try:
        document = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise UnsupportedFormatError(
                "Password-protected PDF (not supported). Remove the password and upload it again.",
                details={"reason": "pdf_encrypted"},
            ) from None
        raise ExtractionError(
            "The PDF could not be read; it may be damaged.", details={"reason": "pdf_unreadable"}
        ) from None
    try:
        count = len(document)
        if count > max_pages:
            raise ExtractionError(
                f"The PDF has {count:,} pages; at most {max_pages:,} are read.",
                details={"reason": "pdf_too_many_pages", "pages": count},
            )
        pages = [_text_page(document[index], index + 1) for index in range(count)]
        scanned = [page.number for page in pages if page.needs_ocr]
        if scanned and ocr is not None and ocr.status.available:
            for number, read in ocr.read(document, scanned).items():
                page = pages[number - 1]
                page.lines = _lines(read.words, number)
                page.ocr = True
                page.skew_degrees = read.skew_degrees
                page.superscripts = read.superscripts
        return pages
    finally:
        document.close()


def _text_page(page: pdfium.PdfPage, number: int) -> Page:
    textpage = page.get_textpage()
    try:
        words, unreadable, total = _words(textpage, page.get_height())
    finally:
        textpage.close()
        page.close()
    if not words or unreadable > UNREADABLE_SHARE * total:
        return Page(number, [], needs_ocr=True)
    return Page(number, _lines(words, number))


def _unreadable(char: str) -> bool:
    code = ord(char)
    return char == "\ufffd" or 0xE000 <= code <= 0xF8FF or (code < 32 and char not in "\t")


def _words(textpage: pdfium.PdfTextPage, height: float) -> tuple[list[Word], int, int]:
    """The words of a text layer, how many of its characters are unreadable, and how many
    characters it has."""
    unreadable = total = 0
    words: list[Word] = []
    run: list[tuple[str, float, float, float, float, bool, float]] = []

    def flush() -> None:
        text = "".join(c[0] for c in run).strip()
        if text:
            words.append(
                Word(
                    text=text,
                    x0=run[0][1],
                    x1=run[-1][2],
                    top=min(c[3] for c in run),
                    bottom=max(c[4] for c in run),
                    bold=sum(c[5] for c in run) * 2 > len(run),
                    size=max(c[6] for c in run),
                )
            )
        run.clear()

    raw = textpage.raw
    for index in range(textpage.count_chars()):
        code = pdfium_c.FPDFText_GetUnicode(raw, index)
        char = _HYPHEN_MARKERS.get(code, chr(code) if code else "")
        if not char or char.isspace():
            flush()
            continue
        total += 1
        if _unreadable(char):
            unreadable += 1
        left, bottom, right, top = textpage.get_charbox(index)
        size = pdfium_c.FPDFText_GetFontSize(raw, index)
        bold = pdfium_c.FPDFText_GetFontWeight(raw, index) >= BOLD_WEIGHT
        current = (char, left, right, height - top, height - bottom, bold, size)
        if run:
            last = run[-1]
            same_line = abs((last[3] + last[4]) - (current[3] + current[4])) / 2 <= max(
                2.0, 0.35 * size
            )
            gap = left - last[2]
            if not same_line or gap > max(3.0, 0.6 * size) or gap < -max(2.0, 0.3 * size):
                flush()
        run.append(current)
    flush()
    return words, unreadable, total


def _lines(words: list[Word], page: int) -> list[Line]:
    words = sorted(words, key=lambda w: ((w.top + w.bottom) / 2, w.x0))
    groups: list[list[Word]] = []
    bands: list[tuple[float, float]] = []
    for word in words:
        middle = (word.top + word.bottom) / 2
        for k in range(len(groups) - 1, max(-1, len(groups) - 4), -1):
            top, bottom = bands[k]
            if top - 1 <= middle <= bottom + 1:
                groups[k].append(word)
                bands[k] = (min(top, word.top), max(bottom, word.bottom))
                break
        else:
            groups.append([word])
            bands.append((word.top, word.bottom))
    lines = [Line(_join_pieces(sorted(group, key=lambda w: w.x0)), page) for group in groups]
    return sorted(lines, key=lambda line: line.top)


def _join_pieces(words: list[Word]) -> list[Word]:
    joined = [words[0]]
    for word in words[1:]:
        last = joined[-1]
        gap = word.x0 - last.x1
        numeric = _NUMERIC_PIECE.match(last.text) and _NUMERIC_PIECE.match(word.text)
        limit = max(3.0, 0.35 * word.size) if numeric else max(1.5, 0.15 * word.size)
        if -0.5 <= gap <= limit:
            joined[-1] = Word(
                text=last.text + word.text,
                x0=last.x0,
                x1=word.x1,
                top=min(last.top, word.top),
                bottom=max(last.bottom, word.bottom),
                bold=last.bold and word.bold,
                size=max(last.size, word.size),
                confidence=_lowest(last.confidence, word.confidence),
            )
        else:
            joined.append(word)
    return joined


def _lowest(first: float | None, second: float | None) -> float | None:
    if first is None:
        return second
    return first if second is None else min(first, second)
