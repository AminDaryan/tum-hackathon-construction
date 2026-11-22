"""Text recognition (OCR) for PDF pages without a usable text layer, with Tesseract.

A scanned bill has no text layer; some PDFs have one that cannot be decoded (glyphs without a
Unicode mapping come out as replacement or private-use characters). Such pages are rendered by
PDFium to grayscale images and read by the ``tesseract`` command, which reports every word with
its box and a confidence (0-100). Then:

* **Skew.** A scan is rarely straight; 1 degree moves a column by 12 points over a page, enough
  to lose the quantity column, and small glyphs read worse at an angle. A quick reading at
  low resolution gives the skew (the median slope of Tesseract's text lines); the page is then
  rendered rotated back by that angle and read at full resolution. A remaining slight skew is
  removed from the word boxes.
* **Superscripts.** Tesseract's models have no ``²``/``³``: ``m³`` comes out as ``m?``,
  ``m’`` or ``Mo`` (``m²`` sometimes as ``M2``, kept: m2 is m²). For such a unit the small
  glyph after the letters is cropped
  (three slightly different crops), enlarged and read again as a single character limited to
  ``2`` and ``3``; the reads vote, and only a clear winner is used. Otherwise the unit is left
  as read, and the unit check reports it: a unit is never guessed.

The image is written as PGM (no imaging library is needed). Rendering stays in the calling
thread (PDFium is not thread-safe); only the ``tesseract`` processes run in parallel. Nothing
is sent anywhere: Tesseract runs locally. The command and its language data come from the
system (the Docker image installs ``tesseract-ocr`` with German and English).
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from app.core.config import OcrSettings
from app.core.errors import ExtractionError
from app.ingestion.pdf.layout import Word

POINTS_PER_INCH = 72
MIN_SKEW_DEGREES = 0.15  # below this the scan counts as straight
MAX_SKEW_DEGREES = 10.0  # beyond this the estimate is not trusted
SUPERSCRIPT_DPI = 1200
SKEW_DPI = 150  # the quick reading that measures the skew
MAX_AUTO_WORKERS = 8
# Crops of the superscript after the unit's letters (left edge, top and bottom, as shares of
# the word box). Their reads vote: a digit needs a summed confidence of SUPERSCRIPT_VOTES and
# the other digit at most SUPERSCRIPT_MARGIN of that.
_SUPERSCRIPT_CROPS = ((0.62, -0.05, 0.62), (0.55, -0.2, 0.7), (0.66, -0.1, 0.55))
SUPERSCRIPT_VOTES = 1.2
SUPERSCRIPT_MARGIN = 0.25
# Units whose last character may be a superscript Tesseract misread: letters and one or two
# junk characters ("m?", "m’"), and metre units with a letter-like character after them ("Mo",
# "MI" are how m³ comes out of some scans). A unit read with a digit ("m2", "M3") is valid as
# read and never read again: the crop of a full-size digit is not a superscript.
_SUPERSCRIPT_UNIT = re.compile(r"^([A-Za-z]{1,3})[?'’‘`´°*\"^]{1,2}$|^([mM]|[cdk]m)[oOIl|]$")
_SUPERSCRIPTS = {"2": "²", "3": "³"}


@dataclass(frozen=True, slots=True)
class OcrStatus:
    available: bool
    version: str | None = None
    languages: tuple[str, ...] = ()
    reason: str | None = None  # why OCR is not available


@dataclass(slots=True)
class OcrPage:
    words: list[Word]
    skew_degrees: float  # the skew of the scan, removed before reading
    superscripts: int  # units whose superscript was read again
    rotation: float = 0.0  # radians the page was rendered rotated by (to straighten it)


@cache
def tesseract_status(command: str, languages: str) -> OcrStatus:
    """Whether ``command`` runs and has every language of ``languages`` (``deu+eng``)."""
    path = shutil.which(command)
    if path is None:
        return OcrStatus(False, reason=f"the OCR engine '{command}' is not installed")
    try:
        version = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [path, "--version"], capture_output=True, timeout=20, check=True
        ).stdout.decode("utf-8", "replace")
        listed = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [path, "--list-langs"], capture_output=True, timeout=20, check=True
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return OcrStatus(False, reason=f"the OCR engine '{command}' could not be started")
    have = tuple(line.strip() for line in listed.splitlines()[1:] if line.strip())
    missing = [lang for lang in languages.split("+") if lang not in have]
    first = version.splitlines()[0].strip() if version else None
    if missing:
        return OcrStatus(
            False,
            first,
            have,
            reason=f"the OCR language data {', '.join(missing)} is not installed",
        )
    return OcrStatus(True, first, have)


class TesseractOcr:
    """Reads rendered PDF pages with the ``tesseract`` command."""

    def __init__(self, settings: OcrSettings) -> None:
        self.settings = settings

    @property
    def status(self) -> OcrStatus:
        if not self.settings.enabled:
            return OcrStatus(False, reason="OCR is turned off (TWB_OCR__ENABLED)")
        return tesseract_status(self.settings.command, self.settings.languages)

    # ------------------------------------------------------------------ pages
    def read(self, document: pdfium.PdfDocument, numbers: list[int]) -> dict[int, OcrPage]:
        """The words of the 1-based pages ``numbers``, straightened and with superscripts."""
        if len(numbers) > self.settings.max_pages:
            raise ExtractionError(
                f"{len(numbers):,} pages of the PDF need text recognition (OCR); at most "
                f"{self.settings.max_pages:,} are read.",
                details={"reason": "pdf_too_many_ocr_pages", "pages": len(numbers)},
            )
        workers = self.settings.workers or min(MAX_AUTO_WORKERS, os.cpu_count() or 2)
        mode = str(self.settings.page_segmentation)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # 1. the skew of each page, from a quick reading at low resolution
            skews: dict[int, float] = {}
            for batch in _batches(numbers, workers * 2):  # bound the images held in memory
                futures = {
                    number: pool.submit(
                        self._tesseract, _render(document[number - 1], SKEW_DPI), SKEW_DPI, mode
                    )
                    for number in batch
                }
                for number, future in futures.items():
                    skews[number] = _skew(_entries(future.result(), SKEW_DPI))
            # 2. each page rendered straight and read at full resolution
            results: dict[int, OcrPage] = {}
            dpi = self.settings.dpi
            for batch in _batches(numbers, workers * 2):
                futures = {
                    number: pool.submit(
                        self._tesseract,
                        _render(document[number - 1], dpi, rotation=-skews[number]),
                        dpi,
                        mode,
                    )
                    for number in batch
                }
                for number, future in futures.items():
                    words, residual = _words(future.result(), dpi)
                    skew = math.degrees(skews[number]) + residual
                    results[number] = OcrPage(words, skew, 0, rotation=-skews[number])
            self._superscripts(document, results, pool)
        return results

    def _superscripts(
        self,
        document: pdfium.PdfDocument,
        results: dict[int, OcrPage],
        pool: ThreadPoolExecutor,
    ) -> None:
        """Read again the superscript of units Tesseract left as ``m?``: three crops around
        the glyph, each read as one character (``2`` or ``3``); the digit is used only when
        its summed confidence wins clearly, otherwise the unit stays as read."""
        jobs: list[tuple[int, int, list[Future[str]]]] = []
        for number, page in results.items():
            pdf_page = None
            for index, word in enumerate(page.words):
                if not _SUPERSCRIPT_UNIT.match(word.text) or word.ocr_box is None:
                    continue
                if pdf_page is None:
                    pdf_page = document[number - 1]
                x0, top, x1, bottom = word.ocr_box  # where the word is in the image
                width, height = x1 - x0, bottom - top
                futures = []
                for left, upper, lower in _SUPERSCRIPT_CROPS:
                    crop = (x0 + left * width, top + upper * height, x1 + 1, top + lower * height)
                    image = _render(
                        pdf_page, SUPERSCRIPT_DPI, rotation=page.rotation, crop=crop, pad=40
                    )
                    futures.append(pool.submit(self._tesseract, image, SUPERSCRIPT_DPI, "10", "23"))
                jobs.append((number, index, futures))
        for number, index, futures in jobs:
            votes: dict[str, float] = defaultdict(float)
            for future in futures:
                read, _ = _words(future.result(), SUPERSCRIPT_DPI, straighten=False)
                if len(read) == 1 and read[0].text in _SUPERSCRIPTS:
                    votes[read[0].text] += read[0].confidence or 0.0
            if not votes:
                continue
            digit, score = max(votes.items(), key=lambda item: item[1])
            others = sum(votes.values()) - score
            if score < SUPERSCRIPT_VOTES or others > SUPERSCRIPT_MARGIN * score:
                continue
            word = results[number].words[index]
            match = _SUPERSCRIPT_UNIT.match(word.text)
            letters = ((match.group(1) or match.group(2)) if match else "m").lower()
            results[number].words[index] = _replace_text(word, letters + _SUPERSCRIPTS[digit])
            results[number].superscripts += 1

    def _tesseract(self, image: bytes, dpi: int, psm: str, whitelist: str | None = None) -> str:
        arguments = ["-l", self.settings.languages, "--psm", psm, "--dpi", str(dpi)]
        if whitelist:
            arguments += ["-c", f"tessedit_char_whitelist={whitelist}"]
        output = ["tsv"]
        with tempfile.TemporaryDirectory(prefix="twb-ocr-") as folder:
            path = Path(folder) / "page.pgm"
            path.write_bytes(image)
            try:
                completed = subprocess.run(  # noqa: S603 - fixed command and arguments
                    [self.settings.command, str(path), "stdout", *arguments, *output],
                    capture_output=True,
                    timeout=self.settings.page_timeout_seconds,
                    check=True,
                    env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                )
            except subprocess.TimeoutExpired:
                raise ExtractionError(
                    "Text recognition (OCR) took too long on a page.",
                    details={"reason": "pdf_ocr_timeout"},
                ) from None
            except (OSError, subprocess.CalledProcessError):
                raise ExtractionError(
                    "Text recognition (OCR) failed on a page.",
                    details={"reason": "pdf_ocr_failed"},
                ) from None
        return completed.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------- images
def _render(
    page: pdfium.PdfPage,
    dpi: int,
    *,
    rotation: float = 0.0,
    crop: tuple[float, float, float, float] | None = None,
    pad: int = 0,
) -> bytes:
    """``page`` as a grayscale PGM at ``dpi``, rotated by ``rotation`` radians about its centre
    (image coordinates, y down), cut to ``crop`` (x0, top, x1, bottom in points of the rotated
    page) and surrounded by ``pad`` white pixels."""
    scale = dpi / POINTS_PER_INCH
    page_width, page_height = page.get_width(), page.get_height()
    x0, top, x1, bottom = crop if crop is not None else (0.0, 0.0, page_width, page_height)
    width = max(1, round((x1 - x0) * scale))
    height = max(1, round((bottom - top) * scale))
    bitmap = pdfium.PdfBitmap.new_native(width, height, pdfium_c.FPDFBitmap_Gray)
    try:
        bitmap.fill_rect((255, 255, 255, 255), 0, 0, width, height)
        # PDFium first maps the page to points with the origin at the top left (y down); this
        # matrix then scales to pixels, rotates about the page centre and moves the crop to 0, 0.
        cos, sin = math.cos(rotation), math.sin(rotation)
        cx, cy = scale * page_width / 2, scale * page_height / 2
        matrix = pdfium_c.FS_MATRIX(
            scale * cos,
            scale * sin,
            -scale * sin,
            scale * cos,
            cx - cos * cx + sin * cy - scale * x0,
            cy - sin * cx - cos * cy - scale * top,
        )
        clip = pdfium_c.FS_RECTF(0, 0, width, height)
        pdfium_c.FPDF_RenderPageBitmapWithMatrix(
            bitmap.raw, page.raw, matrix, clip, pdfium_c.FPDF_ANNOT
        )
        stride = bitmap.stride
        data = bytes(bitmap.buffer)
    finally:
        bitmap.close()
    rows = [data[y * stride : y * stride + width] for y in range(height)]
    if pad:
        blank = b"\xff" * (width + 2 * pad)
        side = b"\xff" * pad
        rows = [blank] * pad + [side + row + side for row in rows] + [blank] * pad
        width += 2 * pad
        height += 2 * pad
    return b"P5\n%d %d\n255\n" % (width, height) + b"".join(rows)


def _batches(numbers: list[int], size: int) -> list[list[int]]:
    return [numbers[k : k + size] for k in range(0, len(numbers), size)]


# --------------------------------------------------------------------------- words
_Entry = tuple[str, float, float, float, float, float, tuple[str, str, str]]


def _entries(tsv: str, dpi: int) -> list[_Entry]:
    """Tesseract's words (text, left, top, width, height in points, confidence 0-1, line)."""
    scale = POINTS_PER_INCH / dpi
    out: list[_Entry] = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        left, top = int(row["left"]) * scale, int(row["top"]) * scale
        width, height = int(row["width"]) * scale, int(row["height"]) * scale
        confidence = max(0.0, min(100.0, float(row["conf"]))) / 100
        out.append(
            (
                text,
                left,
                top,
                width,
                height,
                confidence,
                (row["block_num"], row["par_num"], row["line_num"]),
            )
        )
    return out


def _words(tsv: str, dpi: int, *, straighten: bool = True) -> tuple[list[Word], float]:
    """Tesseract's words in points, a remaining skew removed from their boxes; and that skew
    (degrees). ``ocr_box`` keeps each word's box in the image, for cropping it again."""
    raw = _entries(tsv, dpi)
    angle = _skew(raw) if straighten else 0.0
    cos, sin = math.cos(angle), math.sin(angle)
    words: list[Word] = []
    for text, left, top, width, height, confidence, _ in raw:
        cx, cy = left + width / 2, top + height / 2
        x, y = (cx * cos + cy * sin, -cx * sin + cy * cos) if angle else (cx, cy)
        words.append(
            Word(
                text=text,
                x0=x - width / 2,
                x1=x + width / 2,
                top=y - height / 2,
                bottom=y + height / 2,
                bold=False,
                size=height,
                confidence=confidence,
                ocr_box=(left, top, left + width, top + height),
            )
        )
    return words, math.degrees(angle)


def _skew(raw: list[_Entry]) -> float:
    """The median baseline slope of Tesseract's text lines (radians), or 0 when straight."""
    lines: dict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for _, left, top, width, height, _, line in raw:
        lines[line].append((left + width / 2, top + height))
    slopes: list[float] = []
    for points in lines.values():
        if len(points) < 3 or max(x for x, _ in points) - min(x for x, _ in points) < 100:
            continue
        mean_x = statistics.fmean(x for x, _ in points)
        mean_y = statistics.fmean(y for _, y in points)
        spread = sum((x - mean_x) ** 2 for x, _ in points)
        if spread:
            slopes.append(sum((x - mean_x) * (y - mean_y) for x, y in points) / spread)
    if not slopes:
        return 0.0
    angle = math.atan(statistics.median(slopes))
    if not math.radians(MIN_SKEW_DEGREES) <= abs(angle) <= math.radians(MAX_SKEW_DEGREES):
        return 0.0
    return angle


def _replace_text(word: Word, text: str) -> Word:
    return Word(
        text,
        word.x0,
        word.x1,
        word.top,
        word.bottom,
        word.bold,
        word.size,
        confidence=word.confidence,
        ocr_box=word.ocr_box,
    )
