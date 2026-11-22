"""The price model of the ``boq`` benchmark variant: position families per trade and their prices.

A **family** is one kind of work in one unit, written as a short text with options, for example
"Mauerwerk KS {11,5|17,5|24|30} cm" in m². Each option value has a price factor (24 cm costs
more per m² than 11,5 cm), so the positions of one family are similar texts whose prices differ
for a reason. A family belongs to one trade, and a generated bill has one Titel per trade, so a
family appears only in its trade's Titel. Families of work that repeats across a building are
*located*: the same family and options may appear once per construction phase
("Bauabschnitt 2"), with the same unit price.

The texts are written for this project in German and English. No STLB-Bau text is copied: the
catalogue is a licensed product, and its terms forbid derived works. The standard-text keys are
synthetic (``SYN-050-001-2100``: trade, family, options) and only stand in for the STLB-Bau
column of real bills.

Prices (:class:`PriceModel`): base price × the option factors × a bill factor (the regional
price level, lognormal with σ 0.10) × noise per family and options (lognormal with σ 0.08),
rounded to cents. The same family and options get the same unit price everywhere in a bill, as
estimators price them. Quantities are lognormal around a typical size per family (σ 0.8 for
measured work, 0.6 for counts and periods); counts and periods are whole numbers, lump sums 1.
The random factors are floats drawn from ``random.Random``; every amount is a ``Decimal``.

The catalogue is the table :data:`CATALOGUE`, one line per trade or family (see
:func:`parse_catalogue` for the format).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from itertools import product
from typing import Literal

CENT = Decimal("0.01")
_PRICE_SIGMA = 0.10  # bill factor: the regional price level
_NOISE_SIGMA = 0.08  # one estimator's price for one family and options
_MEASURE_SIGMA = 0.8
_COUNT_SIGMA = 0.6

Scale = Literal["measure", "mass", "count", "time", "lump_sum"]
Language = Literal["de", "en"]


@dataclass(frozen=True)
class Unit:
    unit_id: str
    de: str
    en: str
    dimension: str  # as the dimensions of the BoQ profile's units

    def text(self, language: Language) -> str:
        return self.de if language == "de" else self.en


UNITS: dict[str, Unit] = {
    unit.unit_id: unit
    for unit in (
        Unit("m", "m", "m", "length"),
        Unit("m2", "m2", "m2", "area"),
        Unit("m3", "m3", "m3", "volume"),
        Unit("t", "t", "t", "mass"),
        Unit("pcs", "St", "nr", "count"),
        Unit("wk", "Wo", "wk", "time"),
        Unit("ls", "psch", "item", "lump_sum"),
    )
}
# A unit of another dimension for each measured one (the ``wrong_unit`` kind: m² -> m, ...).
OTHER_DIMENSION: dict[str, str] = {"m": "m2", "m2": "m", "m3": "m2"}
UNKNOWN_UNITS: dict[Language, tuple[str, ...]] = {
    "de": ("Sack", "Rolle", "Pal", "Bund"),
    "en": ("bag", "roll", "pallet", "coil"),
}
_SCALES: dict[str, Scale] = {
    "length": "measure",
    "area": "measure",
    "volume": "measure",
    "mass": "mass",
    "count": "count",
    "time": "time",
    "lump_sum": "lump_sum",
}


@dataclass(frozen=True)
class Choice:
    """One value of an option: its words in each language, its price factor and, for the
    thickness of a part measured in m³, that thickness in metres."""

    de: str
    en: str
    factor: Decimal
    metres: Decimal | None = None

    def text(self, language: Language) -> str:
        return self.de if language == "de" else self.en


@dataclass(frozen=True)
class Family:
    """One kind of work in one unit. ``de`` and ``en`` are templates with one ``{}`` per
    option; ``thickness`` is the index of the option whose choices are thicknesses."""

    trade: str
    number: int
    unit: Unit
    base: Decimal  # price per unit before the factors
    size: Decimal  # typical quantity (the median)
    located: bool
    de: str
    en: str
    options: tuple[tuple[Choice, ...], ...]

    @property
    def family_id(self) -> str:
        return f"{self.trade}-{self.number:03d}"

    @property
    def scale(self) -> Scale:
        return _SCALES[self.unit.dimension]

    @property
    def thickness(self) -> int | None:
        return next(
            (i for i, option in enumerate(self.options) if option[0].metres is not None), None
        )

    def combos(self) -> list[tuple[int, ...]]:
        return list(product(*(range(len(option)) for option in self.options)))

    def text(self, combo: tuple[int, ...], language: Language) -> str:
        template = self.de if language == "de" else self.en
        return template.format(*(self.options[i][j].text(language) for i, j in enumerate(combo)))

    def factor(self, combo: tuple[int, ...]) -> Decimal:
        result = Decimal(1)
        for i, j in enumerate(combo):
            result *= self.options[i][j].factor
        return result

    def key(self, combo: tuple[int, ...]) -> str:
        """The synthetic standard-text key of this family and options."""
        options = "".join(str(j + 1) for j in combo).ljust(4, "0")
        return f"SYN-{self.trade}-{self.number:03d}-{options}"

    def thickness_of(self, combo: tuple[int, ...]) -> Decimal | None:
        index = self.thickness
        return None if index is None else self.options[index][combo[index]].metres


@dataclass(frozen=True)
class Trade:
    trade_id: str  # three digits, used in the synthetic keys
    de: str
    en: str
    families: tuple[Family, ...]

    def name(self, language: Language) -> str:
        return self.de if language == "de" else self.en


# One line per trade ("trade | id | German name | English name") or per family of the trade
# above it: "number | unit | base price | typical size | located or - | German text | English
# text | option | option ...". An option lists its choices separated by ";": the words (in
# English with decimal points instead of commas), then optionally "x<factor>" (default 1) and
# "@<metres>" (a thickness). A line ending in a backslash continues on the next one.
CATALOGUE = """
trade | 010 | Baustelleneinrichtung | Site setup
1 | ls | 8500 | 1 | - | Baustelleneinrichtung einrichten | Site setup, establish
2 | wk | 640 | 30 | - | Baustelleneinrichtung vorhalten | Site setup, maintain
3 | ls | 3200 | 1 | - | Baustelleneinrichtung räumen | Site setup, clear away
4 | m | 18 | 140 | - | Bauzaun, Höhe {} m, aufstellen und vorhalten | Site hoarding, {} m high, \
erect and maintain | 2,00; 2,50 x1.2
5 | ls | 1800 | 1 | - | Baustromanschluss, Anschlusswert {} A | Temporary power connection, {} A \
| 32; 63 x1.4; 125 x2.1
6 | wk | 95 | 30 | - | Bürocontainer {} Fuß vorhalten | Site office container, {} ft, hire \
| 10; 20 x1.6
7 | pcs | 340 | 12 | - | Schuttcontainer {} m3 stellen, abfahren und entsorgen | Skip, {} m3, \
deliver, remove and dispose of | 5; 7 x1.3; 10 x1.75

trade | 020 | Erdarbeiten | Earthworks
1 | m2 | 3.8 | 900 | - | Oberboden abtragen, Dicke {} cm, seitlich lagern | Strip topsoil {} cm \
deep, store on site | 20; 30 x1.3; 40 x1.6
2 | m3 | 9.5 | 650 | - | Baugrube ausheben, Bodenklasse {}, Tiefe bis {} m | Excavate pit, soil \
class {}, depth up to {} m | 3; 4 x1.15; 5 x1.45 | 1,25; 2,50 x1.2; 4,00 x1.5
3 | m3 | 18 | 120 | - | Leitungsgraben ausheben, Breite {} m, Tiefe bis {} m | Excavate service \
trench {} m wide, up to {} m deep | 0,60; 0,80 x0.95; 1,00 x0.9 | 1,25; 1,75 x1.2
4 | m3 | 14 | 500 | - | Boden laden und abfahren, Entfernung bis {} km | Load and cart away \
spoil, up to {} km | 5; 10 x1.3; 20 x1.7
5 | t | 12 | 400 | - | Boden entsorgen, Zuordnungsklasse Z {} | Dispose of spoil, class Z {} \
| 0; 1.1 x1.8; 2 x3.2
6 | m2 | 11 | 420 | - | Schottertragschicht 0/{} mm, Dicke {} cm, einbauen und verdichten | \
Crushed stone base 0/{} mm, {} cm thick, place and compact | 32; 45 x0.97; 56 x0.95 | 20; 30 x1.45
7 | m3 | 16 | 260 | - | Arbeitsräume lagenweise bis {} cm verfüllen und verdichten | Backfill \
working space in layers up to {} cm, compact | 20; 30 x0.9
8 | m2 | 1.9 | 900 | - | Planum herstellen, Höhentoleranz {} cm | Trim formation level to a \
tolerance of {} cm | 2 x1.15; 3

trade | 030 | Entwässerung | Drainage
1 | m | 28 | 60 | located | Grundleitung PVC-U DN {} liefern und verlegen | Underground drain \
PVC-U DN {}, supply and lay | 100; 125 x1.15; 150 x1.35; 200 x1.8
2 | pcs | 22 | 12 | located | Bogen PVC-U DN {}, {} Grad | Bend PVC-U DN {}, {} degrees | 100; \
125 x1.2; 150 x1.45; 200 x2.1 | 15; 30; 45 x1.05
3 | pcs | 38 | 8 | located | Abzweig PVC-U DN {}, {} Grad | Branch PVC-U DN {}, {} degrees | \
150; 200 x1.6 | 45; 87 x1.05
4 | pcs | 1450 | 3 | - | Kontrollschacht DN {}, Tiefe bis {} m | Inspection chamber DN {}, up \
to {} m deep | 800; 1000 x1.3 | 1,50; 2,00 x1.2; 2,50 x1.4
5 | pcs | 185 | 6 | located | Bodenablauf DN {}, Aufsatz {} mm | Floor gully DN {}, grating {} mm \
| 70; 100 x1.15 | 150; 200 x1.25
6 | m | 6.5 | 120 | - | Dichtheitsprüfung der Grundleitungen DN {} | Leak test of underground \
drains DN {} | 100; 150 x1.1; 200 x1.25
7 | m | 7 | 90 | located | Sandbettung im Rohrgraben, Dicke {} cm | Sand bedding in pipe trench, \
{} cm thick | 10; 15 x1.35

trade | 040 | Beton- und Stahlbetonarbeiten | Concrete works
1 | m2 | 11 | 260 | - | Sauberkeitsschicht C8/10, Dicke {} cm | Blinding concrete C8/10, {} cm \
thick | 5; 8 x1.4; 10 x1.7
2 | m3 | 165 | 45 | located | Stahlbeton C{} für Fundamente | Reinforced concrete C{} in \
foundations | 20/25 x0.95; 25/30; 30/37 x1.07; 35/45 x1.16
3 | m3 | 215 | 40 | located | Stahlbeton C{} für Wände, Dicke {} cm | Reinforced concrete C{} in \
walls, {} cm thick | 25/30; 30/37 x1.07; 35/45 x1.16 | 20 x1.1 @0.20; 25 @0.25; 30 x0.95 @0.30
4 | m3 | 190 | 55 | located | Stahlbeton C{} für Decken, Dicke {} cm | Reinforced concrete C{} in \
slabs, {} cm thick | 25/30; 30/37 x1.07 | 18 x1.05 @0.18; 20 @0.20; 22 x0.98 @0.22; 25 x0.96 @0.25
5 | m3 | 175 | 90 | located | Stahlbeton C{} für Bodenplatte, Dicke {} cm | Reinforced concrete \
C{} in ground slab, {} cm thick | 25/30; 30/37 x1.07 | 25 x1.04 @0.25; 30 @0.30; 40 x0.95 @0.40
6 | t | 1650 | 12 | located | Betonstahl B500B, Durchmesser bis {} mm, liefern und verlegen | \
Reinforcing steel B500B, up to {} mm diameter, supply and fix | 12 x1.08; 20; 28 x0.96
7 | t | 1550 | 6 | located | Betonstahlmatten B500A, Typ Q{}A, liefern und verlegen | Steel mesh \
B500A, type Q{}A, supply and fix | 188 x1.04; 257; 335 x0.98; 424 x0.97
8 | m2 | 34 | 160 | located | Wandschalung, Höhe bis {} m | Wall formwork, up to {} m high | \
2,75; 3,50 x1.15; 5,00 x1.35
9 | m2 | 38 | 180 | located | Deckenschalung, Raumhöhe bis {} m | Soffit formwork, room height \
up to {} m | 2,75; 3,50 x1.12
10 | pcs | 62 | 14 | located | Fertigteilsturz, Länge {} m | Precast lintel, {} m long | 1,00; \
1,25 x1.2; 1,50 x1.4; 2,00 x1.8

trade | 050 | Mauerarbeiten | Masonry
1 | m2 | 52 | 180 | located | Mauerwerk KS {} cm, Druckfestigkeitsklasse {} | Calcium silicate \
masonry {} cm, strength class {} | 11,5; 17,5 x1.3; 24 x1.6; 30 x1.9 | 12; 20 x1.08
2 | m2 | 68 | 150 | located | Mauerwerk Hochlochziegel {} cm, Wärmeleitfähigkeit {} | Clay \
block masonry {} cm, thermal conductivity {} | 17,5; 24 x1.3; 36,5 x1.85 | 0,08 x1.12; 0,10
3 | m2 | 44 | 120 | located | Porenbeton-Mauerwerk {} cm | Aerated concrete masonry {} cm | 10; \
15 x1.25; 20 x1.5; 24 x1.7
4 | m | 14 | 40 | located | Schlitz in Mauerwerk herstellen, Querschnitt bis {} cm2 | Cut chase \
in masonry, up to {} cm2 | 50; 100 x1.3; 200 x1.7
5 | m | 9 | 70 | located | Kimmschicht für Wanddicke {} cm | Levelling course for {} cm wall | \
11,5; 17,5 x1.2; 24 x1.4
6 | pcs | 85 | 5 | located | Öffnung im Mauerwerk schließen, bis {} m2 | Close opening in \
masonry, up to {} m2 | 0,5; 1,0 x1.6; 2,0 x2.4

trade | 060 | Gerüstarbeiten | Scaffolding
1 | m2 | 9.5 | 600 | - | Fassadengerüst Lastklasse {}, Breite {} m, auf- und abbauen | Facade \
scaffold, load class {}, {} m wide, erect and dismantle | 3; 4 x1.15 | 0,70; 1,00 x1.12
2 | wk | 420 | 12 | - | Gerüst vorhalten, Lastklasse {}, Gerüstfläche bis {} m2 | Scaffold \
hire, load class {}, area up to {} m2 | 3; 4 x1.15 | 500; 1000 x1.8; 2000 x3.2
3 | m2 | 2.6 | 600 | - | Schutznetz am Gerüst, Maschenweite {} mm | Debris netting on scaffold, \
{} mm mesh | 20 x1.1; 40
4 | m2 | 6.8 | 140 | located | Innengerüst, Arbeitshöhe bis {} m | Interior scaffold, working \
height up to {} m | 3; 4 x1.2; 5 x1.45
5 | pcs | 1850 | 1 | - | Treppenturm, Höhe bis {} m | Stair tower, up to {} m high | 10; 15 \
x1.35; 20 x1.7

trade | 070 | Putzarbeiten | Plastering
1 | m2 | 17 | 420 | located | Innenputz Kalkgips, Dicke {} mm, Qualitätsstufe Q{} | Internal \
lime-gypsum plaster, {} mm, finish level Q{} | 10; 15 x1.25 | 2; 3 x1.15
2 | m2 | 34 | 300 | located | Außenputz als Leichtputz, Dicke {} mm, Körnung {} mm | External \
lightweight render, {} mm, grain {} mm | 15; 20 x1.2 | 2; 3 x1.05
3 | m | 4.8 | 90 | located | Kantenschutzprofil, Länge {} m | Angle bead, {} m long | 2,50; 3,00 \
x1.05
4 | m | 6.5 | 60 | located | Putzträger über Schlitzen, Breite bis {} cm | Plaster mesh over \
chases, up to {} cm wide | 20; 30 x1.3
5 | m2 | 78 | 320 | located | Wärmedämmverbundsystem EPS {} mm, Wärmeleitgruppe {} | External \
insulation system EPS {} mm, conductivity group {} | 100; 140 x1.15; 160 x1.22; 200 x1.38 | 032 \
x1.08; 035
6 | m | 24 | 80 | - | Sockelputz, Höhe {} cm | Plinth render, {} cm high | 30; 50 x1.4

trade | 080 | Estricharbeiten | Screeds
1 | m2 | 21 | 300 | located | Zementestrich CT-C{}-F{}, Dicke {} mm, auf Trennlage | Cement \
screed CT-C{}-F{}, {} mm, on separating layer | 25; 30 x1.06 | 4; 5 x1.04 | 45; 50 x1.08; 65 x1.3
2 | m2 | 27 | 260 | located | Heizestrich CT-C{}-F{}, Dicke {} mm | Heated screed CT-C{}-F{}, {} \
mm | 25; 30 x1.06 | 4; 5 x1.04 | 65; 70 x1.06
3 | m2 | 7.5 | 300 | located | Trittschalldämmung EPS, Dicke {} mm | Impact sound insulation \
EPS, {} mm | 20; 30 x1.25; 40 x1.5
4 | m | 1.6 | 260 | located | Randdämmstreifen, Höhe {} mm | Edge insulation strip, {} mm high \
| 80; 100 x1.1; 120 x1.2
5 | m | 11 | 40 | located | Bewegungsfuge im Estrich, Breite {} mm | Movement joint in screed, {} \
mm wide | 8; 10 x1.1

trade | 090 | Fliesenarbeiten | Tiling
1 | m2 | 72 | 110 | located | Bodenfliesen Feinsteinzeug {} cm, im Dünnbett verlegen | \
Porcelain floor tiles {} cm, laid in thin bed | 30 x 60; 60 x 60 x1.1; 60 x 120 x1.35
2 | m2 | 64 | 90 | located | Wandfliesen Steingut {} cm, im Dünnbett ansetzen | Ceramic wall \
tiles {} cm, fixed in thin bed | 20 x 40; 30 x 60 x1.15
3 | m | 15 | 80 | located | Fliesensockel, Höhe {} cm | Tiled skirting, {} cm high | 6; 8 x1.1; \
10 x1.2
4 | m2 | 24 | 70 | located | Verbundabdichtung, Wassereinwirkungsklasse W{}-I | Liquid \
waterproofing under tiles, exposure class W{}-I | 1; 2 x1.2; 3 x1.45
5 | m | 5.5 | 120 | located | Silikonfuge, Breite {} mm | Silicone joint, {} mm wide | 5; 8 x1.2
6 | m | 13 | 40 | located | Fliesenschiene Edelstahl, Höhe {} mm | Stainless steel tile trim, {} \
mm high | 8; 10 x1.05; 12,5 x1.12

trade | 100 | Trockenbauarbeiten | Drywall
1 | m2 | 48 | 220 | located | Metallständerwand CW {}, beidseitig {}-lagig beplankt | Metal stud \
partition CW {}, {}-layer boarding each side | 50; 75 x1.1; 100 x1.2 | 1; 2 x1.4
2 | m2 | 38 | 120 | located | Vorsatzschale CW {}, {}-lagig beplankt | Lining wall CW {}, {}-layer \
boarding | 50; 75 x1.1 | 1; 2 x1.35
3 | m2 | 52 | 200 | located | Abgehängte Decke, Gipsplatten {} mm | Suspended ceiling, \
plasterboard {} mm | 12,5; 2 x 12,5 x1.3
4 | pcs | 145 | 8 | located | Revisionsklappe {} cm | Access panel {} cm | 30 x 30; 40 x 40 \
x1.2; 60 x 60 x1.55
5 | m2 | 6.2 | 220 | located | Mineralwolle in Ständerwand, Dicke {} mm | Mineral wool in stud \
partition, {} mm | 40; 60 x1.3; 80 x1.6

trade | 110 | Malerarbeiten | Painting
1 | m2 | 6.8 | 700 | located | Dispersionsanstrich, Nassabriebklasse {}, {}-fach | Emulsion \
paint, wet abrasion class {}, {} coats | 2 x1.15; 3 | 2; 3 x1.35
2 | m2 | 1.9 | 700 | located | Tiefgrund auftragen, Verbrauch bis {} ml/m2 | Apply deep primer, \
up to {} ml/m2 | 100; 200 x1.3
3 | m2 | 7.9 | 400 | located | Raufasertapete, Körnung {} | Woodchip wallpaper, grade {} | 1; 2 \
x1.05; 3 x1.1
4 | pcs | 48 | 20 | located | Stahlzarge lackieren, Breite bis {} m | Paint steel door frame, up \
to {} m wide | 1,00; 1,50 x1.25; 2,00 x1.5
5 | m2 | 13 | 500 | - | Fassadenanstrich Silikonharz, {}-fach | Silicone resin facade paint, {} \
coats | 2; 3 x1.3

trade | 120 | Türen | Doors
1 | pcs | 520 | 12 | located | Innentür einflügelig, {} x 198,5 cm, Röhrenspaneinlage | \
Internal door, single leaf, {} x 198.5 cm, tubular core | 73,5; 86,0 x1.06; 98,5 x1.12
2 | pcs | 1150 | 3 | located | Innentür zweiflügelig, {} x 213,5 cm | Internal door, double \
leaf, {} x 213.5 cm | 147; 172 x1.12
3 | pcs | 210 | 14 | located | Stahlzarge für Wanddicke {} cm | Steel frame for {} cm wall | \
11,5; 17,5 x1.06; 24 x1.12
4 | pcs | 1450 | 2 | located | Feuerschutztür T{}, {}-flügelig | Fire door T{}, {} leaf | 30; 90 \
x1.6 | 1; 2 x1.9
5 | pcs | 68 | 14 | located | Drückergarnitur Edelstahl, Rosette {} mm | Stainless steel lever \
set, rose {} mm | 50; 52 x1.04
6 | pcs | 165 | 6 | located | Obentürschließer, Größe EN {} | Overhead door closer, size EN {} | \
2; 3 x1.1; 4 x1.25
"""


def _choice(text: str) -> Choice:
    words: list[str] = []
    factor, metres = "1", None
    for part in text.split():
        if part.startswith("x") and part[1:].replace(".", "", 1).isdigit():
            factor = part[1:]
        elif part.startswith("@"):
            metres = part[1:]
        else:
            words.append(part)
    de = " ".join(words)
    return Choice(
        de=de,
        en=de.replace(",", "."),
        factor=Decimal(factor),
        metres=Decimal(metres) if metres is not None else None,
    )


def parse_catalogue(text: str) -> tuple[Trade, ...]:
    """The trades and families of a catalogue table (format above :data:`CATALOGUE`)."""
    trades: list[Trade] = []
    families: list[Family] = []
    header: tuple[str, str, str] | None = None

    def close() -> None:
        if header is not None:
            trades.append(Trade(*header, families=tuple(families)))

    for raw in text.splitlines():
        if not raw.strip():
            continue
        cells = [cell.strip() for cell in raw.split("|")]
        if cells[0] == "trade":
            close()
            header, families = (cells[1], cells[2], cells[3]), []
            continue
        if header is None:
            raise ValueError(f"family before its trade: {raw!r}")
        number, unit, base, size, located, de, en, *options = cells
        family = Family(
            trade=header[0],
            number=int(number),
            unit=UNITS[unit],
            base=Decimal(base),
            size=Decimal(size),
            located=located == "located",
            de=de,
            en=en,
            options=tuple(
                tuple(_choice(choice) for choice in option.split(";")) for option in options
            ),
        )
        if de.count("{}") != len(family.options) or en.count("{}") != len(family.options):
            raise ValueError(f"family {family.family_id}: one {{}} per option is needed")
        families.append(family)
    close()
    return tuple(trades)


TRADES: tuple[Trade, ...] = parse_catalogue(CATALOGUE)


def lognormal(rng: random.Random, sigma: float) -> Decimal:
    """A lognormal factor with median 1, as an exact decimal of six places."""
    return Decimal(f"{rng.lognormvariate(0.0, sigma):.6f}")


def _places(scale: Scale) -> Decimal:
    if scale in ("count", "time", "lump_sum"):
        return Decimal(1)
    return Decimal("0.001") if scale == "mass" else CENT


def quantity(rng: random.Random, family: Family) -> Decimal:
    """A quantity around the family's typical size, in the precision its unit is written in."""
    if family.scale == "lump_sum":
        return Decimal(1)
    sigma = _COUNT_SIGMA if family.scale in ("count", "time") else _MEASURE_SIGMA
    return _rounded(family.size * lognormal(rng, sigma), family.scale)


def similar_quantity(rng: random.Random, family: Family, value: Decimal) -> Decimal:
    """The quantity of the same position in another building: within ±30 % of ``value``."""
    if family.scale == "lump_sum":
        return value
    return _rounded(value * Decimal(f"{rng.uniform(0.77, 1.3):.6f}"), family.scale)


def _rounded(value: Decimal, scale: Scale) -> Decimal:
    places = _places(scale)
    smallest = Decimal(1) if places == 1 else places * 10
    return max(smallest, value.quantize(places, rounding=ROUND_HALF_UP))


def split(rng: random.Random, price: Decimal, parts: int) -> tuple[Decimal, ...]:
    """``parts`` unit price components (labour, materials, plant, other) that add up to
    ``price`` exactly, each at least one cent."""
    cents = int((price / CENT).to_integral_value())
    if cents < parts:
        raise ValueError("a price below one cent per component cannot be split")
    weights = [rng.uniform(1.0, 3.0) for _ in range(parts)]
    total = sum(weights)
    shares = [max(1, int(cents * weight / total)) for weight in weights[:-1]]
    while sum(shares) > cents - 1:  # leave at least one cent for the last part
        largest = max(range(len(shares)), key=lambda i: shares[i])
        shares[largest] -= 1
    shares.append(cents - sum(shares))
    return tuple(Decimal(share) * CENT for share in shares)


class PriceModel:
    """The unit prices of one bill (see the module docstring)."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.bill_factor = lognormal(rng, _PRICE_SIGMA)
        self._prices: dict[tuple[str, tuple[int, ...]], Decimal] = {}

    def unit_price(self, family: Family, combo: tuple[int, ...]) -> Decimal:
        key = (family.family_id, combo)
        if key not in self._prices:
            value = family.base * family.factor(combo) * self.bill_factor
            value *= lognormal(self._rng, _NOISE_SIGMA)
            self._prices[key] = max(CENT, value.quantize(CENT, rounding=ROUND_HALF_UP))
        return self._prices[key]
