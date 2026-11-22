"""The ``boq`` corpus variant: bills that behave like real ones, with planted errors of all seven
anomaly types (plan step B1).

A bill has one Titel per trade (:data:`app.evaluation.prices.TRADES`), each with positions of
that trade's families only: similar positions that differ in one option, the same work once per
construction phase, Bedarfspositionen (with or without total, most of them repeating a normal
position of the same Titel) and alternatives right after their base position. A quarter of the
bills repeat the whole bill per building (Haus A, Haus B) under Lose, with quantities within
±30 % of each other; a quarter carry synthetic STLB-Bau keys; a quarter carry two to four unit
price components (EP-Anteile) that add up to the unit price; half of the German bills mark the
item kinds in a Positionsart column, the others in the text, the way the BoQ profile reads
them. Every second Positionsart column writes the names the GAEB import gives its item types
(Normalposition, Grundposition, Bedarfsposition mit GB, ...), the others the short codes of
spreadsheet bills (N, G, BmGB, BoGB, Wahl). OZ are GAEB-style (01.0010, or 01.02.0010 under
Lose). Unit prices come from :class:`app.evaluation.prices.PriceModel`: the same family and
options get the same unit price everywhere in the bill.

Errors (:func:`plant`) go into ordinary positions (kind normal), except
``high_contingency_price``. After planting, the changed positions' line totals are recomputed
(except for the kinds that plant a wrong line total) and every subtotal and total is summed again
from the line totals as written, so only the check named for a kind can find it. Each error is
recorded like in the standard variant: the cell holding it and every row where a correct
checker may report it, which for a changed price or quantity includes the position's identical
copies (a comparison of two copies cannot tell which one is wrong), for a copied position the
original, and for an item code moved to a higher Titel prefix the next position (whose code is
then lower than the one before it). The total-level kinds of the standard variant are planted
last, as there.

Same seed, same bytes, as in :mod:`app.evaluation.synthetic`.
"""

from __future__ import annotations

import csv
import io
import math
import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from functools import partial
from itertools import pairwise

from openpyxl import Workbook

from app.evaluation.prices import (
    CENT,
    OTHER_DIMENSION,
    TRADES,
    UNITS,
    UNKNOWN_UNITS,
    Family,
    Language,
    PriceModel,
    Trade,
    quantity,
    similar_quantity,
    split,
)
from app.evaluation.synthetic import (
    ERROR_FIELD,
    EXCLUSIVE,
    EXPECTED_RULES,
    WORKBOOK_TIMESTAMP,
    BoqSettings,
    CorpusConfig,
    ErrorKind,
    GroundTruth,
    SyntheticDocument,
    corrupt,
    csv_number,
    not_a_number,
    xlsx_bytes,
)

FAMILIES: dict[str, Family] = {f.family_id: f for trade in TRADES for f in trade.families}

# Item kinds (the GAEB codes of plan section 5) and how a Positionsart column writes them: as
# the short codes of spreadsheet bills, or by the names the GAEB import gives its item types
# (app.ingestion.gaeb.flatten.item_type). The boq profile reads both.
NORMAL, BASE = "normal", "base"
WITH_TOTAL, WITHOUT_TOTAL = "contingency_with_total", "contingency_without_total"
ALTERNATIVE = "alternative"
COUNTED = frozenset({NORMAL, BASE, WITH_TOTAL})
CONTINGENCY_TYPES = frozenset({WITH_TOTAL, WITHOUT_TOTAL})  # Bedarfspositionen
TYPE_CODES = {
    NORMAL: "N",
    BASE: "G",
    WITH_TOTAL: "BmGB",
    WITHOUT_TOTAL: "BoGB",
    ALTERNATIVE: "Wahl",
}
TYPE_NAMES = {
    NORMAL: "Normalposition",
    BASE: "Grundposition",
    WITH_TOTAL: "Bedarfsposition mit GB",
    WITHOUT_TOTAL: "Bedarfsposition ohne GB",
    ALTERNATIVE: "Wahlposition",
}

# Chances per position (of normal positions that get a counterpart) and per bill.
CONTINGENCY = 0.05
CONTINGENCY_WITH_TOTAL = 0.4  # of German contingencies; English bills mark only "without"
ALTERNATIVE_SHARE = 0.03
TITLE_BLOCK = 0.5
BLANK_BEFORE_SECTION = 0.3
MAX_PHASES = 6
POSITIONS_PER_TRADE = 40  # a bill of n positions has about n / 40 trades, at least 4
PROJECTS = ("Wohnanlage Nord", "Kita Am Park", "Bürogebäude B", "Schulzentrum Ost")

# The standard kinds that are planted after the totals are summed (as in the standard variant).
TOTAL_LEVEL = (ErrorKind.SUBTOTAL, ErrorKind.NET_TOTAL, ErrorKind.TAX)


@dataclass(frozen=True)
class BoqStyle:
    """How one language writes a bill of this variant."""

    language: Language
    headers: dict[str, str]
    tax_rate: Decimal
    titel: str
    los: str
    titel_total: str
    los_total: str
    net_text: str
    tax_text: str
    gross_text: str
    buildings: tuple[str, str]
    phase: str
    without_total: str
    with_total: str | None
    alternative: str
    title_lines: tuple[str, ...]
    code_in_section_row: bool

    def section_code(self, los: int | None, titel: int) -> str:
        if self.language == "de":
            return f"{titel:02d}" if los is None else f"{los:02d}.{titel:02d}"
        return str(titel) if los is None else f"{los}.{titel}"

    def los_code(self, los: int) -> str:
        return f"{los:02d}" if self.language == "de" else str(los)

    def item_code(self, section: str, number: int) -> str:
        return f"{section}.{number * 10:04d}" if self.language == "de" else f"{section}.{number}"


GERMAN = BoqStyle(
    language="de",
    headers={
        "code": "OZ",
        "type": "Positionsart",
        "text": "Kurztext",
        "key": "STLB-Bau",
        "quantity": "Menge",
        "unit": "ME",
        "unit_price": "EP",
        "total": "GP",
    },
    tax_rate=Decimal(19),
    titel="Titel {code} {name}",
    los="Los {code} {name}",
    titel_total="Summe Titel {code}",
    los_total="Summe Los {code}",
    net_text="Gesamtsumme netto",
    tax_text="zzgl. 19 % MwSt.",
    gross_text="Gesamtsumme brutto",
    buildings=("Haus A", "Haus B"),
    phase="{text}, Bauabschnitt {phase}",
    without_total="{text}, Bedarfsposition ohne GB",
    with_total="{text}, Bedarfsposition mit GB",
    alternative="Alternativposition: {text}",
    title_lines=("Leistungsverzeichnis {project}", "Projekt 2026-{number}"),
    code_in_section_row=True,
)
ENGLISH = BoqStyle(
    language="en",
    headers={
        "code": "Item",
        "text": "Description",
        "quantity": "Qty",
        "unit": "Unit",
        "unit_price": "Rate",
        "total": "Amount",
    },
    tax_rate=Decimal(20),
    titel="Section {code} {name}",
    los="Bill {code} {name}",
    titel_total="Subtotal section {code}",
    los_total="Subtotal bill {code}",
    net_text="Grand total",
    tax_text="VAT 20%",
    gross_text="Total incl. VAT",
    buildings=("Building A", "Building B"),
    phase="{text}, phase {phase}",
    without_total="{text}, not included in the total",
    with_total=None,
    alternative="Alternative: {text}",
    title_lines=("Bill of Quantities: {project}", "Project 2026-{number}"),
    code_in_section_row=False,
)
STYLES: dict[Language, BoqStyle] = {"de": GERMAN, "en": ENGLISH}


@dataclass(frozen=True)
class Features:
    """What one bill carries besides its positions."""

    language: Language
    buildings: bool = False
    keys: bool = False
    components: int = 0  # 0, or 2 to 4 component columns
    type_column: bool = False
    type_names: bool = False  # the Positionsart column writes TYPE_NAMES instead of TYPE_CODES


@dataclass(eq=False)
class BoqLine:
    """One row below the header; ``kind`` is the row kind the generator meant. Compared by
    identity, so a copied position is a different line."""

    kind: str
    text: str = ""
    code: str | None = None
    section: str | None = None  # Titel code of items and Titel rows; Los code of Los rows
    los: str | None = None
    quantity: Decimal | str | None = None  # a str only when an invalid number was planted
    unit: str | None = None  # unit id (app.evaluation.prices.UNITS), or the text as written
    unit_text: str | None = None  # the unit as written when it is not a catalogue unit
    unit_price: Decimal | None = None
    total: Decimal | None = None
    item_type: str = NORMAL
    key: str | None = None
    components: tuple[Decimal, ...] = ()
    family: str | None = None
    combo: tuple[int, ...] = ()
    phase: int | None = None

    @property
    def counted(self) -> bool:
        return self.item_type in COUNTED

    @property
    def plain(self) -> bool:
        """An ordinary position: the only kind errors are planted into (but one)."""
        return self.kind == "item" and self.item_type == NORMAL

    @property
    def identity(self) -> tuple[str | None, tuple[int, ...], int | None]:
        """The same work: equal for a position's copies in other buildings and for a
        Bedarfsposition that repeats it."""
        return (self.family, self.combo, self.phase)

    @property
    def family_spec(self) -> Family:
        assert self.family is not None
        return FAMILIES[self.family]


@dataclass
class _Planted:
    error_id: str
    kind: ErrorKind
    target: BoqLine
    field: str | None
    related: list[BoqLine]
    change: str


@dataclass
class BoqBill:
    style: BoqStyle
    features: Features
    lines: list[BoqLine]
    title: list[str] = field(default_factory=list)
    planted: list[_Planted] = field(default_factory=list)

    @property
    def header_row(self) -> int:
        return len(self.title) + 1

    @property
    def columns(self) -> list[str]:
        german = self.style.language == "de"
        columns = ["code"]
        if german and self.features.type_column:
            columns.append("type")
        columns.append("text")
        if german and self.features.keys:
            columns.append("key")
        columns += ["quantity", "unit"]
        columns += [f"component_{i}" for i in range(1, self.features.components + 1)]
        return [*columns, "unit_price", "total"]

    def header(self, column: str) -> str:
        if column.startswith("component_"):
            return f"EP-Anteil {column.rsplit('_', 1)[1]}"
        return self.style.headers[column]

    def row_of(self, line: BoqLine) -> int:
        index = next(i for i, other in enumerate(self.lines) if other is line)
        return self.header_row + 1 + index

    def items(self) -> list[BoqLine]:
        return [line for line in self.lines if line.kind == "item"]

    def copies(self, line: BoqLine) -> list[BoqLine]:
        """The other positions of the same work (see :attr:`BoqLine.identity`)."""
        return [
            other
            for other in self.items()
            if other is not line and other.family is not None and other.identity == line.identity
        ]

    def identical(self, line: BoqLine) -> list[BoqLine]:
        """Copies with the same text and unit: what a comparison of identical positions sees."""
        return [
            other
            for other in self.copies(line)
            if other.text == line.text and other.unit == line.unit
        ]

    def section_items(self, section: str | None) -> list[BoqLine]:
        return [line for line in self.items() if line.section == section]

    def titel_rows(self) -> list[BoqLine]:
        return [line for line in self.lines if line.kind == "section" and line.los != line.section]


def _text(style: BoqStyle, family: Family, combo: tuple[int, ...], phase: int | None) -> str:
    text = family.text(combo, style.language)
    return text if phase is None else style.phase.format(text=text, phase=phase)


@dataclass
class _Spec:
    """A position before it is written: what the copies in another building repeat."""

    family: Family
    combo: tuple[int, ...]
    phase: int | None
    item_type: str
    quantity: Decimal


def _titel_specs(rng: random.Random, trade: Trade, count: int) -> list[_Spec]:
    """``count`` positions of the trade (fewer when its families run out): random families and
    options, located work at most once per construction phase, ordered by family."""
    drawn: Counter[tuple[int, tuple[int, ...]]] = Counter()
    families = trade.families
    for _ in range(count):
        for _attempt in range(20):
            index = rng.randrange(len(families))
            family = families[index]
            combo = rng.choice(family.combos())
            limit = MAX_PHASES if family.located else 1
            if drawn[(index, combo)] < limit:
                drawn[(index, combo)] += 1
                break
    specs: list[_Spec] = []
    for (index, combo), times in sorted(drawn.items()):
        family = families[index]
        for phase in range(1, times + 1):
            specs.append(
                _Spec(family, combo, phase if times > 1 else None, NORMAL, quantity(rng, family))
            )
    return _with_kinds(rng, specs)


def _with_kinds(rng: random.Random, specs: list[_Spec]) -> list[_Spec]:
    """Bedarfspositionen after the position they repeat, alternatives (with other options of
    the same family) after their base position. Lump sums get neither."""
    used = {(spec.family.family_id, spec.combo) for spec in specs}
    result: list[_Spec] = []
    for spec in specs:
        result.append(spec)
        if spec.family.scale == "lump_sum":
            continue
        draw = rng.random()
        if draw < CONTINGENCY:
            share = Decimal(f"{rng.uniform(0.1, 0.4):.6f}")
            small = similar_quantity(rng, spec.family, spec.quantity * share)
            kind = WITH_TOTAL if rng.random() < CONTINGENCY_WITH_TOTAL else WITHOUT_TOTAL
            result.append(_Spec(spec.family, spec.combo, spec.phase, kind, small))
        elif draw < CONTINGENCY + ALTERNATIVE_SHARE:
            others = [
                combo
                for combo in spec.family.combos()
                if (spec.family.family_id, combo) not in used
                and sum(a != b for a, b in zip(combo, spec.combo, strict=True)) == 1
            ]
            if others:
                combo = rng.choice(others)
                used.add((spec.family.family_id, combo))
                spec.item_type = BASE
                result.append(_Spec(spec.family, combo, spec.phase, ALTERNATIVE, spec.quantity))
    return result


def _position(
    bill: BoqBill, model: _BillPrices, rng: random.Random, spec: _Spec, section: str, number: int
) -> BoqLine:
    style, features = bill.style, bill.features
    if spec.item_type == WITH_TOTAL and style.with_total is None:
        spec.item_type = WITHOUT_TOTAL
    text = _text(style, spec.family, spec.combo, spec.phase)
    if not features.type_column:
        if spec.item_type == WITHOUT_TOTAL:
            text = style.without_total.format(text=text)
        elif spec.item_type == WITH_TOTAL:
            assert style.with_total is not None
            text = style.with_total.format(text=text)
        elif spec.item_type == ALTERNATIVE:
            text = style.alternative.format(text=text)
    price = model.unit_price(spec.family, spec.combo)
    components: tuple[Decimal, ...] = ()
    if features.components:
        components = model.components(spec.family, spec.combo, features.components)
    return BoqLine(
        kind="item",
        text=text,
        code=style.item_code(section, number),
        section=section,
        quantity=spec.quantity,
        unit=spec.family.unit.unit_id,
        unit_price=price,
        total=_line_total(spec.quantity, price),
        item_type=spec.item_type,
        key=spec.family.key(spec.combo),
        components=components,
        family=spec.family.family_id,
        combo=spec.combo,
        phase=spec.phase,
    )


def _line_total(quantity: Decimal, price: Decimal) -> Decimal:
    return (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)


class _BillPrices(PriceModel):
    """The price model plus the unit price components of the bill (the same split for the same
    family and options)."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(rng)
        self._splits: dict[tuple[str, tuple[int, ...]], tuple[Decimal, ...]] = {}
        self._split_rng = rng

    def components(self, family: Family, combo: tuple[int, ...], parts: int) -> tuple[Decimal, ...]:
        key = (family.family_id, combo)
        if key not in self._splits:
            self._splits[key] = split(self._split_rng, self.unit_price(family, combo), parts)
        return self._splits[key]


def generate_bill(rng: random.Random, features: Features, positions: int) -> BoqBill:
    """A bill of about ``positions`` positions (per building: half as many each)."""
    style = STYLES[features.language]
    bill = BoqBill(style=style, features=features, lines=[])
    if rng.random() < TITLE_BLOCK:
        project, number = rng.choice(PROJECTS), rng.randint(100, 999)
        bill.title = [line.format(project=project, number=number) for line in style.title_lines]
        bill.title.append("")
    model = _BillPrices(rng)
    count = min(len(TRADES), max(4, round(positions / POSITIONS_PER_TRADE)))
    trades = [TRADES[i] for i in sorted(rng.sample(range(len(TRADES)), count))]
    buildings = 2 if features.buildings else 1
    per_titel = positions / buildings / count
    specs = [
        _titel_specs(rng, trade, max(3, round(per_titel * rng.uniform(0.7, 1.3))))
        for trade in trades
    ]
    for building in range(1, buildings + 1):
        los = building if features.buildings else None
        if los is not None:
            if building > 1:
                specs = [[_again(rng, spec) for spec in titel] for titel in specs]
            code = style.los_code(los)
            _blank(rng, bill)
            name = style.buildings[building - 1]
            bill.lines.append(
                BoqLine(
                    kind="section",
                    text=style.los.format(code=code, name=name),
                    code=code if style.code_in_section_row else None,
                    section=code,
                    los=code,
                )
            )
        for index, (trade, titel) in enumerate(zip(trades, specs, strict=True), start=1):
            section = style.section_code(los, index)
            los_code = style.los_code(los) if los is not None else None
            _blank(rng, bill)
            bill.lines.append(
                BoqLine(
                    kind="section",
                    text=style.titel.format(code=section, name=trade.name(style.language)),
                    code=section if style.code_in_section_row else None,
                    section=section,
                    los=los_code,
                )
            )
            for number, spec in enumerate(titel, start=1):
                line = _position(bill, model, rng, spec, section, number)
                line.los = los_code
                bill.lines.append(line)
            bill.lines.append(
                BoqLine(
                    kind="subtotal",
                    text=style.titel_total.format(code=section),
                    section=section,
                    los=los_code,
                )
            )
        if los is not None:
            code = style.los_code(los)
            bill.lines.append(
                BoqLine(kind="subtotal", text=style.los_total.format(code=code), los=code)
            )
    bill.lines.append(BoqLine(kind="grand_total", text=style.net_text))
    bill.lines.append(BoqLine(kind="tax", text=style.tax_text))
    bill.lines.append(BoqLine(kind="gross_total", text=style.gross_text))
    recompute_totals(bill)
    return bill


def _again(rng: random.Random, spec: _Spec) -> _Spec:
    """The same position in the next building."""
    return replace(spec, quantity=similar_quantity(rng, spec.family, spec.quantity))


def _blank(rng: random.Random, bill: BoqBill) -> None:
    if bill.lines and rng.random() < BLANK_BEFORE_SECTION:
        bill.lines.append(BoqLine(kind="blank"))


def _in_section(section: str, item: BoqLine) -> bool:
    return item.section == section


def _in_los(los: str | None, item: BoqLine) -> bool:
    return item.los == los


def _only(bill: BoqBill, kind: str) -> BoqLine:
    return next(line for line in bill.lines if line.kind == kind)


def recompute_totals(bill: BoqBill) -> None:
    """Every total as a spreadsheet sums it: from the line totals as written."""

    def summed(selected: Callable[[BoqLine], bool]) -> Decimal:
        return sum(
            (
                line.total
                for line in bill.items()
                if line.counted and line.total is not None and selected(line)
            ),
            Decimal(0),
        )

    for line in bill.lines:
        if line.kind == "subtotal" and line.section is not None:
            line.total = summed(partial(_in_section, line.section))
        elif line.kind == "subtotal":
            line.total = summed(partial(_in_los, line.los))
    net = summed(lambda item: True)
    tax = (net * bill.style.tax_rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    _only(bill, "grand_total").total = net
    _only(bill, "tax").total = tax
    _only(bill, "gross_total").total = net + tax


# Planting -------------------------------------------------------------------------------------

Planter = Callable[["_Context", BoqLine], "_Planted | None"]


@dataclass
class _Context:
    rng: random.Random
    bill: BoqBill
    prefix: str
    used: set[int] = field(default_factory=set)  # ids of lines an earlier error touched
    number: int = 0

    def record(
        self,
        kind: ErrorKind,
        target: BoqLine,
        change: str,
        *,
        related: Sequence[BoqLine] = (),
        field_id: str | None = None,
        default_field: bool = True,
    ) -> _Planted:
        self.number += 1
        planted = _Planted(
            error_id=f"{self.prefix}-e{self.number}",
            kind=kind,
            target=target,
            field=ERROR_FIELD[kind] if default_field else field_id,
            related=list(related),
            change=change,
        )
        self.bill.planted.append(planted)
        for line in (target, *related, *self.bill.copies(target)):
            self.used.add(id(line))
        return planted

    def free(self, line: BoqLine) -> bool:
        return id(line) not in self.used and not any(
            id(copy) in self.used for copy in self.bill.copies(line)
        )


def _amount(value: Decimal) -> str:
    return format(value, "f")


def _reprice(line: BoqLine, price: Decimal) -> None:
    line.unit_price = price
    assert isinstance(line.quantity, Decimal)
    line.total = _line_total(line.quantity, price)


def _requantify(line: BoqLine, value: Decimal) -> None:
    line.quantity = value
    assert line.unit_price is not None
    line.total = _line_total(value, line.unit_price)


def _measured(line: BoqLine) -> bool:
    return line.family is not None and line.family_spec.scale != "lump_sum"


def _swap(value: Decimal, rng: random.Random) -> Decimal | None:
    """Two adjacent, different digits swapped, or None when no two adjacent digits differ."""
    digits = f"{value:.2f}"
    if not any(a.isdigit() and b.isdigit() and a != b for a, b in pairwise(digits)):
        return None
    return corrupt(rng, value)


def _price_decimal_slip(ctx: _Context, line: BoqLine) -> _Planted | None:
    if not _measured(line):
        return None
    assert line.unit_price is not None
    factor = ctx.rng.choice((Decimal(10), Decimal("0.1"), Decimal(100)))
    wrong = (line.unit_price * factor).quantize(CENT, rounding=ROUND_HALF_UP)
    if wrong <= 0:
        return None
    change = f"unit price {_amount(line.unit_price)} written as {_amount(wrong)} (× {factor})"
    planted = ctx.record(ErrorKind.PRICE_DECIMAL_SLIP, line, change, related=ctx.bill.copies(line))
    _reprice(line, wrong)
    return planted


def _price_digit_swap(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert line.unit_price is not None
    if not _measured(line):
        return None
    wrong = _swap(line.unit_price, ctx.rng)
    if wrong is None or wrong <= 0:
        return None
    change = f"unit price {_amount(line.unit_price)} written as {_amount(wrong)}"
    planted = ctx.record(ErrorKind.PRICE_DIGIT_SWAP, line, change, related=ctx.bill.copies(line))
    _reprice(line, wrong)
    return planted


def _inconsistent_rate(ctx: _Context, line: BoqLine) -> _Planted | None:
    if not ctx.bill.identical(line):
        return None
    assert line.unit_price is not None
    if ctx.rng.random() < 0.5:
        factor = Decimal(f"{ctx.rng.uniform(1.25, 1.60):.4f}")
    else:
        factor = Decimal(f"{ctx.rng.uniform(0.60, 0.75):.4f}")
    wrong = (line.unit_price * factor).quantize(CENT, rounding=ROUND_HALF_UP)
    change = (
        f"unit price {_amount(line.unit_price)} written as {_amount(wrong)} in one of "
        f"{len(ctx.bill.identical(line)) + 1} identical positions"
    )
    planted = ctx.record(ErrorKind.INCONSISTENT_RATE, line, change, related=ctx.bill.copies(line))
    _reprice(line, wrong)
    return planted


def _wrong_rate_copied(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert line.unit_price is not None
    price = line.unit_price
    sources = [
        other
        for other in ctx.bill.items()
        if other.family not in (None, line.family)
        and other.unit_price is not None
        and other.unit_price > 0
        and abs(math.log(other.unit_price / price)) >= math.log(1.5)
    ]
    if not sources:
        return None
    source = ctx.rng.choice(sources)
    assert source.unit_price is not None
    change = (
        f"unit price {_amount(price)} replaced by {_amount(source.unit_price)}, the unit price "
        f"of position {source.code}"
    )
    planted = ctx.record(ErrorKind.WRONG_RATE_COPIED, line, change, related=ctx.bill.copies(line))
    _reprice(line, source.unit_price)
    return planted


def _placeholder_price(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert line.unit_price is not None
    wrong = ctx.rng.choice((Decimal("0.01"), Decimal("0.00")))
    change = f"unit price {_amount(line.unit_price)} written as {_amount(wrong)}"
    planted = ctx.record(ErrorKind.PLACEHOLDER_PRICE, line, change, related=ctx.bill.copies(line))
    _reprice(line, wrong)
    return planted


def _quantity_slip(ctx: _Context, line: BoqLine) -> _Planted | None:
    if not _measured(line) or not ctx.bill.identical(line):
        return None
    assert isinstance(line.quantity, Decimal)
    factors = [Decimal(10), Decimal(100), Decimal(1000)]
    if line.family_spec.scale not in ("count", "time"):  # whole numbers stay whole
        factors += [Decimal("0.1"), Decimal("0.01"), Decimal("0.001")]
    factor = ctx.rng.choice(factors)
    wrong = line.quantity * factor
    change = f"quantity {_amount(line.quantity)} written as {_amount(wrong)} (× {factor})"
    related = ctx.bill.copies(line)
    planted = ctx.record(ErrorKind.QUANTITY_DECIMAL_SLIP, line, change, related=related)
    _requantify(line, wrong)
    return planted


def _quantity_unit_slip(ctx: _Context, line: BoqLine) -> _Planted | None:
    if line.unit != "m" or not ctx.bill.identical(line):
        return None
    assert isinstance(line.quantity, Decimal)
    factor, unit = ctx.rng.choice(((Decimal(100), "cm"), (Decimal(1000), "mm")))
    wrong = line.quantity * factor
    change = f"quantity {_amount(line.quantity)} m entered in {unit} as {_amount(wrong)}"
    planted = ctx.record(ErrorKind.QUANTITY_UNIT_SLIP, line, change, related=ctx.bill.copies(line))
    _requantify(line, wrong)
    return planted


def _price_per_wrong_unit(ctx: _Context, line: BoqLine) -> _Planted | None:
    thickness = line.family_spec.thickness_of(line.combo) if line.family else None
    if line.unit != "m3" or thickness is None:
        return None
    assert line.unit_price is not None
    wrong = (line.unit_price * thickness).quantize(CENT, rounding=ROUND_HALF_UP)
    change = (
        f"unit price {_amount(line.unit_price)} per m3 written as {_amount(wrong)}, the price "
        f"per m2 of a {_amount(thickness)} m thick part"
    )
    related = ctx.bill.copies(line)
    planted = ctx.record(ErrorKind.PRICE_PER_WRONG_UNIT, line, change, related=related)
    _reprice(line, wrong)
    return planted


def _wrong_unit(ctx: _Context, line: BoqLine) -> _Planted | None:
    if line.unit not in OTHER_DIMENSION:
        return None
    other = OTHER_DIMENSION[line.unit]
    language = ctx.bill.style.language
    change = (
        f"unit {UNITS[line.unit].text(language)} written as {UNITS[other].text(language)}, "
        "quantity and unit price kept"
    )
    planted = ctx.record(ErrorKind.WRONG_UNIT, line, change, related=ctx.bill.copies(line))
    line.unit = other
    return planted


def _next_code(bill: BoqBill, section: str) -> str:
    numbers = [_number(line.code) for line in bill.section_items(section)]
    step = 10 if bill.style.language == "de" else 1
    return bill.style.item_code(section, (max(numbers, default=0) // step) + 1)


def _number(code: str | None) -> int:
    assert code is not None
    return int(code.rsplit(".", 1)[1])


def _other_titel(ctx: _Context, line: BoqLine, *, lower_first: bool) -> BoqLine | None:
    """Another Titel of the same Los (a lower one first when asked)."""
    titels = [
        row for row in ctx.bill.titel_rows() if row.los == line.los and row.section != line.section
    ]
    if not titels:
        return None
    if lower_first:
        lower = [row for row in titels if (row.section or "") < (line.section or "")]
        if lower:
            return ctx.rng.choice(lower)
    return ctx.rng.choice(titels)


def _end_of_section(bill: BoqBill, section: str) -> int:
    """The index of the subtotal that closes ``section`` (insert before it)."""
    return next(
        i
        for i, line in enumerate(bill.lines)
        if line.kind == "subtotal" and line.section == section
    )


def _misplaced_position(ctx: _Context, line: BoqLine) -> _Planted | None:
    bill = ctx.bill
    if len([item for item in bill.section_items(line.section) if item.plain]) < 2:
        return None
    titel = _other_titel(ctx, line, lower_first=False)
    if titel is None or titel.section is None:
        return None
    old = line.code
    bill.lines.remove(line)
    line.code = _next_code(bill, titel.section)
    line.section = titel.section
    bill.lines.insert(_end_of_section(bill, titel.section), line)
    change = f"position {old} moved into Titel {titel.section} as {line.code}"
    return ctx.record(ErrorKind.MISPLACED_POSITION, line, change)


def _code_outside_section(ctx: _Context, line: BoqLine) -> _Planted | None:
    bill = ctx.bill
    titel = _other_titel(ctx, line, lower_first=True)
    if titel is None or titel.section is None:
        return None
    number = _number(line.code)
    step = 10 if bill.style.language == "de" else 1
    taken = {_number(item.code) for item in bill.section_items(titel.section)}
    if number in taken:
        number = (max(taken) // step + 1) * step
    code = bill.style.item_code(titel.section, number // step)
    related: list[BoqLine] = []
    if (titel.section or "") > (line.section or ""):  # the next code is then lower than this one
        siblings = bill.section_items(line.section)
        following = siblings.index(line) + 1
        if following < len(siblings):
            related.append(siblings[following])
    change = f"item code {line.code} written as {code} (the prefix of Titel {titel.section})"
    planted = ctx.record(ErrorKind.CODE_OUTSIDE_SECTION, line, change, related=related)
    line.code = code
    return planted


def _line_total_slip(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert line.total is not None
    wrong = line.total * 10
    if wrong == line.total:
        return None
    change = f"line total {_amount(line.total)} written as {_amount(wrong)} (10 times)"
    planted = ctx.record(ErrorKind.LINE_TOTAL_SLIP, line, change)
    line.total = wrong
    return planted


def _component_sum_error(ctx: _Context, line: BoqLine) -> _Planted | None:
    candidates = [i for i, value in enumerate(line.components) if value >= 1]
    if not candidates:
        return None
    index = ctx.rng.choice(candidates)
    value = line.components[index]
    sign = 1 if ctx.rng.random() < 0.5 else -1
    factor = 1 + sign * Decimal(f"{ctx.rng.uniform(0.01, 0.20):.4f}")
    wrong = (value * factor).quantize(CENT, rounding=ROUND_HALF_UP)
    if wrong == value:
        wrong = value + CENT * sign
    change = f"unit price component {index + 1} {_amount(value)} written as {_amount(wrong)}"
    planted = ctx.record(
        ErrorKind.COMPONENT_SUM_ERROR,
        line,
        change,
        field_id=f"unit_price_component_{index + 1}",
        default_field=False,
    )
    line.components = (*line.components[:index], wrong, *line.components[index + 1 :])
    return planted


def _copy_at_end(ctx: _Context, line: BoqLine, text: str, amount: Decimal) -> BoqLine:
    bill = ctx.bill
    assert line.section is not None
    assert line.unit_price is not None
    copy = replace(
        line,
        text=text,
        code=_next_code(bill, line.section),
        quantity=amount,
        total=_line_total(amount, line.unit_price),
        phase=line.phase,
    )
    bill.lines.insert(_end_of_section(bill, line.section), copy)
    return copy


def _duplicate_position(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert isinstance(line.quantity, Decimal)
    copy = _copy_at_end(ctx, line, line.text, line.quantity)
    change = f"position {line.code} entered again as {copy.code}"
    return ctx.record(ErrorKind.DUPLICATE_POSITION, copy, change, related=[line])


_ABBREVIATIONS: dict[Language, tuple[tuple[str, str], ...]] = {
    "de": (
        ("liefern und verlegen", "liefern u. verlegen"),
        ("einbauen und verdichten", "einbauen u. verdichten"),
        ("Stahlbeton", "StB"),
        ("Mauerwerk", "MW"),
        ("Durchmesser", "Ø"),
        ("Dicke", "D."),
        ("Höhe", "H."),
        ("Breite", "B."),
        ("Tiefe", "T."),
    ),
    "en": (
        ("supply and lay", "supply & lay"),
        ("supply and fix", "supply & fix"),
        ("Reinforced concrete", "RC"),
        ("diameter", "dia."),
        ("thick", "thk"),
        ("Internal", "Int."),
        ("External", "Ext."),
    ),
}


def near_text(rng: random.Random, text: str, language: Language) -> str:
    """A small change that keeps the numbers: two comma-separated parts in the other order, an
    abbreviation, or two adjacent letters swapped (a typo)."""
    changes: list[str] = []
    parts = text.split(", ")
    if len(parts) > 1:
        i = rng.randrange(len(parts) - 1)
        parts[i], parts[i + 1] = parts[i + 1], parts[i]
        changes.append(", ".join(parts))
    changes += [
        text.replace(long, short, 1) for long, short in _ABBREVIATIONS[language] if long in text
    ]
    letters = [
        i
        for i in range(len(text) - 1)
        if text[i].isalpha() and text[i + 1].isalpha() and text[i] != text[i + 1]
    ]
    if letters:
        i = rng.choice(letters)
        changes.append(text[:i] + text[i + 1] + text[i] + text[i + 2 :])
    candidates = [change for change in changes if change != text]
    return rng.choice(candidates)


def _near_duplicate_position(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert isinstance(line.quantity, Decimal)
    text = near_text(ctx.rng, line.text, ctx.bill.style.language)
    amount = line.quantity
    if ctx.rng.random() < 0.5 and line.family_spec.scale != "lump_sum":
        factor = Decimal(f"{ctx.rng.uniform(0.9, 1.1):.4f}")
        places = Decimal(1) if line.family_spec.scale in ("count", "time") else CENT
        if line.family_spec.scale == "mass":
            places = Decimal("0.001")
        amount = max(places, (amount * factor).quantize(places, rounding=ROUND_HALF_UP))
    copy = _copy_at_end(ctx, line, text, amount)
    change = f"position {line.code} entered again as {copy.code}: {text!r}, quantity {amount}"
    return ctx.record(ErrorKind.NEAR_DUPLICATE_POSITION, copy, change, related=[line])


def _high_contingency_price(ctx: _Context, line: BoqLine) -> _Planted | None:
    """``line`` is a Bedarfsposition without total that repeats a normal position."""
    counterparts = [copy for copy in ctx.bill.copies(line) if copy.plain]
    if not counterparts:
        return None
    assert line.unit_price is not None
    factor = Decimal(f"{ctx.rng.uniform(2.0, 3.0):.4f}")
    wrong = (line.unit_price * factor).quantize(CENT, rounding=ROUND_HALF_UP)
    change = (
        f"unit price {_amount(line.unit_price)} of a Bedarfsposition without total written as "
        f"{_amount(wrong)} ({factor} times its normal position {counterparts[0].code})"
    )
    related = ctx.bill.copies(line)
    planted = ctx.record(ErrorKind.HIGH_CONTINGENCY_PRICE, line, change, related=related)
    _reprice(line, wrong)
    return planted


# The standard kinds, planted as in the standard variant ------------------------------------------


def _std_line_total(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert line.total is not None
    wrong = corrupt(ctx.rng, line.total)
    change = f"line total {_amount(line.total)} written as {_amount(wrong)}"
    planted = ctx.record(ErrorKind.LINE_TOTAL, line, change)
    line.total = wrong
    return planted


def _std_unknown_unit(ctx: _Context, line: BoqLine) -> _Planted | None:
    language = ctx.bill.style.language
    unit = ctx.rng.choice(UNKNOWN_UNITS[language])
    assert line.unit is not None
    change = f"unit {UNITS[line.unit].text(language)} written as {unit}"
    planted = ctx.record(ErrorKind.UNKNOWN_UNIT, line, change)
    line.unit, line.unit_text = None, unit
    return planted


def _std_duplicate_row(ctx: _Context, line: BoqLine) -> _Planted | None:
    copy = replace(line)
    ctx.bill.lines.insert(ctx.bill.lines.index(line) + 1, copy)
    return ctx.record(
        ErrorKind.DUPLICATE_ROW, copy, f"position {line.code} entered twice", related=[line]
    )


def _std_missing_price(ctx: _Context, line: BoqLine) -> _Planted | None:
    if not _measured(line) or line.components:
        return None
    assert line.unit_price is not None
    planted = ctx.record(
        ErrorKind.MISSING_PRICE, line, f"unit price {_amount(line.unit_price)} left empty"
    )
    line.unit_price = None
    return planted


def _std_invalid_quantity(ctx: _Context, line: BoqLine) -> _Planted | None:
    assert isinstance(line.quantity, Decimal)
    text = not_a_number(line.quantity, german=ctx.bill.style.language == "de")
    change = f"quantity {_amount(line.quantity)} written as {text!r}"
    planted = ctx.record(ErrorKind.INVALID_QUANTITY, line, change)
    line.quantity = text
    return planted


PLANTERS: dict[ErrorKind, Planter] = {
    ErrorKind.LINE_TOTAL: _std_line_total,
    ErrorKind.UNKNOWN_UNIT: _std_unknown_unit,
    ErrorKind.DUPLICATE_ROW: _std_duplicate_row,
    ErrorKind.MISSING_PRICE: _std_missing_price,
    ErrorKind.INVALID_QUANTITY: _std_invalid_quantity,
    ErrorKind.PRICE_DECIMAL_SLIP: _price_decimal_slip,
    ErrorKind.PRICE_DIGIT_SWAP: _price_digit_swap,
    ErrorKind.INCONSISTENT_RATE: _inconsistent_rate,
    ErrorKind.WRONG_RATE_COPIED: _wrong_rate_copied,
    ErrorKind.PLACEHOLDER_PRICE: _placeholder_price,
    ErrorKind.HIGH_CONTINGENCY_PRICE: _high_contingency_price,
    ErrorKind.QUANTITY_DECIMAL_SLIP: _quantity_slip,
    ErrorKind.QUANTITY_UNIT_SLIP: _quantity_unit_slip,
    ErrorKind.PRICE_PER_WRONG_UNIT: _price_per_wrong_unit,
    ErrorKind.WRONG_UNIT: _wrong_unit,
    ErrorKind.MISPLACED_POSITION: _misplaced_position,
    ErrorKind.CODE_OUTSIDE_SECTION: _code_outside_section,
    ErrorKind.LINE_TOTAL_SLIP: _line_total_slip,
    ErrorKind.COMPONENT_SUM_ERROR: _component_sum_error,
    ErrorKind.DUPLICATE_POSITION: _duplicate_position,
    ErrorKind.NEAR_DUPLICATE_POSITION: _near_duplicate_position,
}


def _targets(bill: BoqBill, kind: ErrorKind) -> list[BoqLine]:
    """The positions an error of ``kind`` may go into (before the planter's own checks)."""
    if kind is ErrorKind.HIGH_CONTINGENCY_PRICE:
        return [line for line in bill.items() if line.item_type == WITHOUT_TOTAL]
    return [line for line in bill.items() if line.plain]


def plant(rng: random.Random, bill: BoqBill, kinds: Sequence[ErrorKind], prefix: str) -> None:
    """Plant one error of each kind (position-level kinds first, then the totals are summed
    again, then the total-level kinds). A kind that finds no position it fits is left out."""
    ctx = _Context(rng=rng, bill=bill, prefix=prefix)
    for kind in kinds:
        if kind in TOTAL_LEVEL:
            continue
        candidates = [line for line in _targets(bill, kind) if ctx.free(line)]
        rng.shuffle(candidates)
        for line in candidates:
            if PLANTERS[kind](ctx, line) is not None:
                break
    recompute_totals(bill)
    net, tax, gross = _only(bill, "grand_total"), _only(bill, "tax"), _only(bill, "gross_total")
    for kind in kinds:
        if kind is ErrorKind.SUBTOTAL:
            target = rng.choice(
                [line for line in bill.lines if line.kind == "subtotal" and line.section]
            )
            assert target.total is not None
            wrong = corrupt(rng, target.total)
            enclosing = [
                line
                for line in bill.lines
                if line.kind == "subtotal"
                and line.section is None
                and line.los == target.los
                and target.los is not None
            ]
            change = f"subtotal {_amount(target.total)} written as {_amount(wrong)}"
            ctx.record(kind, target, change, related=[*enclosing, net])
            target.total = wrong
        elif kind is ErrorKind.NET_TOTAL:
            assert net.total is not None
            wrong = corrupt(rng, net.total)
            change = f"net total {_amount(net.total)} written as {_amount(wrong)}"
            ctx.record(kind, net, change, related=[tax, gross])
            net.total = wrong
        elif kind is ErrorKind.TAX:
            assert tax.total is not None
            assert net.total is not None
            wrong = corrupt(rng, tax.total)
            ctx.record(kind, tax, f"tax {_amount(tax.total)} written as {_amount(wrong)}")
            tax.total = wrong
            gross.total = net.total + wrong


def eligible(bill: BoqBill, kind: ErrorKind) -> bool:
    """Whether the clean bill has the structure an error of ``kind`` needs."""
    items = [line for line in bill.items() if line.plain]
    if kind is ErrorKind.HIGH_CONTINGENCY_PRICE:
        return any(
            line.item_type == WITHOUT_TOTAL and any(copy.plain for copy in bill.copies(line))
            for line in bill.items()
        )
    if kind in (ErrorKind.INCONSISTENT_RATE, ErrorKind.QUANTITY_DECIMAL_SLIP):
        return any(bill.identical(line) and _measured(line) for line in items)
    if kind is ErrorKind.QUANTITY_UNIT_SLIP:
        return any(line.unit == "m" and bill.identical(line) for line in items)
    if kind is ErrorKind.PRICE_PER_WRONG_UNIT:
        return any(line.unit == "m3" and line.family_spec.thickness is not None for line in items)
    if kind in (ErrorKind.MISPLACED_POSITION, ErrorKind.CODE_OUTSIDE_SECTION):
        titels = Counter(row.los for row in bill.titel_rows())
        return any(count > 1 for count in titels.values())
    if kind is ErrorKind.COMPONENT_SUM_ERROR:
        return bill.features.components > 0
    return bool(items)


def truths(bill: BoqBill) -> tuple[GroundTruth, ...]:
    result = []
    for planted in bill.planted:
        row = bill.row_of(planted.target)
        rows = {row, *(bill.row_of(line) for line in planted.related)}
        result.append(
            GroundTruth(
                error_id=planted.error_id,
                kind=planted.kind,
                row=row,
                field=planted.field,
                rows=tuple(sorted(rows)),
                expected_rules=EXPECTED_RULES[planted.kind],
                change=planted.change,
            )
        )
    return tuple(result)


# Rendering ------------------------------------------------------------------------------------


def _unit_text(bill: BoqBill, line: BoqLine) -> str | None:
    if line.unit_text is not None:
        return line.unit_text
    return None if line.unit is None else UNITS[line.unit].text(bill.style.language)


def _values(bill: BoqBill, line: BoqLine) -> list[Decimal | str | None]:
    columns = bill.columns
    cells: dict[str, Decimal | str | None] = {}
    if line.kind == "section":
        cells = {"code": line.code, "text": line.text}
    elif line.kind == "item":
        cells = {
            "code": line.code,
            "type": (TYPE_NAMES if bill.features.type_names else TYPE_CODES)[line.item_type],
            "text": line.text,
            "key": line.key,
            "quantity": line.quantity,
            "unit": _unit_text(bill, line),
            "unit_price": line.unit_price,
            "total": line.total,
        }
        for i, value in enumerate(line.components, start=1):
            cells[f"component_{i}"] = value
    elif line.kind != "blank":
        cells = {"text": line.text, "total": line.total}
    return [cells.get(column) for column in columns]


_AMOUNT_COLUMNS = ("unit_price", "total")


def render_xlsx(bill: BoqBill) -> bytes:
    workbook = Workbook()
    workbook.properties.creator = "Tabular Integrity Workbench synthetic benchmark"
    workbook.properties.created = workbook.properties.modified = WORKBOOK_TIMESTAMP
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "LV" if bill.style.language == "de" else "BoQ"
    for title in bill.title:
        sheet.append([title or None])
    columns = bill.columns
    sheet.append([bill.header(column) for column in columns])
    amounts = [
        i
        for i, column in enumerate(columns, start=1)
        if column in _AMOUNT_COLUMNS or column.startswith("component_")
    ]
    for line in bill.lines:
        sheet.append(_values(bill, line))
        for column in amounts:  # quantities keep the General format
            cell = sheet.cell(row=sheet.max_row, column=column)
            if isinstance(cell.value, Decimal):
                cell.number_format = "#,##0.00"
    return xlsx_bytes(workbook)


def _csv_quantity(value: Decimal, *, german: bool) -> str:
    """A quantity with every decimal place it has. ``csv_number`` writes two, which would round
    a mass in t (three places) and leave the line total no longer equal to quantity × unit
    price."""
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent >= -2:
        return csv_number(value, german=german, amount=False)
    text = f"{value:,f}"
    if german:
        return text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text.replace(",", "")


def render_csv(bill: BoqBill) -> bytes:
    german = bill.style.language == "de"
    columns = bill.columns
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";" if german else ",", lineterminator="\r\n")
    for title in bill.title:
        writer.writerow([title, *([""] * (len(columns) - 1))])
    writer.writerow([bill.header(column) for column in columns])
    for line in bill.lines:
        cells = []
        for column, value in zip(columns, _values(bill, line), strict=True):
            if isinstance(value, Decimal) and column == "quantity":
                cells.append(_csv_quantity(value, german=german))
            elif isinstance(value, Decimal):
                amount = column in _AMOUNT_COLUMNS or column.startswith("component_")
                cells.append(csv_number(value, german=german, amount=amount))
            else:
                cells.append("" if value is None else value)
        writer.writerow(cells)
    return buffer.getvalue().encode("utf-8")


def column_fields(bill: BoqBill) -> dict[int, str]:
    """The bill's columns that no header of the ``boq`` profile maps, by source column, with the
    field the harness maps each to, as a reviewer would: the STLB-Bau key column
    (``standard_text_key``, so ``domain.standard_text_keys`` runs on the bills that carry keys)
    and the unit price components (EP-Anteil k, ``unit_price_component_k``)."""
    fields: dict[int, str] = {}
    for number, column in enumerate(bill.columns, start=1):
        if column.startswith("component_"):
            fields[number] = f"unit_price_component_{column.rsplit('_', 1)[1]}"
        elif column == "key":
            fields[number] = "standard_text_key"
    return fields


def document(bill: BoqBill, *, name: str, file_format: str) -> SyntheticDocument:
    content = render_xlsx(bill) if file_format == "xlsx" else render_csv(bill)
    return SyntheticDocument(
        name=f"{name}.{file_format}",
        language=bill.style.language,
        format=file_format,
        content=content,
        row_kinds={bill.row_of(line): line.kind for line in bill.lines},
        truths=truths(bill),
        features={
            "positions": len(bill.items()),
            "buildings": bill.features.buildings,
            "keys": bill.features.keys,
            "components": bill.features.components,
            "type_column": bill.features.type_column,
            "type_names": bill.features.type_names,
        },
        column_fields=column_fields(bill),
        contingency_and_hourly_rows=frozenset(
            bill.row_of(line) for line in bill.items() if line.item_type in CONTINGENCY_TYPES
        ),
    )


def _deal(rng: random.Random, count: int, share: float) -> list[bool]:
    """``round(count × share)`` of ``count`` flags set, in a shuffled order."""
    chosen = round(count * share)
    flags = [True] * chosen + [False] * (count - chosen)
    rng.shuffle(flags)
    return flags


def features_of(rng: random.Random, count: int, settings: BoqSettings) -> list[Features]:
    """What each of ``count`` bills carries: the shares of :class:`BoqSettings`, dealt so that
    each holds exactly (rounded) over the corpus."""
    english = _deal(rng, count, settings.english_share)
    buildings = _deal(rng, count, settings.buildings_share)
    german = [i for i in range(count) if not english[i]]
    share = count / len(german) if german else 0.0
    keys = _deal(rng, len(german), min(1.0, settings.key_share * share))
    components = _deal(rng, len(german), min(1.0, settings.component_share * share))
    columns = _deal(rng, len(german), settings.type_column_share)
    # Every second bill with a Positionsart column writes the import's names. Taken in turn, not
    # drawn, so the bills of a seed stay the same apart from that column.
    names = [columns[j] and sum(columns[:j]) % 2 == 1 for j in range(len(german))]
    result = [Features(language="en", buildings=buildings[i]) for i in range(count)]
    for j, i in enumerate(german):
        result[i] = Features(
            language="de",
            buildings=buildings[i],
            keys=keys[j],
            components=rng.randint(2, 4) if components[j] else 0,
            type_column=columns[j],
            type_names=names[j],
        )
    return result


def _positions(rng: random.Random, settings: BoqSettings) -> int:
    low, high = settings.positions
    return round(math.exp(rng.uniform(math.log(low), math.log(high))))


def generate_boq_corpus(config: CorpusConfig) -> list[SyntheticDocument]:
    """``config.documents_per_variant`` bills. Error kinds are dealt from a shuffled deck of
    every kind, as in the standard variant; a kind a bill cannot hold goes to a later bill."""
    settings = config.boq
    rng = random.Random(config.seed)  # noqa: S311 - reproducible test data, not security
    count = config.documents_per_variant
    deck: list[ErrorKind] = []
    documents = []
    for index, features in enumerate(features_of(rng, count, settings), start=1):
        file_format = settings.formats[(index - 1) % len(settings.formats)]
        name = f"boq-{features.language}-{index:03d}"
        bill = generate_bill(rng, features, _positions(rng, settings))
        kinds: list[ErrorKind] = []
        for _ in range(rng.randint(0, config.max_errors)):
            if not deck:
                deck = list(config.kinds)
                rng.shuffle(deck)
            kind = deck.pop()
            if (
                kind in kinds
                or (kind in EXCLUSIVE and EXCLUSIVE & set(kinds))
                or not eligible(bill, kind)
            ):
                deck.insert(0, kind)  # deal it to a later bill
                continue
            kinds.append(kind)
        plant(rng, bill, kinds, prefix=name)
        documents.append(document(bill, name=name, file_format=file_format))
    return documents
