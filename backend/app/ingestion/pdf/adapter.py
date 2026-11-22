"""Ingestion adapter for printed bills of quantities in PDF.

The PDF's text is read with PDFium, or by text recognition (OCR, Tesseract) on pages without a
usable text layer (:mod:`app.ingestion.pdf.layout`, :mod:`app.ingestion.pdf.ocr`); the bill is
found in its column layout (:mod:`app.ingestion.pdf.bill`), and the result is flattened like a
GAEB bill (:mod:`app.ingestion.gaeb.flatten`): one table whose row kinds, section levels and
column mapping are declared, every cell with its page and box (source kind ``pdf_text``, or
``ocr`` when every bill page was recognised; OCR values carry the engine's confidence).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import IngestionLimits, OcrSettings
from app.ingestion.base import RawWorkbook
from app.ingestion.gaeb.flatten import flatten
from app.ingestion.gaeb.model import EntryKind, GaebCategory, GaebDocument, GaebEntry, XmlValue
from app.ingestion.pdf.bill import BillPages, read_bill
from app.ingestion.pdf.layout import Page, read_pages
from app.ingestion.pdf.ocr import TesseractOcr
from app.models.dataset import ExtractionWarning
from app.models.document import DocumentFormat

logger = logging.getLogger(__name__)

MAX_LISTED = 12
LOW_CONFIDENCE = 0.8  # OCR values below this are counted in the warning


class PdfAdapter:
    adapter_id = "pdf.pdfium"
    adapter_version = "1.1.0"  # 1.1.0: text recognition for scanned pages
    format = DocumentFormat.PDF
    formats = frozenset({DocumentFormat.PDF})

    def __init__(self, ocr: OcrSettings | None = None) -> None:
        self.ocr = TesseractOcr(ocr or OcrSettings())

    def extract(self, path: Path, limits: IngestionLimits) -> RawWorkbook:
        pages = read_pages(path, limits.max_pdf_pages, self.ocr)
        unread = [page.number for page in pages if page.needs_ocr and not page.ocr]
        status = self.ocr.status
        document, bill = read_bill(pages, ocr_missing=status.reason if unread else None)
        sheet, warnings = flatten(document, limits)
        warnings = [*_warnings(bill, pages), *warnings]
        ocr_pages = [page for page in pages if page.ocr]
        if ocr_pages:
            warnings.append(_ocr_warning(ocr_pages, document, status.version, self.ocr))
        if unread:
            # The technical reason belongs in the log and the system status (``/api/health``).
            logger.warning(
                "PDF pages %s not read: OCR is not available (%s)", unread, status.reason
            )
            warnings.append(
                ExtractionWarning(
                    code="pdf_ocr_unavailable",
                    message=(
                        f"No text could be read from pages {_pages_text(unread)} "
                        "(they may be scans); they were not read."
                    ),
                    count=len(unread),
                    needs_review=True,
                )
            )
        missing = _items_without_quantity(document)
        if missing:
            listed = ", ".join(missing[:MAX_LISTED]) + (" …" if len(missing) > MAX_LISTED else "")
            warnings.append(
                ExtractionWarning(
                    code="pdf_items_without_quantity",
                    message=(
                        f"{len(missing)} item(s) have no quantity line the reader could place: "
                        f"{listed}. Check them in the PDF."
                    ),
                    count=len(missing),
                    needs_review=True,
                )
            )
        details: dict[str, str | int | float | bool | None] = {
            "pages": len(pages),
            "bill_pages": _pages_text([page.number for page, _ in bill.pages]),
            "skipped_pages": _pages_text(bill.skipped) or None,
            "project": document.project,
            "currency": document.currency,
        }
        if ocr_pages:
            details["ocr_pages"] = _pages_text([page.number for page in ocr_pages])
            details["ocr_engine"] = status.version
            details["ocr_languages"] = self.ocr.settings.languages
        return RawWorkbook(
            format=self.format,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            sheets=[sheet],
            details=details,
            warnings=warnings,
        )


def _pages_text(numbers: list[int]) -> str:
    """``1-13, 20, 23`` for a sorted list of page numbers."""
    ranges: list[str] = []
    start = previous = None
    for number in [*numbers, None]:
        if number is not None and previous is not None and number == previous + 1:
            previous = number
            continue
        if start is not None:
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    return ", ".join(ranges)


def _warnings(bill: BillPages, pages: list[Page]) -> list[ExtractionWarning]:
    read = [page.number for page, _ in bill.pages]
    skipped = (
        f" Pages without a bill table were skipped (cover, forms, conditions): "
        f"{_pages_text(bill.skipped)}."
        if bill.skipped
        else ""
    )
    return [
        ExtractionWarning(
            code="pdf_layout_read",
            message=(
                f"Read from the PDF by its column layout: {len(read)} of {len(pages)} pages "
                f"({_pages_text(read)}).{skipped} Values are as printed; a finding on a PDF "
                "value asks to be checked against the page."
            ),
            count=len(read),
            needs_review=False,
        )
    ]


def _ocr_warning(
    pages: list[Page], document: GaebDocument, engine: str | None, ocr: TesseractOcr
) -> ExtractionWarning:
    values = [value.confidence for value in _values(document) if value.confidence is not None]
    low = sum(1 for confidence in values if confidence < LOW_CONFIDENCE)
    skew = max((abs(page.skew_degrees) for page in pages), default=0.0)
    superscripts = sum(page.superscripts for page in pages)
    notes = []
    if skew:
        notes.append(f"a skew of up to {skew:.1f}° was straightened")
    if superscripts:
        notes.append(f"{superscripts} unit superscript(s) (m², m³) were read again")
    if low:
        notes.append(f"{low} of {len(values)} values have a confidence below {LOW_CONFIDENCE:.0%}")
    return ExtractionWarning(
        code="pdf_ocr_used",
        message=(
            f"Pages {_pages_text([page.number for page in pages])} have no readable text layer "
            f"and were read by text recognition ({engine or 'Tesseract'}, languages "
            f"{ocr.settings.languages}, {ocr.settings.dpi} dpi)"
            + (f": {'; '.join(notes)}." if notes else ".")
            + " Recognised values may be misread; check them against the page."
        ),
        count=len(pages),
        needs_review=True,
    )


def _values(document: GaebDocument) -> list[XmlValue]:
    out: list[XmlValue] = []

    def walk(nodes: list[GaebCategory | GaebEntry]) -> None:
        for node in nodes:
            if isinstance(node, GaebCategory):
                out.extend(v for v in (node.total,) if v is not None)
                walk(node.children)
            else:
                out.extend(
                    v for v in (node.qty, node.unit, node.unit_price, node.total) if v is not None
                )

    walk(document.body)
    return out


def _items_without_quantity(document: GaebDocument) -> list[str]:
    out: list[str] = []

    def walk(nodes: list[GaebCategory | GaebEntry]) -> None:
        for node in nodes:
            if isinstance(node, GaebCategory):
                walk(node.children)
            elif node.kind is EntryKind.ITEM and node.qty is None:
                out.append(node.number)

    walk(document.body)
    return out
