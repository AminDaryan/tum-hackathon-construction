"""Synthetic bills of quantities with injected errors and their ground truth (brief Part L).

A bill is generated from a seed: sections of priced items, a subtotal per section, the net total,
one tax line and the gross total, in English or German conventions. Errors are injected the way
they happen in practice: an item-level slip (a wrong line total, an unknown unit, a duplicated
row, a missing rate, a quantity that is not a number) is summed into the totals as written, like
a spreadsheet would; a total-level slip (a subtotal, the net total or the tax typed wrong) leaves
the other totals as they were. Each error is recorded with the cell that holds it and every row
where a correct checker may report it (the error's own row and the totals it throws off).

Bills also carry what real ones do and what must not be reported: a title block above the
header, continuation text rows, blank rows, contingency and alternative items that are not
counted in the totals (and contingency items that are), and "rate only" items. Errors are only
injected into ordinary priced items, so the ground truth stays unambiguous. A section holds the
work its name says (:data:`SECTION_ITEMS`), and the copies of one catalogue item in a bill are
priced within 10 % of each other, so that the signal checks (peer prices, section fit) see a
clean bill as clean and only the injected errors stand out.

Bills are written as XLSX (numbers as numeric cells) or CSV (English: commas, thousands
separators on amounts; German: semicolons, decimal commas). Everything is decided by
``random.Random(seed)``: the same seed gives the same bills, errors and ground truth, and the
same bytes (XLSX files carry fixed timestamps, :data:`WORKBOOK_TIMESTAMP`), so the hashes in a
benchmark manifest identify the files. Amounts are exact decimals.

This is the ``standard`` corpus variant and its error kinds are :data:`STANDARD_KINDS`. The
``boq`` variant (:mod:`app.evaluation.boq`, ``CorpusConfig(variant="boq")``) generates bills
that behave like real ones and plants the other kinds of :class:`ErrorKind` as well.
"""

from __future__ import annotations

import csv
import io
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter

from app.models.schema import SchemaDecisions, TableDecisions

CENT = Decimal("0.01")
# The creation and modification time written into every XLSX file and its ZIP members. A fixed
# value, not the time of the run: otherwise two runs with the same seed would differ byte for
# byte and so would the sha256 values in the manifest.
WORKBOOK_TIMESTAMP = datetime(2026, 1, 1)
# Permissions recorded for each ZIP member (what ``ZipFile.writestr`` records by default).
_MEMBER_ATTRIBUTES = 0o600 << 16


class ErrorKind(StrEnum):
    LINE_TOTAL = "line_total_arithmetic"
    SUBTOTAL = "subtotal_mismatch"
    NET_TOTAL = "net_total_mismatch"
    TAX = "tax_mismatch"
    UNKNOWN_UNIT = "unknown_unit"
    DUPLICATE_ROW = "duplicate_row"
    MISSING_PRICE = "missing_unit_price"
    INVALID_QUANTITY = "invalid_quantity"
    # Planted only in the boq variant (app.evaluation.boq): plan step B1.2, by anomaly type.
    PRICE_DECIMAL_SLIP = "price_decimal_slip"
    PRICE_DIGIT_SWAP = "price_digit_swap"
    INCONSISTENT_RATE = "inconsistent_rate"
    WRONG_RATE_COPIED = "wrong_rate_copied"
    PLACEHOLDER_PRICE = "placeholder_price"
    HIGH_CONTINGENCY_PRICE = "high_contingency_price"
    QUANTITY_DECIMAL_SLIP = "quantity_decimal_slip"
    QUANTITY_UNIT_SLIP = "quantity_unit_slip"
    PRICE_PER_WRONG_UNIT = "price_per_wrong_unit"
    WRONG_UNIT = "wrong_unit"
    MISPLACED_POSITION = "misplaced_position"
    CODE_OUTSIDE_SECTION = "code_outside_section"
    LINE_TOTAL_SLIP = "line_total_slip"
    COMPONENT_SUM_ERROR = "component_sum_error"
    DUPLICATE_POSITION = "duplicate_position"
    NEAR_DUPLICATE_POSITION = "near_duplicate_position"


# The kinds of the standard variant, in the order its deck is built from (adding kinds to
# ErrorKind must not change the standard corpus of a seed).
STANDARD_KINDS: tuple[ErrorKind, ...] = (
    ErrorKind.LINE_TOTAL,
    ErrorKind.SUBTOTAL,
    ErrorKind.NET_TOTAL,
    ErrorKind.TAX,
    ErrorKind.UNKNOWN_UNIT,
    ErrorKind.DUPLICATE_ROW,
    ErrorKind.MISSING_PRICE,
    ErrorKind.INVALID_QUANTITY,
)

ITEM_LEVEL = (
    ErrorKind.LINE_TOTAL,
    ErrorKind.UNKNOWN_UNIT,
    ErrorKind.DUPLICATE_ROW,
    ErrorKind.MISSING_PRICE,
    ErrorKind.INVALID_QUANTITY,
)
# The net total and the tax line are not corrupted in the same bill (their checks overlap).
EXCLUSIVE = frozenset({ErrorKind.NET_TOTAL, ErrorKind.TAX})

# Rule ids that name the error correctly. A finding with another rule on an acceptable row still
# counts as a true positive; the report shows how many detections also had the expected rule.
# For the boq kinds the plan names the rule ids of some checks only; the checks themselves are
# in app.evaluation.expectations.
EXPECTED_RULES: dict[ErrorKind, tuple[str, ...]] = {
    ErrorKind.LINE_TOTAL: ("line_total_mismatch",),
    ErrorKind.SUBTOTAL: ("subtotal_mismatch",),
    ErrorKind.NET_TOTAL: ("grand_total_mismatch",),
    ErrorKind.TAX: ("tax_mismatch",),
    ErrorKind.UNKNOWN_UNIT: ("unknown_unit",),
    ErrorKind.DUPLICATE_ROW: ("exact_duplicate",),
    ErrorKind.MISSING_PRICE: ("required_value",),
    ErrorKind.INVALID_QUANTITY: ("invalid_value", "wrong_type"),
    ErrorKind.PRICE_DECIMAL_SLIP: (),
    ErrorKind.PRICE_DIGIT_SWAP: (),
    ErrorKind.INCONSISTENT_RATE: (),
    ErrorKind.WRONG_RATE_COPIED: (),
    ErrorKind.PLACEHOLDER_PRICE: ("token_price", "zero_price"),
    ErrorKind.HIGH_CONTINGENCY_PRICE: (),
    ErrorKind.QUANTITY_DECIMAL_SLIP: (),
    ErrorKind.QUANTITY_UNIT_SLIP: (),
    ErrorKind.PRICE_PER_WRONG_UNIT: (),
    ErrorKind.WRONG_UNIT: (),
    ErrorKind.MISPLACED_POSITION: (),
    ErrorKind.CODE_OUTSIDE_SECTION: ("item_outside_section",),
    ErrorKind.LINE_TOTAL_SLIP: ("line_total_mismatch",),
    ErrorKind.COMPONENT_SUM_ERROR: ("component_sum_mismatch",),
    ErrorKind.DUPLICATE_POSITION: ("exact_duplicate",),
    ErrorKind.NEAR_DUPLICATE_POSITION: (),
}
# The field holding the mistake (None: the whole row). A component error names its component
# (unit_price_component_1 to _6) in its ground truth instead.
ERROR_FIELD: dict[ErrorKind, str | None] = {
    ErrorKind.LINE_TOTAL: "line_total",
    ErrorKind.SUBTOTAL: "line_total",
    ErrorKind.NET_TOTAL: "line_total",
    ErrorKind.TAX: "line_total",
    ErrorKind.UNKNOWN_UNIT: "unit",
    ErrorKind.DUPLICATE_ROW: None,
    ErrorKind.MISSING_PRICE: "unit_price",
    ErrorKind.INVALID_QUANTITY: "quantity",
    ErrorKind.PRICE_DECIMAL_SLIP: "unit_price",
    ErrorKind.PRICE_DIGIT_SWAP: "unit_price",
    ErrorKind.INCONSISTENT_RATE: "unit_price",
    ErrorKind.WRONG_RATE_COPIED: "unit_price",
    ErrorKind.PLACEHOLDER_PRICE: "unit_price",
    ErrorKind.HIGH_CONTINGENCY_PRICE: "unit_price",
    ErrorKind.QUANTITY_DECIMAL_SLIP: "quantity",
    ErrorKind.QUANTITY_UNIT_SLIP: "quantity",
    ErrorKind.PRICE_PER_WRONG_UNIT: "unit_price",
    ErrorKind.WRONG_UNIT: "unit",
    ErrorKind.MISPLACED_POSITION: None,
    ErrorKind.CODE_OUTSIDE_SECTION: "item_code",
    ErrorKind.LINE_TOTAL_SLIP: "line_total",
    ErrorKind.COMPONENT_SUM_ERROR: "unit_price_component_1",
    ErrorKind.DUPLICATE_POSITION: None,
    ErrorKind.NEAR_DUPLICATE_POSITION: None,
}


@dataclass(frozen=True)
class Style:
    """How one language writes a bill."""

    language: str
    header: tuple[str, ...]
    tax_rate: Decimal
    section_format: str
    subtotal_format: str
    net_text: str
    tax_text: str
    gross_text: str
    code_in_section_row: bool
    section_names: tuple[str, ...]
    catalogue: tuple[tuple[str, str, str], ...]  # (description, unit, scale), SECTION_ITEMS order
    place: str
    unknown_units: tuple[str, ...]
    title_lines: tuple[str, ...]  # formats with {project} and {number}
    continuations: tuple[str, ...]
    not_counted: tuple[str, ...]  # formats with {text}: items left out of the totals
    counted_marked: tuple[str, ...]  # formats with {text}: marked items that are counted
    rate_only: str
    # The formats of not_counted and counted_marked that make the item a contingency position
    # (Bedarfsposition): the generator's own item type, which the benchmark scores the list of
    # contingency positions against (app.evaluation.scoring.RISK_NOTE_RULES).
    contingency_formats: tuple[str, ...] = ()

    def section_code(self, section: int) -> str:
        return f"{section:02d}" if self.language == "de" else str(section)

    def item_code(self, section: int, item: int) -> str:
        if self.language == "de":
            return f"{section:02d}.{item * 10:04d}"
        return f"{section}.{item}"


ENGLISH = Style(
    language="en",
    header=("Item", "Description", "Qty", "Unit", "Rate", "Amount"),
    tax_rate=Decimal(20),
    section_format="Section {code} {name}",
    subtotal_format="Subtotal section {code}",
    net_text="Grand total",
    tax_text="VAT 20%",
    gross_text="Total incl. VAT",
    code_in_section_row=False,
    section_names=(
        "Groundworks",
        "Concrete",
        "Masonry",
        "Drainage",
        "Steelwork",
        "Roofing",
        "Finishes",
        "Doors",
    ),
    catalogue=(
        ("Excavate topsoil", "m2", "measure"),
        ("Excavate trench for foundations", "m3", "measure"),
        ("Dispose of excavated material off site", "m3", "measure"),
        ("Hardcore fill, compacted in layers", "m3", "measure"),
        ("Blinding concrete, 50 mm thick", "m2", "measure"),
        ("Reinforced concrete C30/37 in walls", "m3", "measure"),
        ("Reinforcement bars B500B", "t", "tonnes"),
        ("Formwork to vertical wall faces", "m2", "measure"),
        ("Precast concrete lintel", "nr", "count"),
        ("Blockwork wall, 140 mm", "m2", "measure"),
        ("Damp-proof membrane", "m2", "measure"),
        ("Drainage pipe DN 150", "m", "measure"),
        ("Inspection chamber", "nr", "count"),
        ("Structural steel beam HEA 200", "kg", "kilograms"),
        ("Roof insulation, 160 mm", "m2", "measure"),
        ("Plasterboard wall lining", "m2", "measure"),
        ("Emulsion paint, two coats", "m2", "measure"),
        ("Internal door set", "nr", "count"),
        ("Scaffold hire", "wk", "weeks"),
        ("Testing and commissioning", "item", "lump_sum"),
    ),
    place="grid line",
    unknown_units=("bag", "roll", "pallet", "coil"),
    title_lines=("Bill of Quantities: {project}", "Project 2026-{number}"),
    continuations=(
        "including disposal off site",
        "in accordance with the specification",
        "fixings and sealants included",
    ),
    not_counted=("{text}, not included in the total", "Alternative: {text}"),
    counted_marked=(),
    rate_only="Rate only",
)

GERMAN = Style(
    language="de",
    header=("OZ", "Kurztext", "Menge", "ME", "EP", "GP"),
    tax_rate=Decimal(19),
    section_format="Titel {code} {name}",
    subtotal_format="Summe Titel {code}",
    net_text="Gesamtsumme netto",
    tax_text="zzgl. 19 % MwSt.",
    gross_text="Gesamtsumme brutto",
    code_in_section_row=True,
    section_names=(
        "Erdarbeiten",
        "Betonarbeiten",
        "Mauerarbeiten",
        "Entwässerung",
        "Stahlbau",
        "Dacharbeiten",
        "Trockenbau",
        "Malerarbeiten",
    ),
    catalogue=(
        ("Oberboden abtragen", "m2", "measure"),
        ("Baugrube ausheben und verfüllen", "m3", "measure"),
        ("Boden laden, abfahren und entsorgen, Z 1.1", "m3", "measure"),
        ("Schottertragschicht liefern und verdichten", "m3", "measure"),
        ("Sauberkeitsschicht C12/15, 5 cm", "m2", "measure"),
        ("Stahlbeton C30/37 für Wände", "m3", "measure"),
        ("Betonstahl B500B liefern und verlegen", "t", "tonnes"),
        ("Schalung für Wandflächen", "m2", "measure"),
        ("Fertigteilsturz", "Stk", "count"),
        ("Mauerwerk KS 17,5 cm", "m2", "measure"),
        ("Abdichtung der Bodenplatte", "m2", "measure"),
        ("Grundleitung DN 150", "m", "measure"),
        ("Kontrollschacht DN 1000", "Stk", "count"),
        ("Stahlträger HEA 200", "kg", "kilograms"),
        ("Dachdämmung 16 cm", "m2", "measure"),
        ("Gipskarton-Vorsatzschale", "m2", "measure"),
        ("Dispersionsanstrich, zweifach", "m2", "measure"),
        ("Innentür mit Zarge", "Stk", "count"),
        ("Gerüst vorhalten", "Wo", "weeks"),
        ("Prüfung und Inbetriebnahme", "psch", "lump_sum"),
    ),
    place="Achse",
    unknown_units=("Sack", "Rolle", "Pal", "Bund"),
    title_lines=("Leistungsverzeichnis {project}", "Projekt 2026-{number}"),
    continuations=(
        "inkl. Abfuhr und Entsorgung",
        "inkl. Befestigungsmaterial",
        "Ausführung gemäß Detailplan",
    ),
    not_counted=("{text}, Bedarfsposition ohne GB", "Alternativposition: {text}"),
    counted_marked=("{text}, Bedarfsposition mit GB",),
    rate_only="nur EP",
    contingency_formats=("{text}, Bedarfsposition ohne GB", "{text}, Bedarfsposition mit GB"),
)

STYLES = {"en": ENGLISH, "de": GERMAN}

# The catalogue items (by index) each section holds, by the index of its name in
# Style.section_names; both styles list their sections and catalogues in the same order.
SECTION_ITEMS: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3),  # groundworks
    (4, 5, 6, 7),  # concrete
    (8, 9, 10),  # masonry: lintels, blockwork, damp-proofing
    (11, 12, 19),  # drainage, with its testing and commissioning
    (13, 18),  # steelwork, with scaffold
    (14, 18),  # roofing, with scaffold
    (15, 16),  # finishes
    (17,),  # doors
)
FORMATS = ("xlsx", "csv")


@dataclass(eq=False)
class Line:
    """One row of a bill below the header; ``kind`` is the row kind the generator meant.
    Compared by identity, so a duplicated row is a different line."""

    kind: str
    text: str
    section: int | None = None
    code: str | None = None
    quantity: Decimal | str | None = None  # a str only when an invalid number was injected
    unit: str | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    total_text: str | None = None  # "nur EP" / "Rate only" in the amount column
    counted: bool = True  # added into the totals
    scale: str | None = None  # the catalogue's quantity scale ("lump_sum", "measure", ...)
    contingency: bool = False  # a contingency position (Style.contingency_formats)

    @property
    def plain_item(self) -> bool:
        """An ordinary priced item: the only kind of row errors are injected into."""
        return self.kind == "item" and self.counted and self.total_text is None


@dataclass(frozen=True)
class GroundTruth:
    """One injected error in file coordinates (1-based rows, header in row 1)."""

    error_id: str
    kind: ErrorKind
    row: int
    field: str | None
    rows: tuple[int, ...]  # rows where reporting it is correct: ``row`` and the totals it affects
    expected_rules: tuple[str, ...]
    change: str


@dataclass(frozen=True)
class SyntheticDocument:
    name: str
    language: str
    format: str
    content: bytes
    row_kinds: dict[int, str]  # source row -> the row kind the generator meant (header excluded)
    truths: tuple[GroundTruth, ...]
    features: dict[str, bool | int] = field(default_factory=dict)  # boq: what the bill carries
    # Source column -> field for the columns no header maps (boq: the STLB-Bau key and the unit
    # price components): the harness maps them at upload, as a reviewer would (:meth:`decisions`).
    column_fields: dict[int, str] = field(default_factory=dict)
    # The source rows of the contingency and hourly positions the generator wrote, by its own
    # item types: normal content of a bill, against which a list of such positions is scored
    # (app.evaluation.scoring.RISK_NOTE_RULES). Neither generator writes hourly work.
    contingency_and_hourly_rows: frozenset[int] = frozenset()

    @property
    def data_rows(self) -> int:
        return len(self.row_kinds)

    def decisions(self) -> SchemaDecisions | None:
        """The reviewer's column mappings the harness uploads the document with, if any."""
        if not self.column_fields:
            return None
        columns: dict[int, str | None] = dict(self.column_fields)
        return SchemaDecisions(tables=[TableDecisions(sheet_index=0, column_fields=columns)])


@dataclass
class _Injection:
    error_id: str
    kind: ErrorKind
    target: Line
    related: list[Line] = field(default_factory=list)
    change: str = ""


@dataclass
class Bill:
    style: Style
    lines: list[Line]
    title: list[str] = field(default_factory=list)  # rows above the header ("" = blank)
    injections: list[_Injection] = field(default_factory=list)

    @property
    def header_row(self) -> int:
        return len(self.title) + 1

    def row_of(self, line: Line) -> int:
        index = next(i for i, other in enumerate(self.lines) if other is line)
        return self.header_row + 1 + index


def _quantity(rng: random.Random, scale: str) -> Decimal:
    if scale == "measure":
        if rng.random() < 0.5:
            return Decimal(rng.randint(1, 2500))
        return Decimal(rng.randint(100, 250000)) / 100
    if scale == "tonnes":
        return Decimal(rng.randint(10, 5000)) / 100
    if scale == "kilograms":
        return Decimal(rng.randint(20, 20000))
    if scale == "weeks":
        return Decimal(rng.randint(1, 52))
    if scale == "count":
        return Decimal(rng.randint(1, 60))
    return Decimal(1)  # lump sum


_PRICE_CENTS = {
    "measure": (150, 25000),
    "tonnes": (80000, 180000),
    "kilograms": (150, 600),
    "weeks": (5000, 80000),
    "count": (2000, 250000),
    "lump_sum": (50000, 2500000),
}


def _price(rng: random.Random, scale: str) -> Decimal:
    return Decimal(rng.randint(*_PRICE_CENTS[scale])) / 100


def _priced(rng: random.Random, base: Decimal) -> Decimal:
    """``base`` moved by up to 10 % either way: the same work priced in another place."""
    return max(CENT, (base * Decimal(rng.randint(90, 110)) / 100).quantize(CENT, ROUND_HALF_UP))


# Chances of the realistic structures (per bill, per section gap, per item).
TITLE_BLOCK = 0.5
BLANK_BEFORE_SECTION = 0.3
CONTINUATION = 0.15
NOT_COUNTED = 0.06
COUNTED_MARKED = 0.04
RATE_ONLY = 0.04
PROJECTS = ("Warehouse 3", "School extension", "Office block B", "Depot north")


def generate_bill(
    rng: random.Random, style: Style, *, sections: tuple[int, int], items: tuple[int, int]
) -> Bill:
    title: list[str] = []
    if rng.random() < TITLE_BLOCK:
        project, number = rng.choice(PROJECTS), rng.randint(100, 999)
        title = [line.format(project=project, number=number) for line in style.title_lines]
        title.append("")
    lines: list[Line] = []
    used: set[tuple[str, int]] = set()
    prices: dict[str, Decimal] = {}  # catalogue item -> its base price in this bill
    names = rng.sample(
        range(len(style.section_names)), k=min(len(style.section_names), sections[1])
    )
    for section in range(1, rng.randint(*sections) + 1):
        code = style.section_code(section)
        name = names[(section - 1) % len(names)]
        if lines and rng.random() < BLANK_BEFORE_SECTION:
            lines.append(Line(kind="blank", text=""))
        lines.append(
            Line(
                kind="section",
                text=style.section_format.format(code=code, name=style.section_names[name]),
                section=section,
                code=code if style.code_in_section_row else None,
            )
        )
        for item in range(1, rng.randint(*items) + 1):
            entry = style.catalogue[rng.choice(SECTION_ITEMS[name])]
            lines.append(_item(rng, style, entry, section, item, used, prices))
            if rng.random() < CONTINUATION:
                lines.append(Line(kind="text", text=rng.choice(style.continuations)))
        lines.append(
            Line(kind="subtotal", text=style.subtotal_format.format(code=code), section=section)
        )
    lines.append(Line(kind="grand_total", text=style.net_text))
    lines.append(Line(kind="tax", text=style.tax_text))
    lines.append(Line(kind="gross_total", text=style.gross_text))
    bill = Bill(style=style, lines=lines, title=title)
    recompute_totals(bill)
    return bill


def _item(
    rng: random.Random,
    style: Style,
    entry: tuple[str, str, str],
    section: int,
    item: int,
    used: set[tuple[str, int]],
    prices: dict[str, Decimal],
) -> Line:
    base, unit, scale = entry
    place = rng.randint(1, 99)
    while (base, place) in used:
        place = rng.randint(1, 99)
    used.add((base, place))
    if base not in prices:
        prices[base] = _price(rng, scale)
    quantity, price = _quantity(rng, scale), _priced(rng, prices[base])
    line = Line(
        kind="item",
        text=f"{base} ({style.place} {place})",
        section=section,
        code=style.item_code(section, item),
        quantity=quantity,
        unit=unit,
        unit_price=price,
        total=(quantity * price).quantize(CENT, rounding=ROUND_HALF_UP),
        scale=scale,
    )
    draw = rng.random()
    marked = None
    if draw < NOT_COUNTED:
        marked = rng.choice(style.not_counted)
        line.counted = False
    elif draw < NOT_COUNTED + RATE_ONLY:
        line.total, line.total_text, line.counted = None, style.rate_only, False
    elif style.counted_marked and draw < NOT_COUNTED + RATE_ONLY + COUNTED_MARKED:
        marked = rng.choice(style.counted_marked)
    if marked is not None:
        line.text = marked.format(text=line.text)
        line.contingency = marked in style.contingency_formats
    return line


def _only(bill: Bill, kind: str) -> Line:
    return next(line for line in bill.lines if line.kind == kind)


def recompute_totals(bill: Bill) -> None:
    """Totals as a spreadsheet sums them: from the item totals as written."""
    net = Decimal(0)
    for line in bill.lines:
        if line.kind == "subtotal":
            line.total = sum(
                (
                    item.total
                    for item in bill.lines
                    if item.kind == "item"
                    and item.counted
                    and item.section == line.section
                    and item.total is not None
                ),
                Decimal(0),
            )
            net += line.total
    tax = (net * bill.style.tax_rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    _only(bill, "grand_total").total = net
    _only(bill, "tax").total = tax
    _only(bill, "gross_total").total = net + tax


def corrupt(rng: random.Random, value: Decimal) -> Decimal:
    """A typing slip: two adjacent, different digits swapped (``1250.40`` -> ``1520.40``)."""
    digits = f"{value:.2f}"
    swaps = [
        i
        for i in range(len(digits) - 1)
        if digits[i].isdigit() and digits[i + 1].isdigit() and digits[i] != digits[i + 1]
    ]
    if not swaps:
        return value + 100
    i = rng.choice(swaps)
    return Decimal(digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :])


def not_a_number(quantity: Decimal, *, german: bool) -> str:
    """An OCR-style misread: a zero read as the letter O, or a stray letter appended."""
    text = format(quantity, "f").replace(".", "," if german else ".")
    return text.replace("0", "O", 1) if "0" in text else f"{text}O"


def _eligible(kind: ErrorKind, line: Line) -> bool:
    """A lump sum legitimately has no rate (the profile exempts it), so a missing rate is only
    an error on a measured item."""
    return not (kind is ErrorKind.MISSING_PRICE and line.scale == "lump_sum")


def inject(rng: random.Random, bill: Bill, kinds: Sequence[ErrorKind], prefix: str) -> None:
    """Inject one error of each kind (item-level first, then the totals are re-summed, then the
    total-level slips)."""
    item_kinds = [kind for kind in kinds if kind in ITEM_LEVEL]
    targets: list[Line] = []
    for kind in item_kinds:
        candidates = [
            line
            for line in bill.lines
            if line.plain_item and _eligible(kind, line) and line not in targets
        ]
        targets.append(rng.choice(candidates))
    number = 0

    def record(kind: ErrorKind, target: Line, change: str, related: list[Line]) -> None:
        nonlocal number
        number += 1
        bill.injections.append(
            _Injection(f"{prefix}-e{number}", kind, target, related=related, change=change)
        )

    for kind, target in zip(item_kinds, targets, strict=True):
        if kind is ErrorKind.LINE_TOTAL:
            assert target.total is not None
            wrong = corrupt(rng, target.total)
            record(kind, target, f"line total {target.total} written as {wrong}", [])
            target.total = wrong
        elif kind is ErrorKind.UNKNOWN_UNIT:
            unit = rng.choice(bill.style.unknown_units)
            record(kind, target, f"unit {target.unit} written as {unit}", [])
            target.unit = unit
        elif kind is ErrorKind.DUPLICATE_ROW:
            copy = replace(target)
            bill.lines.insert(bill.lines.index(target) + 1, copy)
            record(kind, copy, f"item {target.code} entered twice", [target])
        elif kind is ErrorKind.MISSING_PRICE:
            record(kind, target, f"rate {target.unit_price} left empty", [])
            target.unit_price = None
        elif kind is ErrorKind.INVALID_QUANTITY:
            assert isinstance(target.quantity, Decimal)
            text = not_a_number(target.quantity, german=bill.style.language == "de")
            record(kind, target, f"quantity {target.quantity} written as {text!r}", [])
            target.quantity = text
    recompute_totals(bill)

    net, tax, gross = _only(bill, "grand_total"), _only(bill, "tax"), _only(bill, "gross_total")
    for kind in kinds:
        if kind is ErrorKind.SUBTOTAL:
            target = rng.choice([line for line in bill.lines if line.kind == "subtotal"])
            assert target.total is not None
            wrong = corrupt(rng, target.total)
            record(kind, target, f"subtotal {target.total} written as {wrong}", [net])
            target.total = wrong
        elif kind is ErrorKind.NET_TOTAL:
            assert net.total is not None
            wrong = corrupt(rng, net.total)
            record(kind, net, f"net total {net.total} written as {wrong}", [tax, gross])
            net.total = wrong
        elif kind is ErrorKind.TAX:
            assert tax.total is not None
            assert net.total is not None
            wrong = corrupt(rng, tax.total)
            record(kind, tax, f"tax {tax.total} written as {wrong}", [])
            tax.total = wrong
            gross.total = net.total + wrong


def truths(bill: Bill) -> tuple[GroundTruth, ...]:
    result = []
    for injection in bill.injections:
        row = bill.row_of(injection.target)
        rows = {row, *(bill.row_of(line) for line in injection.related)}
        result.append(
            GroundTruth(
                error_id=injection.error_id,
                kind=injection.kind,
                row=row,
                field=ERROR_FIELD[injection.kind],
                rows=tuple(sorted(rows)),
                expected_rules=EXPECTED_RULES[injection.kind],
                change=injection.change,
            )
        )
    return tuple(result)


# Rendering ------------------------------------------------------------------------------------


def _values(line: Line) -> list[Decimal | str | None]:
    if line.kind == "section":
        return [line.code, line.text, None, None, None, None]
    if line.kind == "item":
        total = line.total_text if line.total_text is not None else line.total
        return [line.code, line.text, line.quantity, line.unit, line.unit_price, total]
    if line.kind == "blank":
        return [None] * 6
    if line.kind == "text":
        return [None, line.text, None, None, None, None]
    return [None, line.text, None, None, None, line.total]


def csv_number(value: Decimal, *, german: bool, amount: bool) -> str:
    if not amount and value == value.to_integral_value():
        return str(int(value))  # plain integers, no thousands separators (never ambiguous)
    text = f"{value:,.2f}"
    if german:
        return text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text if amount else text.replace(",", "")


def render_csv(bill: Bill) -> bytes:
    german = bill.style.language == "de"
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";" if german else ",", lineterminator="\r\n")
    for title in bill.title:
        writer.writerow([title, "", "", "", "", ""])
    writer.writerow(bill.style.header)
    for line in bill.lines:
        cells = []
        for column, value in enumerate(_values(line)):
            if isinstance(value, Decimal):
                cells.append(csv_number(value, german=german, amount=column >= 4))
            else:
                cells.append("" if value is None else value)
        writer.writerow(cells)
    return buffer.getvalue().encode("utf-8")


def render_xlsx(bill: Bill) -> bytes:
    workbook = Workbook()
    workbook.properties.creator = "Tabular Integrity Workbench synthetic benchmark"
    workbook.properties.created = workbook.properties.modified = WORKBOOK_TIMESTAMP
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "LV" if bill.style.language == "de" else "BoQ"
    for title in bill.title:
        sheet.append([title or None])
    sheet.append(list(bill.style.header))
    for line in bill.lines:
        sheet.append(_values(line))
        for column in (5, 6):  # rates and amounts; quantities keep the General format
            cell = sheet.cell(row=sheet.max_row, column=column)
            if isinstance(cell.value, Decimal):
                cell.number_format = "#,##0.00"
    return xlsx_bytes(workbook)


def xlsx_bytes(workbook: Workbook) -> bytes:
    """The workbook as XLSX bytes that depend only on its content.

    ``Workbook.save`` sets the modification time to now, and every ZIP member gets the time it
    was written. openpyxl's ``ExcelWriter`` writes the workbook with its own properties (here
    :data:`WORKBOOK_TIMESTAMP`) into an uncompressed archive; its members are then compressed
    into the final archive in the same order, each stamped with :data:`WORKBOOK_TIMESTAMP`."""
    written = io.BytesIO()
    ExcelWriter(workbook, ZipFile(written, "w", ZIP_STORED, allowZip64=True)).save()
    stamp = WORKBOOK_TIMESTAMP.timetuple()[:6]
    packed = io.BytesIO()
    with ZipFile(written) as source, ZipFile(packed, "w", ZIP_DEFLATED) as target:
        for member in source.infolist():
            info = ZipInfo(member.filename, date_time=stamp)
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3  # Unix, whatever platform runs the benchmark
            info.external_attr = _MEMBER_ATTRIBUTES
            target.writestr(info, source.read(member))
    return packed.getvalue()


def document(bill: Bill, *, name: str, file_format: str) -> SyntheticDocument:
    content = render_xlsx(bill) if file_format == "xlsx" else render_csv(bill)
    row_kinds = {bill.row_of(line): line.kind for line in bill.lines}
    return SyntheticDocument(
        name=f"{name}.{file_format}",
        language=bill.style.language,
        format=file_format,
        content=content,
        row_kinds=row_kinds,
        truths=truths(bill),
        contingency_and_hourly_rows=frozenset(
            bill.row_of(line) for line in bill.lines if line.kind == "item" and line.contingency
        ),
    )


Variant = Literal["standard", "boq"]
BOQ_SEED = 20261120  # the seed the boq checks are tuned on (plan step B1.4)
BOQ_MAX_ERRORS = 8  # the command line's default for the boq variant


@dataclass(frozen=True)
class BoqSettings:
    """The ``boq`` variant's bills (:mod:`app.evaluation.boq`). Shares are of all bills; the
    STLB-Bau keys, unit price components and the Positionsart column go into German bills."""

    positions: tuple[int, int] = (80, 1500)  # positions per bill, drawn log-uniformly
    english_share: float = 0.25
    buildings_share: float = 0.25  # bills repeated per building under Lose
    key_share: float = 0.25  # bills with a STLB-Bau column of synthetic keys
    component_share: float = 0.25  # bills with unit price components
    type_column_share: float = 0.5  # of the German bills: item kinds in a Positionsart column
    formats: tuple[str, ...] = ("xlsx",)


@dataclass(frozen=True)
class CorpusConfig:
    """``documents_per_variant`` is per language and format in the standard variant and the
    number of bills in the boq variant, which takes its languages, formats and sizes from
    ``boq`` instead of ``languages``, ``formats``, ``sections`` and ``items_per_section``."""

    seed: int = 20261119
    documents_per_variant: int = 25
    languages: tuple[str, ...] = ("en", "de")
    formats: tuple[str, ...] = FORMATS
    sections: tuple[int, int] = (2, 6)
    items_per_section: tuple[int, int] = (3, 25)
    max_errors: int = 3  # per document; 0 to max_errors, so some documents are clean
    variant: Variant = "standard"
    boq: BoqSettings = field(default_factory=BoqSettings)

    @property
    def kinds(self) -> tuple[ErrorKind, ...]:
        """The error kinds this variant plants."""
        return STANDARD_KINDS if self.variant == "standard" else tuple(ErrorKind)

    def describe(self) -> dict[str, object]:
        """The configuration as recorded in manifests and reports. The standard variant keeps
        the keys it always had, so its manifest stays the same for the same seed."""
        data = asdict(self)
        if self.variant == "standard":
            del data["variant"], data["boq"]
        else:
            for name in ("languages", "formats", "sections", "items_per_section"):
                del data[name]
        return data


def generate_corpus(config: CorpusConfig) -> list[SyntheticDocument]:
    """Documents for every language and format. Error kinds are dealt from a shuffled deck so
    every kind occurs about equally often."""
    if config.variant == "boq":
        # Imported here: app.evaluation.boq builds on this module.
        from app.evaluation.boq import generate_boq_corpus

        return generate_boq_corpus(config)
    rng = random.Random(config.seed)  # noqa: S311 - reproducible test data, not security
    deck: list[ErrorKind] = []
    documents = []
    for language in config.languages:
        style = STYLES[language]
        for file_format in config.formats:
            for index in range(1, config.documents_per_variant + 1):
                name = f"{language}-{file_format}-{index:03d}"
                bill = generate_bill(
                    rng, style, sections=config.sections, items=config.items_per_section
                )
                kinds: list[ErrorKind] = []
                for _ in range(rng.randint(0, config.max_errors)):
                    if not deck:
                        deck = list(STANDARD_KINDS)
                        rng.shuffle(deck)
                    kind = deck.pop()
                    if kind in kinds or (kind in EXCLUSIVE and EXCLUSIVE & set(kinds)):
                        deck.insert(0, kind)  # deal it to a later document
                        continue
                    kinds.append(kind)
                inject(rng, bill, kinds, prefix=name)
                documents.append(document(bill, name=name, file_format=file_format))
    return documents
