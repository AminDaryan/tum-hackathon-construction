"""A GAEB bill of quantities as the file states it: categories, items, notes and totals.

Produced by :func:`app.ingestion.gaeb.reader.read_gaeb` after the file passed the official schema
check, or by :func:`app.ingestion.gaeb.gaeb90.read_gaeb90` from a GAEB 90 file, and turned into a
table by :mod:`app.ingestion.gaeb.flatten`. A printed bill (PDF) is read into the same record by
:mod:`app.ingestion.pdf.bill`. XML values keep their lexical text and line; GAEB 90 values are the
stated digits with their fixed decimals written out (``00000093000`` with three decimals is
``93.000``); PDF values are the printed German numbers as decimal text (``1.655,000`` is
``1655.000``) with their page and box. Nothing is computed or normalized here. Later work
that needs GAEB meaning (joining an X84 bid to its X83 by item ID, writing a bid back) starts
from this record.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from app.models.source import BoundingBox, SourceKind


@dataclass(frozen=True, slots=True)
class XmlValue:
    """The text of one element exactly as written (schema-valid), and its line in the file.
    For GAEB 90, the decimal a fixed-width field states and the line of its record; for a PDF,
    the printed number as decimal text, its page and its box on the page."""

    text: str
    line: int | None
    page: int | None = None
    bbox: BoundingBox | None = None
    confidence: float | None = None  # read by OCR: the engine's confidence, 0-1


class EntryKind(StrEnum):
    ITEM = "item"  # Item: an ordinary position
    MARKUP_ITEM = "markup_item"  # MarkupItem: Zuschlagsposition, a percentage of other items
    NOTE = "note"  # Remark or PerfDescr: text without amounts


@dataclass(slots=True)
class GaebEntry:
    """One element of an item list."""

    kind: EntryKind
    element: str  # local name: Item, MarkupItem, Remark, PerfDescr (GAEB 90: also SubDescr)
    element_id: str | None  # the ID attribute; kept between X83 and X84
    number: str  # ordinal number (OZ): the RNoPart path plus RNoIndex; "" for notes
    line: int | None
    short_text: str = ""
    long_text: str = ""
    flags: tuple[str, ...] = ()  # GAEB flags present, e.g. ("Provis=WithoutTotal",)
    in_alternative_category: bool = False
    qty: XmlValue | None = None
    unit: XmlValue | None = None
    unit_price: XmlValue | None = None
    discount_percent: XmlValue | None = None
    total: XmlValue | None = None
    markup_base: XmlValue | None = None  # MarkupItem: ITMarkup, the amount the markup applies to
    standard_text_key: str | None = None  # STLB-Bau or StLNo key, see reader
    standard_text_catalog: str | None = None
    # Item types without a GAEB DA XML flag (GAEB 90 "Wiederholungsposition"), shown as written.
    extra_types: tuple[str, ...] = ()
    # The file does not say whether the item counts toward the totals (a printed bill whose
    # item is marked "Nur Einheitspreis", or names itself a contingency or alternative).
    total_undecided: bool = False
    page: int | None = None  # PDF: the page and box of the item number
    bbox: BoundingBox | None = None


@dataclass(slots=True)
class GaebCategory:
    """BoQCtgy: a group of items or of further categories (Titel, Los, Abschnitt...)."""

    element_id: str | None
    number: str
    label: str
    line: int | None
    level: int  # 1 = top level
    alternative: bool = False  # ALNBSerNo > 0: an alternative group of categories
    children: list[GaebCategory | GaebEntry] = field(default_factory=list)
    total: XmlValue | None = None  # Totals/Total: sum before the category's own discount
    discount_percent: XmlValue | None = None
    discount_amount: XmlValue | None = None
    total_after_discount: XmlValue | None = None
    total_lump_sum: XmlValue | None = None  # TotalLSUM: the category priced as a lump sum
    page: int | None = None  # PDF: the page and box of the category number
    bbox: BoundingBox | None = None


GAEB90_VERSION = "90"
PDF_VERSION = "pdf"  # a printed bill read from a PDF's text layer
DOCX_VERSION = "docx"  # a bill written in a Word document as a list of item paragraphs


@dataclass(slots=True)
class GaebDocument:
    version: str  # "3.3", GAEB90_VERSION, PDF_VERSION or DOCX_VERSION
    phase: str
    dp: str
    schema_file: str | None  # None for GAEB 90, PDF and Word, which have no schema
    schema_sha256: str | None
    line: int | None  # of the BoQ element
    project: str | None = None
    boq_name: str | None = None
    boq_id: str | None = None
    currency: str | None = None
    date: str | None = None  # ISO date of the bill (GAEB 90 record 01, XML BoQInfo/Date)
    body: list[GaebCategory | GaebEntry] = field(default_factory=list)
    total: XmlValue | None = None  # BoQInfo/Totals/Total
    vat_percent: XmlValue | None = None
    total_gross: XmlValue | None = None
    not_shown: Counter[str] = field(default_factory=Counter)  # elements kept out of the table
    encoding: str | None = None  # GAEB 90: the character set the file was read with
    scanned: bool = False  # PDF: every bill page was read by text recognition (OCR)
    # GAEB 90: item numbers (OZ) that do not fit the file's OZ mask, with their lines
    invalid_numbers: list[tuple[str, int]] = field(default_factory=list)

    @property
    def is_gaeb90(self) -> bool:
        return self.version == GAEB90_VERSION

    @property
    def is_pdf(self) -> bool:
        return self.version == PDF_VERSION

    @property
    def is_docx(self) -> bool:
        return self.version == DOCX_VERSION

    @property
    def format_label(self) -> str:
        """``X83`` for GAEB DA XML, ``D83`` for GAEB 90, ``PDF`` for a printed bill, ``Word``
        for a bill written as item paragraphs."""
        if self.is_pdf:
            return "PDF"
        if self.is_docx:
            return "Word"
        return f"{'D' if self.is_gaeb90 else 'X'}{self.phase}"

    @property
    def source_kind(self) -> SourceKind:
        if self.is_pdf:
            return SourceKind.OCR if self.scanned else SourceKind.PDF_TEXT
        if self.is_docx:
            return SourceKind.WORD
        return SourceKind.GAEB_90 if self.is_gaeb90 else SourceKind.GAEB_XML
