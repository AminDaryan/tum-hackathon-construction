"""Read a printed bill of quantities (Leistungsverzeichnis) from the lines of a PDF.

AVA programs print a bill in one of a few layouts, all built the same way: a column header
row on every page (``OZ``/``Pos-Nr.``, ``Menge``, ``ME``/``Einheit``, ``Einheitspreis``/``EP``,
``Gesamtbetrag``/``GP``), then for each item its ordinal number (OZ) in the left column, its
short and long text, and one line with quantity, unit, unit price and total. Category headings
carry an OZ but no quantity; ``Summe <OZ>`` lines close them.

Reading, in order:

1. **Bill pages.** A page belongs to the bill when it has the column header row. A page of the
   same bill whose header row is not recognised (body text drawn over it) keeps the columns of
   the page before, if it shares the bill's running header or footer. Other pages (cover,
   tender forms) are skipped and named in a warning.
2. **Running header and footer.** Lines above the column header, lines that repeat at the
   same height on many bill pages (with their digits ignored: page numbers, dates), page and
   print-date lines (``Seite:``, ``Druckdatum:``) and carry-over lines (``Übertrag``) are
   dropped.
3. **Quantity column.** Clean quantity lines (a number, a unit, then only amounts or blanks to
   fill) show where the document aligns its quantities, and whether it prints them with
   decimals; a number and a unit elsewhere in a text ("Breite 20 cm") is then not taken for
   a quantity.
4. **Blocks.** A block starts at an OZ in the OZ column, a ``Bereich``/``Abschnitt``/``Titel``
   heading, or a ``Summe`` line. An OZ block's quantity is on the OZ line (directly after the
   OZ) or on the last aligned quantity line of the block; the text before it is the item's,
   text after it a note. A block without a quantity is a category when later items are
   numbered below it, otherwise an item whose quantity is missing.
5. **Numbers.** Printed German numbers (``1.655,000``) become decimal text (``1655.000``).
   Amounts are assigned to the unit price or total column by their right edge. Blanks to fill
   (``.........``) are no value.

Every value keeps its page and box. The reading depends on the layout; what it could not
place is reported, never guessed.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.errors import ExtractionError
from app.ingestion.gaeb.model import (
    PDF_VERSION,
    EntryKind,
    GaebCategory,
    GaebDocument,
    GaebEntry,
    XmlValue,
)
from app.ingestion.pdf.layout import Line, Page, Word

logger = logging.getLogger(__name__)

GERMAN_NUMBER = re.compile(r"^-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?$")
NUMBER_LIKE = re.compile(r"^[-\d.,]*\d[-\d.,]*$")  # digits and separators, maybe broken
OZ = re.compile(r"^(?:\d{1,4}|\.{1,2}\d{1,5})(?:\.{1,2}\d{1,5})*\.?[A-Za-z]?$")
UNIT = re.compile(r"^[A-Za-zÄÖÜäöüß²³µ%/][A-Za-z0-9ÄÖÜäöüß²³µ%/.\-]{0,9}$")
BLANK = re.compile(r"^(?:EP|GP)?\.{3,}$")
SECTION_WORD = re.compile(r"^(?:Los|Bereich|Abschnitt|Unterabschnitt|Hauptabschnitt|Titel|Gewerk)$")
SUM_WORD = re.compile(r"^(?:Summe|Gesamtsumme|Zwischensumme)\b")
CARRY = re.compile(r"^(?:Übertrag|Uebertrag)\b")
PAGE_LINE = re.compile(r"^(?:Seite|Druckdatum|Datum)\s*:")  # page numbers, print dates
HEADER_QTY = re.compile(r"^Menge")
HEADER_PRICE = re.compile(r"^(?:Einheitspreis|EP\b|Preis\b)")
HEADER_TOTAL = re.compile(r"^(?:Gesamt|GP\b)")
GROSS = re.compile(r"brutto|inkl\.?\s*(?:MwSt|USt)", re.IGNORECASE)
NET = re.compile(r"netto|ohne\s*(?:MwSt|USt)", re.IGNORECASE)
ONLY_UNIT_PRICE = re.compile(r"Nur\s*Einh", re.IGNORECASE)
UNDECIDED_TYPES = re.compile(
    r"\b(Bedarfsposition|Eventualposition|Wahlposition|Alternativposition)\b", re.IGNORECASE
)
FURNITURE_SHARE = 0.4  # a line repeated on this share of bill pages is a running header/footer
ALIGNMENT_TOLERANCE = 4.0  # points
DECIMAL_SHARE = 0.95  # quantities "with decimals" when this share of clean quantity lines has them


@dataclass(frozen=True, slots=True)
class Columns:
    oz_x: float  # left edge of the OZ column header
    text_x: float  # left edge of the column after it (description, or Menge)
    qty_x: float  # left edge of the Menge header
    price_x: float  # left edge of the unit price header
    price_centre: float
    total_centre: float
    header_bottom: float


@dataclass(slots=True)
class BillPages:
    pages: list[tuple[Page, Columns]]
    skipped: list[int]  # pages without a bill table
    furniture: set[tuple[int, str]]


@dataclass(slots=True)
class _Block:
    kind: str  # "oz", "section", "sum", "note"
    lines: list[tuple[Line, Columns]] = field(default_factory=list)


@dataclass(slots=True)
class _Quantity:
    qty: XmlValue
    unit: XmlValue | None
    rest: list[Word]  # after the quantity and unit: amounts, blanks to fill
    line: Line
    lead: list[Word]  # text before the quantity on the same line


def read_bill(pages: list[Page], ocr_missing: str | None = None) -> tuple[GaebDocument, BillPages]:
    """The bill printed in ``pages``. :class:`ExtractionError` when no page has text (no text
    layer, and OCR found none or did not run: ``ocr_missing`` says why) or no page has a
    bill's column header."""
    if not any(page.lines for page in pages):
        if ocr_missing:
            # The technical reason (engine not installed, turned off) is for the server's log and
            # the system status, not for the person who uploaded the file.
            logger.warning("PDF without text not read: OCR is not available (%s)", ocr_missing)
        found = " Text recognition (OCR) found no text either." if any(p.ocr for p in pages) else ""
        raise ExtractionError(
            f"No text could be read from this PDF (it may be a scan).{found} Upload a PDF "
            "exported from the AVA program, or its GAEB file.",
            details={"reason": "pdf_no_text"},
        )
    bill = _bill_pages(pages)
    if not bill.pages:
        raise ExtractionError(
            "No bill of quantities table found: no page has a column header with Menge, "
            "Einheitspreis (EP) and Gesamtbetrag (GP).",
            details={"reason": "pdf_no_bill_table"},
        )
    document = _Reader(bill).read()
    document.scanned = all(page.ocr for page, _ in bill.pages)
    return document, bill


# --------------------------------------------------------------------------- pages
def find_header(lines: list[Line]) -> Columns | None:
    """The bill's column header among ``lines``: a line naming quantity, unit price and total."""
    for index, line in enumerate(lines):
        qty = next((w for w in line.words if HEADER_QTY.match(w.text)), None)
        price = next((w for w in line.words if HEADER_PRICE.match(w.text)), None)
        total = next(
            (
                w
                for w in line.words
                if HEADER_TOTAL.match(w.text) and price is not None and w.x0 > price.x0
            ),
            None,
        )
        if qty is None or price is None or total is None or not qty.x0 < price.x0:
            continue
        first = line.words[0]
        after = [w for w in line.words[1:] if w.x0 < qty.x0 and w.x0 - first.x1 > 8]
        bottom = line.bottom
        below = lines[index + 1] if index + 1 < len(lines) else None
        if below is not None and below.top - bottom < 6 and all(w.x0 > qty.x0 for w in below.words):
            bottom = below.bottom  # a second header line ("in EUR")
        price_words = [w for w in line.words if price.x0 <= w.x0 < total.x0]
        total_words = [w for w in line.words if w.x0 >= total.x0]
        return Columns(
            oz_x=first.x0,
            text_x=after[0].x0 if after else qty.x0,
            qty_x=qty.x0,
            price_x=price.x0,
            price_centre=(price.x0 + max(w.x1 for w in price_words)) / 2,
            total_centre=(total.x0 + max(w.x1 for w in total_words)) / 2,
            header_bottom=bottom,
        )
    return None


def _furniture_key(line: Line) -> tuple[int, str]:
    return round(line.top / 4), re.sub(r"\d+", "#", line.text)


def _bill_pages(pages: list[Page]) -> BillPages:
    found = [find_header(page.lines) for page in pages]
    headed = [page for page, columns in zip(pages, found, strict=True) if columns]
    counts: Counter[tuple[int, str]] = Counter()
    for page in headed:
        counts.update({_furniture_key(line) for line in page.lines})
    limit = max(2, len(headed) * FURNITURE_SHARE)
    furniture = {key for key, count in counts.items() if count >= limit}
    kept: list[tuple[Page, Columns]] = []
    skipped: list[int] = []
    last: Columns | None = None
    for page, columns in zip(pages, found, strict=True):
        if columns is not None:
            last = columns
            kept.append((page, columns))
        elif last is not None and any(_furniture_key(line) in furniture for line in page.lines):
            kept.append((page, last))
        else:
            skipped.append(page.number)
    return BillPages(kept, skipped, furniture)


# --------------------------------------------------------------------------- numbers
def german_decimal(text: str) -> str:
    """``1.655,000`` -> ``1655.000``; ``-12,5`` -> ``-12.5``."""
    return text.replace(".", "").replace(",", ".")


def _value(word: Word, line: Line) -> XmlValue:
    return XmlValue(german_decimal(word.text), None, line.page, line.box([word]), word.confidence)


def _text_value(word: Word, line: Line) -> XmlValue:
    return XmlValue(word.text, None, line.page, line.box([word]), word.confidence)


class _Reader:
    def __init__(self, bill: BillPages) -> None:
        self.bill = bill
        self.alignment: tuple[str, float] | None = None
        self.document = GaebDocument(
            version=PDF_VERSION,
            phase="",
            dp="",
            schema_file=None,
            schema_sha256=None,
            line=None,
        )
        self.categories: dict[tuple[str, ...], GaebCategory] = {}
        self.item_depth = 0  # the most common number of OZ parts: items are numbered this deep
        self.decimal_quantities = False  # the document prints every quantity with decimals

    # ------------------------------------------------------------------ lines
    def content(self) -> list[tuple[Line, Columns]]:
        out: list[tuple[Line, Columns]] = []
        for page, columns in self.bill.pages:
            for line in page.lines:
                if line.top <= columns.header_bottom + 1:
                    continue
                if _furniture_key(line) in self.bill.furniture or CARRY.match(line.text):
                    continue
                if any(PAGE_LINE.match(w.text) for w in line.words):
                    continue
                if any(CARRY.match(w.text) for w in line.words if w.x0 > columns.price_x - 60):
                    continue
                out.append((line, columns))
        return out

    def starts(self, line: Line, columns: Columns) -> str | None:
        first = line.words[0]
        if SUM_WORD.match(first.text):
            return "sum"
        if SECTION_WORD.match(first.text) and len(line.words) > 1 and OZ.match(line.words[1].text):
            return "section"
        if (
            OZ.match(first.text)
            and first.x0 < columns.text_x - 4
            and abs(first.x0 - columns.oz_x) < 30
            and (len(line.words) == 1 or line.words[1].x0 - first.x1 > 6)
        ):
            return "oz"
        return None

    # ------------------------------------------------------------------ quantities
    def quantity(
        self, line: Line, columns: Columns, *, after_oz: bool, learning: bool = False
    ) -> _Quantity | None:
        """The quantity and unit of ``line``, followed only by amounts in the price columns.

        The quantity starts the line (after its OZ when ``after_oz``) and has a unit; or, once
        the quantity column is known, it may follow text that ends well before it (a layout
        that prints the last text line and the quantity on one line), and its unit may be
        missing (the reader then reports the missing unit instead of guessing one)."""
        words = line.words[1:] if after_oz else line.words
        for k, number in enumerate(words):
            if not GERMAN_NUMBER.match(number.text):
                continue
            if not columns.qty_x - 70 <= number.x1 <= columns.price_x + 5:
                return None
            unit: Word | None = words[k + 1] if k + 1 < len(words) else None
            if unit is not None and (unit.x0 >= columns.price_x or not _unit_like(unit)):
                unit = None
            rest = words[k + 2 :] if unit is not None else words[k + 1 :]
            if any(w.x0 < columns.price_x - 40 for w in rest):
                return None
            known = not learning and self.alignment is not None and self.aligned(number)
            if (k > 0 or unit is None) and not known:
                return None
            if k > 0 and (after_oz or words[k - 1].x1 > number.x0 - 15):
                return None
            if not learning and not self.aligned(number):
                return None
            if not learning and self.decimal_quantities and "," not in number.text:
                return None  # this document prints quantities with decimals: a bare number is text
            return _Quantity(
                _value(number, line),
                _text_value(unit, line) if unit is not None else None,
                rest,
                line,
                words[:k],
            )
        return None

    def aligned(self, word: Word) -> bool:
        if self.alignment is None:
            return True
        edge, position = self.alignment
        return abs((word.x1 if edge == "right" else word.x0) - position) <= ALIGNMENT_TOLERANCE

    def learn_alignment(self, lines: list[tuple[Line, Columns]]) -> None:
        rights: Counter[int] = Counter()
        lefts: Counter[int] = Counter()
        decimals: Counter[bool] = Counter()
        for line, columns in lines:
            after_oz = self.starts(line, columns) == "oz"
            found = self.quantity(line, columns, after_oz=after_oz, learning=True)
            if found is None and after_oz:
                continue
            if found is None or any(
                not (GERMAN_NUMBER.match(w.text) or BLANK.match(w.text) or w.text in ("EP", "GP"))
                for w in found.rest
            ):
                continue
            number = (line.words[1:] if after_oz else line.words)[0]
            rights[round(number.x1)] += 1
            lefts[round(number.x0)] += 1
            decimals["," in number.text] += 1
        if not rights:
            return
        self.decimal_quantities = decimals[True] >= DECIMAL_SHARE * sum(decimals.values())

        def peak(counts: Counter[int]) -> tuple[int, int]:
            def near(x: int) -> int:
                return sum(v for k, v in counts.items() if abs(k - x) <= 3)

            best = max(counts, key=near)
            return best, near(best)

        right, right_count = peak(rights)
        left, left_count = peak(lefts)
        self.alignment = ("right", right) if right_count >= left_count else ("left", left)

    def amounts(
        self, words: list[Word], line: Line, columns: Columns
    ) -> tuple[XmlValue | None, XmlValue | None, list[str]]:
        price = total = None
        notes: list[str] = []
        unreadable: set[str] = set()  # columns with a number OCR could not read whole
        for word in words:
            column = (
                "price"
                if abs(word.x1 - columns.price_centre) < abs(word.x1 - columns.total_centre)
                else "total"
            )
            if GERMAN_NUMBER.match(word.text):
                if column == "price":
                    price = _value(word, line)
                else:
                    total = _value(word, line)
            elif word.confidence is not None and NUMBER_LIKE.match(word.text):
                unreadable.add(column)  # "2.035," next to "930": no piece is taken for the value
            elif not BLANK.match(word.text) and word.text not in ("EP", "GP"):
                notes.append(word.text)
        return (
            None if "price" in unreadable else price,
            None if "total" in unreadable else total,
            notes,
        )

    # ------------------------------------------------------------------ blocks
    def read(self) -> GaebDocument:
        lines = self.content()
        self.learn_alignment(lines)
        self.header_facts()
        blocks: list[_Block] = []
        for line, columns in lines:
            kind = self.starts(line, columns)
            if kind is not None or not blocks:
                blocks.append(_Block(kind or "note"))
            blocks[-1].lines.append((line, columns))
        numbered = [self.oz_parts(b.lines[0][0].words[0].text) for b in blocks if b.kind == "oz"]
        depths = Counter(len(parts) for parts in numbered)
        self.item_depth = depths.most_common(1)[0][0] if depths else 0
        for block in blocks:
            if block.kind == "sum":
                self.sum_line(block)
            elif block.kind == "section":
                line, _ = block.lines[0]
                self.section(line.words[1], line, " ".join(w.text for w in line.words[2:]))
                self.note(block.lines[1:])
            elif block.kind == "note":
                self.note(block.lines)
            else:
                self.oz_block(block, numbered)
        return self.document

    def oz_block(self, block: _Block, numbered: list[tuple[str, ...]]) -> None:
        first, columns = block.lines[0]
        oz_word = first.words[0]
        found = self.quantity(first, columns, after_oz=True)
        at = 0 if found else None
        if found is None:
            for k in range(len(block.lines) - 1, 0, -1):
                line, line_columns = block.lines[k]
                found = self.quantity(line, line_columns, after_oz=False)
                if found is not None:
                    at = k
                    break
        if (
            found is not None
            and at
            and _recognised(found.line)
            and any(
                self.quantity(line, line_columns, after_oz=False) is not None
                for line, line_columns in block.lines[1:at]
            )
        ):
            # Two quantity lines in one block of a scan: the item number between them was
            # probably not recognised. Neither quantity is given to this item; it is reported.
            found, at = None, None
        texts = [] if at == 0 else [_text_of(first.words[1:], columns)]
        body = block.lines[1:] if at in (0, None) else block.lines[1:at]
        tail = [] if at in (0, None) else block.lines[at + 1 :]
        texts += [line.text for line, _ in body]
        if found is not None and found.lead and at != 0:
            texts.append(" ".join(w.text for w in found.lead))
        bold_lead = _bold_lead(first.words[1:], body) if at != 0 else 0
        texts = [t for t in texts if t]
        # Some printouts repeat the short text as the first line of the long text: a line
        # equal to the one before it is printed twice, not written twice.
        kept: list[str] = []
        for index, text in enumerate(texts):
            if kept and text == kept[-1]:
                bold_lead -= 1 if index < bold_lead else 0
                continue
            kept.append(text)
        texts = kept
        parts = self.oz_parts(oz_word.text)
        if found is None and (
            any(later[: len(parts)] == parts and len(later) > len(parts) for later in numbered)
            or len(parts) < self.item_depth
        ):
            # a category heading: its label on the OZ line or the line below, the rest a note
            label = _text_of(first.words[1:], columns)
            rest = block.lines[1:]
            if not label and rest:
                label, rest = rest[0][0].text, rest[1:]
            self.section(oz_word, first, label)
            self.note(rest)
            return
        entry = GaebEntry(
            kind=EntryKind.ITEM,
            element="Item",
            element_id=None,
            number=oz_word.text.rstrip("."),
            line=None,
            page=first.page,
            bbox=first.box([oz_word]),
        )
        split = max(1, bold_lead) if texts else 0
        entry.short_text = " ".join(texts[:split])
        entry.long_text = " ".join(texts[split:])
        if found is not None:
            entry.qty, entry.unit = found.qty, found.unit
            entry.unit_price, entry.total, notes = self.amounts(found.rest, found.line, columns)
            if ONLY_UNIT_PRICE.search(" ".join(notes)):
                entry.extra_types += ("Nur Einheitspreis",)
                entry.total_undecided = True
        named = UNDECIDED_TYPES.search(entry.short_text)
        if named:
            entry.extra_types += (f"{named.group(1)} (laut Text)",)
            entry.total_undecided = True
        self.attach(entry, parts)
        self.note(tail)

    def section(self, oz_word: Word, line: Line, label: str) -> None:
        parts = self.oz_parts(oz_word.text)
        parent = self.parent(parts)
        category = GaebCategory(
            element_id=None,
            number=oz_word.text.rstrip("."),
            label=label,
            line=None,
            level=(parent.level + 1) if parent else 1,
            page=line.page,
            bbox=line.box([oz_word]),
        )
        self.categories[parts] = category
        (parent.children if parent else self.document.body).append(category)

    def note(self, lines: list[tuple[Line, Columns]]) -> None:
        texts = [line.text for line, _ in lines if line.text]
        if not texts:
            return
        first = lines[0][0]
        entry = GaebEntry(
            kind=EntryKind.NOTE,
            element="Remark",
            element_id=None,
            number="",
            line=None,
            short_text=texts[0],
            long_text=" ".join(texts[1:]),
            page=first.page,
            bbox=first.box(),
        )
        self.attach(entry, None)

    def sum_line(self, block: _Block) -> None:
        line, columns = block.lines[0]
        price, total, _ = self.amounts(
            [w for w in line.words if w.x0 >= columns.price_x - 40], line, columns
        )
        amount = total or price
        named = next((w for w in line.words[1:3] if OZ.match(w.text)), None)
        if amount is not None and named is not None:
            category = self.categories.get(self.oz_parts(named.text))
            if category is not None:
                category.total = amount
        elif amount is not None:
            self.bill_total(line.text, amount)
        self.note(block.lines[1:])

    def bill_total(self, label: str, amount: XmlValue) -> None:
        """A total of the whole bill: net ("Summe (netto)", "Summe:") or gross ("Brutto",
        or a second, larger "Gesamtsumme" after the net total)."""
        document = self.document
        if GROSS.search(label):
            document.total_gross = amount
        elif NET.search(label) or document.total is None:
            document.total = amount
        elif Decimal(amount.text) > Decimal(document.total.text):
            document.total_gross = amount

    def attach(self, entry: GaebEntry, parts: tuple[str, ...] | None) -> None:
        parent = self.parent(parts) if parts is not None else self.last_category()
        (parent.children if parent else self.document.body).append(entry)

    def parent(self, parts: tuple[str, ...]) -> GaebCategory | None:
        for length in range(len(parts) - 1, 0, -1):
            category = self.categories.get(parts[:length])
            if category is not None:
                return category
        return None

    def last_category(self) -> GaebCategory | None:
        return next(reversed(self.categories.values()), None)

    @staticmethod
    def oz_parts(text: str) -> tuple[str, ...]:
        return tuple(part.lstrip("0") or "0" for part in re.split(r"\.+", text.strip(".")) if part)

    def header_facts(self) -> None:
        """Bill name, project and currency from the lines above the first column header."""
        page, columns = self.bill.pages[0]
        for line in page.lines:
            if line.top > columns.header_bottom:
                break
            label, _, rest = line.text.partition(" ")
            if label in ("LV:", "Leistungsverzeichnis:") and rest and not self.document.boq_name:
                self.document.boq_name = rest.strip()[:80]
            elif label in ("Projekt:", "Bauvorhaben:") and rest and not self.document.project:
                self.document.project = rest.strip()[:200]
            if "EUR" in line.text.split() or "€" in line.text:
                self.document.currency = "EUR"


def _recognised(line: Line) -> bool:
    """Whether ``line`` was read by OCR (its words carry the engine's confidence)."""
    return any(word.confidence is not None for word in line.words)


def _unit_like(word: Word) -> bool:
    """A unit (``m2``, ``psch``, ``m³``); for a word read by OCR also a short token that is not
    a number (``m?`` where the engine could not read a superscript): it is kept as written, so
    the unit check reports it and the quantity is not lost."""
    if UNIT.match(word.text):
        return True
    return (
        word.confidence is not None
        and len(word.text) <= 6
        and not GERMAN_NUMBER.match(word.text)
        and any(char.isalpha() for char in word.text)
    )


def _text_of(words: list[Word], columns: Columns) -> str:
    return " ".join(w.text for w in words if w.x1 < columns.price_x)


def _bold_lead(oz_rest: list[Word], body: list[tuple[Line, Columns]]) -> int:
    """How many leading text lines are bold (the short text of many layouts)."""
    lines = ([oz_rest] if oz_rest else []) + [line.words for line, _ in body]
    count = 0
    for words in lines:
        if words and all(w.bold for w in words):
            count += 1
        else:
            break
    return count
