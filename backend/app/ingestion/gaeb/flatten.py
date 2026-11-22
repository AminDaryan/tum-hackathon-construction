"""Turn a :class:`~app.ingestion.gaeb.model.GaebDocument` into the table an LV printout shows,
and declare its structure (``RawSheet.declared``) so normalization does not guess it.

Layout (row 1 is the header):

* one SECTION row for the bill, then one per category (level = depth + 1), with its number and
  label;
* one ITEM row per Item or MarkupItem, one TEXT row per note (Remark, PerfDescr);
* after a category's content, a SUBTOTAL row with ``Totals/Total`` that closes the category;
  when the category is carried into the next level with another amount (``TotAfterDisc`` after
  a discount, ``TotalLSUM`` for a lump sum), an ADJUSTMENT row follows with the difference.
  That amount is computed from the two stated totals (both are named in the row's text and in
  the warning ``gaeb_amounts_derived``); it lets the parent category reconcile;
* the bill's net total as a SUBTOTAL row closing the bill section, and its gross total.

Totals membership (``counts_toward_totals``): in X81 and X83 an item counts unless it is a
Bedarfsposition ohne GB, an alternative item (``ALNSerNo`` > 0) or not applicable (``NotAppl``);
items inside an alternative group of categories are undecided (they count toward their own
category only). An X84 bid does not carry these flags (they are in the X83), so all its items
are undecided: the total checks then try both readings instead of reporting a false mismatch.

Numbers are NUMBER cells with the exact decimal of the XML text (``xs:decimal``: a point, no
thousands separators), so no separator is guessed.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.config import IngestionLimits
from app.ingestion.base import RawCell, RawSheet, RawValueType
from app.ingestion.gaeb.model import EntryKind, GaebCategory, GaebDocument, GaebEntry, XmlValue
from app.ingestion.security import TableLimitGuard
from app.models.dataset import ExtractionWarning, RowKind
from app.models.schema import TableDecisions

# (header, profile field). The headers are the usual German LV column names.
COLUMNS: tuple[tuple[str, str | None], ...] = (
    ("OZ", "item_code"),
    ("Kurztext", "description"),
    ("Positionsart", "item_type"),
    ("Menge", "quantity"),
    ("Einheit", "unit"),
    ("EP", "unit_price"),
    ("Nachlass %", "discount_percent"),
    ("GP", "line_total"),
    ("Währung", "currency"),
    ("Standardtext", "standard_text_key"),
    ("Standardtext-Katalog", "standard_text_catalog"),
    ("Langtext", "long_description"),
    ("GAEB-ID", None),
)
COL = {header: index for index, (header, _) in enumerate(COLUMNS, start=1)}
MAX_SECTION_LEVEL = 9
# Where a cell comes from: a file line, or a value, entry or category that knows its place.
Located = int | XmlValue | GaebEntry | GaebCategory | None
_NOTE_TYPES = {
    "Remark": "Hinweis",
    "PerfDescr": "Ausführungsbeschreibung",
    "SubDescr": "Unterbeschreibung",
}


def flatten(
    document: GaebDocument, limits: IngestionLimits
) -> tuple[RawSheet, list[ExtractionWarning]]:
    return _Flattener(document, limits).run()


def item_type(entry: GaebEntry) -> str:
    """The German item type of an entry, from its GAEB flags."""
    if entry.kind is EntryKind.MARKUP_ITEM:
        return "Zuschlagsposition"
    if entry.kind is EntryKind.NOTE:
        return _NOTE_TYPES.get(entry.element, entry.element)
    flags = _flags(entry)
    names: list[str] = []
    if flags.get("Provis") == "WithoutTotal":
        names.append("Bedarfsposition ohne GB")
    elif flags.get("Provis") == "WithTotal":
        names.append("Bedarfsposition mit GB")
    if "ALNSerNo" in flags:
        names.append("Grundposition" if flags["ALNSerNo"] == "0" else "Wahlposition")
    elif entry.in_alternative_category:
        names.append("Wahlposition (Wahlgruppe)")
    for flag, name in (  # names as the schema documents the flags
        ("LumpSumItem", "Pauschalposition"),
        ("HourIt", "Stundenlohnarbeiten"),
        ("QtyTBD", "Freie Menge"),
        ("KeyIt", "Schwerpunktposition"),
        ("NotAppl", "entfällt"),
        ("NotOffered", "nicht angeboten"),
    ):
        if flag in flags:
            names.append(name)
    names.extend(entry.extra_types)
    return ", ".join(names) or "Normalposition"


def counts_toward_totals(entry: GaebEntry, phase: str) -> bool | None:
    if phase == "84" or entry.in_alternative_category or entry.total_undecided:
        return None
    flags = _flags(entry)
    if flags.get("Provis") == "WithoutTotal" or "NotAppl" in flags:
        return False
    return not ("ALNSerNo" in flags and flags["ALNSerNo"] != "0")


def _flags(entry: GaebEntry) -> dict[str, str]:
    """The entry's GAEB flags as name -> value ("Provis=WithoutTotal" -> {"Provis": "WithoutTotal"};
    a flag without a value maps to "")."""
    return {name: value for name, _, value in (flag.partition("=") for flag in entry.flags)}


class _Flattener:
    def __init__(self, document: GaebDocument, limits: IngestionLimits) -> None:
        self.document = document
        self.sheet = RawSheet(
            name=document.boq_name or "LV", index=0, source_kind=document.source_kind
        )
        self.guard = TableLimitGuard("The bill", limits)
        self.max_chars = limits.max_cell_chars
        self.clipped = 0
        self.row = 1
        self.kinds: dict[int, RowKind] = {}
        self.counts: dict[int, bool | None] = {}
        self.levels: dict[int, int] = {}
        self.closes: dict[int, int | None] = {}
        self.derived = 0

    def run(self) -> tuple[RawSheet, list[ExtractionWarning]]:
        for header, column in COL.items():
            self.put(column, header, None)
        document = self.document
        bill = self.section(
            "", f"Leistungsverzeichnis {document.boq_name or ''}".strip(), document.line, 1
        )
        for child in document.body:
            self.node(child)
        if document.total is not None:
            self.amount_row(RowKind.SUBTOTAL, "Gesamtsumme netto", document.total, closes=bill)
        if document.total_gross is not None:
            vat = f" (MwSt. {document.vat_percent.text} %)" if document.vat_percent else ""
            self.amount_row(RowKind.GROSS_TOTAL, f"Gesamtsumme brutto{vat}", document.total_gross)
        self.sheet.declared = TableDecisions(
            sheet_index=0,
            header_row_numbers=[1],
            column_fields={COL[h]: f for h, f in COLUMNS},
            row_kinds=self.kinds,
            counts_toward_totals=self.counts,
            section_levels=self.levels,
            closes_section=self.closes,
        )
        return self.sheet, self.warnings()

    # ------------------------------------------------------------------ rows
    def next_row(self, kind: RowKind) -> int:
        self.row += 1
        self.kinds[self.row] = kind
        return self.row

    def put(self, column: int, text: str | None, at: Located, *, number: bool = False) -> None:
        """One cell; ``at`` is where it comes from: a file line, or a value, entry or category
        with its line (XML, GAEB 90) or its page and box (PDF)."""
        if text is None or text == "":
            return
        self.guard.admit(self.row, column)
        self.guard.check_text(text, self.row, column)
        if at is None or isinstance(at, int):
            line, page, bbox = at, None, None
        else:
            line, page, bbox = at.line, at.page, at.bbox
        # read by OCR: the engine's confidence travels with the value
        confidence = at.confidence if isinstance(at, XmlValue) else None
        self.sheet.cells[(self.row, column)] = RawCell(
            row=self.row,
            column=column,
            value_type=RawValueType.NUMBER if number else RawValueType.STRING,
            text=text,
            number=Decimal(text) if number else None,
            line_number=line,
            page_number=page,
            bbox=bbox,
            confidence=confidence,
        )
        self.sheet.max_row = max(self.sheet.max_row, self.row)
        self.sheet.max_column = max(self.sheet.max_column, column)

    def put_value(self, column: int, value: XmlValue | None) -> None:
        if value is not None:
            self.put(column, value.text, value, number=True)

    def section(self, number: str, label: str, at: Located, level: int) -> int:
        row = self.next_row(RowKind.SECTION)
        self.levels[row] = min(level, MAX_SECTION_LEVEL)
        self.put(COL["OZ"], number, at)
        self.put(COL["Kurztext"], label, at)
        return row

    def amount_row(
        self, kind: RowKind, label: str, value: XmlValue, *, closes: int | None = None
    ) -> int:
        row = self.next_row(kind)
        if kind is RowKind.SUBTOTAL:
            self.closes[row] = closes
        self.put(COL["Kurztext"], label, value)
        self.put_value(COL["GP"], value)
        self.put(COL["Währung"], self.document.currency, value)
        return row

    def node(self, node: GaebCategory | GaebEntry) -> None:
        if isinstance(node, GaebCategory):
            self.category(node)
        else:
            self.entry(node)

    def category(self, category: GaebCategory) -> None:
        row = self.section(category.number, category.label, category, category.level + 1)
        if category.alternative:
            self.put(COL["Positionsart"], "Wahlgruppe", category)
        self.put(COL["GAEB-ID"], category.element_id, category)
        for child in category.children:
            self.node(child)
        if category.total is None:
            return
        self.amount_row(
            RowKind.SUBTOTAL,
            f"Summe {category.number} {category.label}".strip(),
            category.total,
            closes=row,
        )
        carried = category.total_lump_sum or category.total_after_discount
        if carried is None or Decimal(carried.text) == Decimal(category.total.text):
            return
        reasons = []
        if category.discount_percent is not None:
            reasons.append(f"Nachlass {category.discount_percent.text} %")
        if category.discount_amount is not None:
            reasons.append(f"Nachlassbetrag {category.discount_amount.text}")
        if category.total_lump_sum is not None:
            reasons.append("Pauschalsumme")
        difference = Decimal(carried.text) - Decimal(category.total.text)
        row = self.next_row(RowKind.ADJUSTMENT)
        self.put(
            COL["Kurztext"],
            f"{', '.join(reasons) or 'Abweichender Betrag'} auf {category.number}: "
            f"{carried.text} statt {category.total.text} (Differenz berechnet)",
            carried,
        )
        self.put(
            COL["Nachlass %"],
            category.discount_percent.text if category.discount_percent else None,
            carried,
            number=True,
        )
        self.put(COL["GP"], str(difference), carried, number=True)
        self.put(COL["Währung"], self.document.currency, carried)
        self.derived += 1

    def entry(self, entry: GaebEntry) -> None:
        # A MarkupItem (Zuschlagsposition) adds a percentage of other items: an adjustment.
        kind = {
            EntryKind.NOTE: RowKind.TEXT,
            EntryKind.MARKUP_ITEM: RowKind.ADJUSTMENT,
        }.get(entry.kind, RowKind.ITEM)
        row = self.next_row(kind)
        if kind is RowKind.ITEM:
            self.counts[row] = counts_toward_totals(entry, self.document.phase)
        at = entry
        self.put(COL["OZ"], entry.number, at)
        text = entry.short_text
        markup = next((f.split("=", 1)[1] for f in entry.flags if f.startswith("Markup=")), None)
        if entry.kind is EntryKind.MARKUP_ITEM and markup and entry.markup_base:
            text = f"{text} ({markup} % auf {entry.markup_base.text})".strip()
        self.put(COL["Kurztext"], text, at)
        self.put(COL["Positionsart"], item_type(entry), at)
        self.put_value(COL["Menge"], entry.qty)
        if entry.unit is not None:
            self.put(COL["Einheit"], entry.unit.text, entry.unit)
        self.put_value(COL["EP"], entry.unit_price)
        self.put_value(COL["Nachlass %"], entry.discount_percent)
        self.put_value(COL["GP"], entry.total)
        if entry.unit_price is not None or entry.total is not None:
            self.put(COL["Währung"], self.document.currency, at)
        self.put(COL["Standardtext"], entry.standard_text_key, at)
        self.put(COL["Standardtext-Katalog"], entry.standard_text_catalog, at)
        long_text = entry.long_text
        if len(long_text) > self.max_chars:  # display column only; the file keeps the full text
            long_text = long_text[: self.max_chars - 1] + "…"
            self.clipped += 1
        self.put(COL["Langtext"], long_text, at)
        self.put(COL["GAEB-ID"], entry.element_id, at)

    # ------------------------------------------------------------------ notes
    def warnings(self) -> list[ExtractionWarning]:
        out: list[ExtractionWarning] = []
        if self.derived:
            out.append(
                ExtractionWarning(
                    code="gaeb_amounts_derived",
                    message=(
                        f"{self.derived} adjustment row(s) show the difference between a "
                        "category's stated total and the amount it carries into the next level "
                        "(after a discount, or a lump sum). The difference is computed from the "
                        "two stated totals; both are named in the row."
                    ),
                    count=self.derived,
                    needs_review=False,
                )
            )
        if self.clipped:
            out.append(
                ExtractionWarning(
                    code="gaeb_long_text_clipped",
                    message=(
                        f"{self.clipped} long text(s) exceed {self.max_chars:,} characters; the "
                        "Langtext column shows their beginning, the stored file keeps them whole."
                    ),
                    count=self.clipped,
                    needs_review=False,
                )
            )
        if self.document.phase == "84":
            out.append(
                ExtractionWarning(
                    code="gaeb_bid_without_tender",
                    message=(
                        f"A {self.document.format_label} bid carries prices but not the item "
                        "flags (contingency, alternative) or, often, the texts and units: those "
                        f"are in the {self.document.format_label[0]}83 it answers. Whether each "
                        "item counts toward the totals is therefore left open, and missing texts "
                        "and units are normal here."
                    ),
                    needs_review=False,
                )
            )
        if self.document.invalid_numbers:
            listed = ", ".join(
                f"{number!r} (line {line})" for number, line in self.document.invalid_numbers[:5]
            )
            more = len(self.document.invalid_numbers) - 5
            if more > 0:
                listed += f" and {more} more"
            out.append(
                ExtractionWarning(
                    code="gaeb90_invalid_item_number",
                    message=(
                        "Item numbers (OZ) that do not fit the OZ mask of record 00 (only the "
                        f"index may hold letters): {listed}. Each is shown as written, in the "
                        "category its records are in."
                    ),
                    count=len(self.document.invalid_numbers),
                    needs_review=True,
                )
            )
        if self.document.not_shown:
            listed = ", ".join(
                f"{name} ({count})" for name, count in sorted(self.document.not_shown.items())
            )
            out.append(
                ExtractionWarning(
                    code="gaeb_elements_not_shown",
                    message=(
                        f"GAEB {'records' if self.document.is_gaeb90 else 'elements'} kept in "
                        f"the file but not shown in the table: {listed}."
                    ),
                    count=sum(self.document.not_shown.values()),
                    needs_review=False,
                )
            )
        return out
