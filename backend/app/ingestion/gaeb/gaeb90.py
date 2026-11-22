"""Read a GAEB 90 file (``.d81``, ``.d83``, ``.d84``, ``.d86``) into a
:class:`~app.ingestion.gaeb.model.GaebDocument`.

GAEB 90 is the fixed-column predecessor of GAEB DA XML, still exported by many AVA programs.
A file is a sequence of records of 80 characters: the record type in columns 1-2, the data in
3-72 and a running record number in 75-80. Optional ``T0``/``T1``/``T9`` records (contract
terms) may come before the opening record ``00``; record ``99`` closes the file.

Record layout (columns 1-based, as in the GAEB 90 rules and the sample files they describe):

====  =====================================================================================
00    11-12 exchange phase (DA), 63-71 OZ mask (``1122PPPPI``: digits = category levels,
      ``P`` = item number, ``I`` = index, ``0`` = unused), 72-73 edition year
01    3-42 name of the bill; 02 project; 08 3-8 currency
10    3-4 lot number, 5-72 its name (a level above the OZ); 33 ends the lot
11    3-11 OZ of a category (only its levels filled); 12 its label (3-72, may repeat)
20    start of a note (Hinweistext); 41 start of an execution description; 24 start of a
      sub-description of the item before it. Their text follows in 25/26 records
21    item: 3-11 OZ, 12 item type 1 (N normal, G base item, A alternative item), 13 item type 2
      (N normal, E contingency without total, M contingency with total), 14 item type 3,
      15-18 alternative group, 21 reference marker (B base of repetitions, W repetition),
      24-34 quantity (8 digits + 3 decimals), 35-38 unit
22/23 prices: 3-11 OZ, 13-22 unit price (8 + 2 decimals) and 23 its tenth of a cent,
      25-36 total (10 + 2 decimals)
25    short text (3-72), 26 long text (6-72; 3-5 hold a text-supplement marker); 28 marks
      the text of a repetition item
30    unit-price components (not shown)
31    3-11 OZ: end of a category; 32 3-11 OZ, 13-24 its total (10 + 2 decimals)
99    3-14 total of the bill (10 + 2), 22-25 VAT percent (2 + 2), 26-37 gross total (10 + 2)
====  =====================================================================================

Checks (each failure has its own message and the document is stored as failed): the file
starts with ``T0`` or ``00``; every line is a record of at most 80 characters with a
record type; record ``00`` states the phase the file extension names and a valid OZ mask;
numeric fields hold digits; record ``99`` closes the file. Numbers keep the stated digits; a
zero bill total in record ``99`` (written by programs that leave it unfilled) is not shown.

Character set: GAEB 90 prescribes the DOS code page 850. Some programs write Windows-1252
instead; the umlauts tell the two apart, and the result is named in the extraction details.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.errors import ExtractionError, UnsupportedFormatError
from app.ingestion.gaeb.model import (
    GAEB90_VERSION,
    EntryKind,
    GaebCategory,
    GaebDocument,
    GaebEntry,
    XmlValue,
)

PHASES: tuple[str, ...] = ("81", "83", "84", "86")
RECORD_WIDTH = 80
DATA_END = 72  # columns 73-80 hold the record number
_RECORD_TYPE = re.compile(r"^(?:\d\d|T\d)$")
_DIGITS = re.compile(r"^(-?)(\d+)(-?)$")
# Umlauts and ß in each character set: their byte values do not overlap.
_DOS_LETTERS = frozenset(b"\x84\x94\x81\x8e\x99\x9a\xe1")
_WINDOWS_LETTERS = frozenset(b"\xe4\xf6\xfc\xc4\xd6\xdc\xdf")
# boq.yaml names the record 30 label (deterministic.unit_price_components): change both together.
_NOT_SHOWN = {
    "30": "Satzart 30 (Einheitspreisanteile)",
    "T1": "Vertragliche Regelungen (T-Sätze)",
}
_IGNORED = frozenset({"00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "T0", "T9"})


@dataclass(frozen=True, slots=True)
class _Record:
    kind: str
    text: str  # columns 1-80, padded with spaces
    line: int  # physical line in the file

    def field(self, first: int, last: int) -> str:
        """Columns ``first`` to ``last`` (1-based, inclusive)."""
        return self.text[first - 1 : last]


@dataclass(frozen=True, slots=True)
class _Segment:
    kind: str  # "1".."9" category level, "P" item number, "I" index
    start: int  # offset within the 9-character OZ
    length: int


def read_gaeb90(path: Path, expected_phase: str) -> GaebDocument:
    text, encoding = decode(path.read_bytes())
    records = _records(text)
    opening = next((r for r in records if r.kind == "00"), None)
    if opening is None:
        raise ExtractionError(
            "The GAEB 90 file has no opening record 00.", details={"reason": "gaeb90_no_header"}
        )
    phase = opening.field(11, 12).strip()
    if phase != expected_phase:
        if phase not in PHASES:
            raise UnsupportedFormatError(
                f"GAEB 90 exchange phase {phase or '(empty)'!r} (record 00, line "
                f"{opening.line}) is not supported; phases {', '.join(PHASES)} are read.",
                details={"reason": "gaeb_phase_unsupported", "phase": phase},
            )
        raise UnsupportedFormatError(
            f"The file name ends with .d{expected_phase}, but the file is a GAEB 90 D{phase} "
            f"(exchange phase in record 00, line {opening.line}). Correct the file name.",
            details={"reason": "gaeb_phase_mismatch", "phase": phase},
        )
    if records[-1].kind != "99":
        raise ExtractionError(
            "The GAEB 90 file does not end with the closing record 99; it may be truncated.",
            details={"reason": "gaeb90_no_end"},
        )
    segments = _mask(opening)
    return _Builder(records, opening, segments, phase, encoding).build()


def decode(data: bytes) -> tuple[str, str]:
    """The text of a GAEB 90 file and the character set it was read with."""
    data = data.rstrip(b"\x1a")  # DOS end-of-file marker
    if data.isascii():
        return data.decode("ascii"), "ascii"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    dos = sum(1 for byte in data if byte in _DOS_LETTERS)
    windows = sum(1 for byte in data if byte in _WINDOWS_LETTERS)
    if windows > dos:
        try:
            return data.decode("cp1252"), "cp1252"
        except UnicodeDecodeError:
            return data.decode("latin-1"), "latin-1"
    return data.decode("cp850"), "cp850"


def _records(text: str) -> list[_Record]:
    lines = text.splitlines()
    records: list[_Record] = []
    for number, line in enumerate(lines, start=1):
        line = line.rstrip()
        if not line:
            continue
        kind = line[:2]
        if not records and kind not in ("00", "T0"):
            raise UnsupportedFormatError(
                "The file is not a GAEB 90 file: it must start with record 00 (or T0 for "
                f"contract terms), but line {number} starts with {kind!r}.",
                details={"reason": "not_gaeb90"},
            )
        if not _RECORD_TYPE.match(kind):
            raise ExtractionError(
                f"Line {number} is not a GAEB 90 record (record type {kind!r}).",
                details={"reason": "gaeb90_bad_record", "line": number},
            )
        if len(line) > RECORD_WIDTH:
            raise ExtractionError(
                f"Line {number} has {len(line)} characters; GAEB 90 records have at most "
                f"{RECORD_WIDTH}.",
                details={"reason": "gaeb90_bad_record", "line": number},
            )
        records.append(_Record(kind, line.ljust(RECORD_WIDTH), number))
    if not records:
        raise UnsupportedFormatError("The file is empty.", details={"reason": "not_gaeb90"})
    return records


def _mask(opening: _Record) -> list[_Segment]:
    """Segments of the OZ mask in record 00 (columns 63-71)."""
    mask = opening.field(63, 71)
    used = mask.rstrip("0 ")
    segments: list[_Segment] = []
    for offset, char in enumerate(used):
        if segments and segments[-1].kind == char:
            last = segments[-1]
            segments[-1] = _Segment(char, last.start, last.length + 1)
        else:
            segments.append(_Segment(char, offset, 1))
    kinds = [s.kind for s in segments]
    levels = [k for k in kinds if k.isdigit()]
    valid = (
        all(k.isdigit() or k in ("P", "I") for k in kinds)
        and kinds.count("P") == 1
        and kinds.count("I") <= 1
        and len(set(levels)) == len(levels)
        and kinds[: len(levels)] == levels
        and (kinds[-1] in ("P", "I"))
        and ("I" not in kinds or kinds[-1] == "I")
    )
    if not valid:
        raise ExtractionError(
            f"Record 00 (line {opening.line}) states the OZ mask {mask!r}, which GAEB 90 does "
            "not allow (category levels, then P for the item number, then optionally I).",
            details={"reason": "gaeb90_bad_mask"},
        )
    return segments


def _number(record: _Record, first: int, last: int, decimals: int, name: str) -> XmlValue | None:
    """A fixed-decimal field as decimal text (``00000093000``, 3 decimals -> ``93.000``)."""
    raw = record.field(first, last).strip()
    if not raw:
        return None
    match = _DIGITS.match(raw)
    if match is None or (match.group(1) and match.group(3)):
        raise ExtractionError(
            f"Line {record.line}: the {name} {raw!r} in record {record.kind} (columns "
            f"{first}-{last}) is not a number.",
            details={"reason": "gaeb90_bad_number", "line": record.line},
        )
    return XmlValue(
        _decimal_text(match.group(2), decimals, negative=bool(match.group(1) or match.group(3))),
        record.line,
    )


def _decimal_text(digits: str, decimals: int, *, negative: bool = False) -> str:
    digits = digits.rjust(decimals + 1, "0")
    whole = digits[: len(digits) - decimals].lstrip("0") or "0"
    text = f"{whole}.{digits[len(digits) - decimals :]}" if decimals else whole
    return f"-{text}" if negative and set(digits) != {"0"} else text


def _date(text: str) -> str | None:
    """A record date TT.MM.JJ as ISO YYYY-MM-DD (years 00-79 are 20xx); None when unreadable."""
    try:
        parsed = datetime.strptime(text.strip(), "%d.%m.%y").date()
    except ValueError:
        return None
    return parsed.isoformat()


def _is_zero(value: XmlValue | None) -> bool:
    return value is not None and not value.text.strip("-0.")


def _join(*parts: str) -> str:
    return " ".join(" ".join(parts).split())


class _Builder:
    def __init__(
        self,
        records: list[_Record],
        opening: _Record,
        segments: list[_Segment],
        phase: str,
        encoding: str,
    ) -> None:
        self.records = records
        self.levels = [s for s in segments if s.kind.isdigit()]
        self.position = next(s for s in segments if s.kind == "P")
        self.index = next((s for s in segments if s.kind == "I"), None)
        self.document = GaebDocument(
            version=GAEB90_VERSION,
            phase=phase,
            dp=phase,
            schema_file=None,
            schema_sha256=None,
            line=opening.line,
            encoding=encoding,
        )
        self.categories: dict[tuple[str, ...], GaebCategory] = {}
        self.items: dict[str, GaebEntry] = {}  # by the raw 9-character OZ
        self.lot: GaebCategory | None = None
        self.container: GaebCategory | None = None  # where notes go
        self.target: GaebCategory | GaebEntry | None = None  # what 12/25/26 records describe
        self.item: GaebEntry | None = None
        self.not_shown: Counter[str] = Counter()

    # ------------------------------------------------------------------ OZ
    def components(self, oz: str) -> list[str]:
        """Category level parts of a 9-character OZ, up to the first empty one."""
        parts: list[str] = []
        for level in self.levels:
            part = oz[level.start : level.start + level.length].strip()
            if not part:
                break
            parts.append(part)
        return parts

    def key(self, parts: list[str]) -> tuple[str, ...]:
        lot = (self.lot.number,) if self.lot is not None else ()
        return (*lot, *parts)

    def category(self, parts: list[str], line: int) -> GaebCategory | None:
        """The category of these level parts, created (with its parents) when first named."""
        if not parts:
            return self.lot
        key = self.key(parts)
        if key in self.categories:
            return self.categories[key]
        parent = self.category(parts[:-1], line)
        category = GaebCategory(
            element_id=None,
            number=".".join(parts),
            label="",
            line=line,
            level=len(parts) + (1 if self.lot is not None else 0),
        )
        self.categories[key] = category
        self.append(parent, category)
        return category

    def append(self, parent: GaebCategory | None, node: GaebCategory | GaebEntry) -> None:
        (parent.children if parent is not None else self.document.body).append(node)

    # ------------------------------------------------------------------ records
    def build(self) -> GaebDocument:
        handlers = {
            "01": self.header,
            "02": self.header,
            "08": self.header,
            "10": self.start_lot,
            "11": self.start_category,
            "12": self.category_label,
            "20": self.note,
            "41": self.note,
            "24": self.note,
            "21": self.start_item,
            "22": self.prices,
            "23": self.prices,
            "25": self.text,
            "26": self.text,
            "28": lambda record: None,  # the text that follows belongs to the current item
            "42": lambda record: None,  # continues the execution description of record 41
            "31": self.end_category,
            "32": self.category_total,
            "33": self.end_lot,
            "99": self.end,
        }
        for record in self.records:
            handler = handlers.get(record.kind)
            if handler is not None:
                handler(record)
            elif record.kind in _NOT_SHOWN:
                self.not_shown[_NOT_SHOWN[record.kind]] += 1
            elif record.kind not in _IGNORED:
                self.not_shown[f"Satzart {record.kind}"] += 1
        self.document.not_shown.update(self.not_shown)
        return self.document

    def header(self, record: _Record) -> None:
        if record.kind == "01":
            self.document.boq_name = record.field(3, 42).strip() or None
            self.document.date = _date(record.field(43, 50))
        elif record.kind == "02":
            self.document.project = record.field(3, DATA_END).strip() or None
        else:
            self.document.currency = record.field(3, 8).strip() or None

    def start_lot(self, record: _Record) -> None:
        number = record.field(3, 4).strip()
        self.lot = None
        lot = GaebCategory(
            element_id=None,
            number=number,
            label=_join(record.field(5, DATA_END)),
            line=record.line,
            level=1,
        )
        self.document.body.append(lot)
        self.lot = lot
        self.container = self.target = lot
        self.item = None

    def end_lot(self, record: _Record) -> None:
        self.lot = self.container = self.target = self.item = None

    def start_category(self, record: _Record) -> None:
        parts = self.components(record.field(3, 11))
        category = self.category(parts, record.line)
        if category is not None and parts:
            category.line = record.line
        self.container = self.target = category
        self.item = None

    def category_label(self, record: _Record) -> None:
        if isinstance(self.target, GaebCategory):
            self.target.label = _join(self.target.label, record.field(3, DATA_END))
        else:
            self.not_shown["Satzart 12 ohne Bereich"] += 1

    def end_category(self, record: _Record) -> None:
        parts = self.components(record.field(3, 11))
        self.container = self.category(parts[:-1], record.line) if parts else self.lot
        self.target = self.item = None

    def category_total(self, record: _Record) -> None:
        parts = self.components(record.field(3, 11))
        category = self.category(parts, record.line) if parts else None
        total = _number(record, 13, 24, 2, "category total")
        if category is not None and total is not None:
            category.total = total

    def note(self, record: _Record) -> None:
        element = {"20": "Remark", "41": "PerfDescr", "24": "SubDescr"}[record.kind]
        entry = GaebEntry(
            kind=EntryKind.NOTE, element=element, element_id=None, number="", line=record.line
        )
        self.append(self.container, entry)
        self.target = entry
        self.item = None

    def new_item(self, oz: str, record: _Record) -> GaebEntry:
        parts = self.components(oz)
        position = oz[self.position.start : self.position.start + self.position.length].strip()
        index = (
            oz[self.index.start : self.index.start + self.index.length].strip()
            if self.index is not None
            else ""
        )
        number = ".".join([*parts, position]) + index
        parent: GaebCategory | None
        if all(part.isdigit() for part in [*parts, position]):
            parent = self.category(parts, record.line)
        else:
            # Only the index may hold letters. Keep the OZ as written and the item where the
            # records place it, instead of building categories from the letters.
            number = oz.strip()
            parent = self.container
            self.document.invalid_numbers.append((number, record.line))
        entry = GaebEntry(
            kind=EntryKind.ITEM,
            element="Item",
            element_id=None,
            number=number,
            line=record.line,
        )
        self.append(parent, entry)
        self.container = parent
        self.items[oz] = entry
        return entry

    def start_item(self, record: _Record) -> None:
        oz = record.field(3, 11)
        entry = self.new_item(oz, record)
        flags: list[str] = []
        extra: list[str] = []
        first, second, third = record.field(12, 12), record.field(13, 13), record.field(14, 14)
        group = record.field(15, 18).strip()
        if first == "G":
            flags.append("ALNSerNo=0")
        elif first == "A":
            flags.append(f"ALNSerNo={group if group.strip('0') else '1'}")
        elif first not in ("N", " "):
            extra.append(f"Positionsart 1 = {first}")
        if second == "E":
            flags.append("Provis=WithoutTotal")
        elif second == "M":
            flags.append("Provis=WithTotal")
        elif second not in ("N", " "):
            extra.append(f"Positionsart 2 = {second}")
        if third not in ("N", " "):
            extra.append(f"Positionsart 3 = {third}")
        marker = record.field(21, 21)
        if marker == "W":
            extra.append("Wiederholungsposition")
        elif marker == "B":
            extra.append("Bezugsposition")
        elif marker != " ":
            extra.append(f"Kennzeichen {marker}")
        entry.flags = tuple(flags)
        entry.extra_types = tuple(extra)
        entry.qty = _number(record, 24, 34, 3, "quantity")
        unit = record.field(35, 38).strip()
        entry.unit = XmlValue(unit, record.line) if unit else None
        self.item = self.target = entry

    def prices(self, record: _Record) -> None:
        oz = record.field(3, 11)
        entry = self.items.get(oz)
        if entry is None:  # a D84 bid may state prices without the item record
            entry = self.new_item(oz, record)
        if record.field(23, 23).strip():  # tenth of a cent given: three decimals
            entry.unit_price = _number(record, 13, 23, 3, "unit price")
        else:
            entry.unit_price = _number(record, 13, 22, 2, "unit price")
        entry.total = _number(record, 25, 36, 2, "total")
        self.item = self.target = entry

    def text(self, record: _Record) -> None:
        target = self.target
        if not isinstance(target, GaebEntry):
            self.not_shown[f"Satzart {record.kind} ohne Position"] += 1
            return
        if record.kind == "25":
            target.short_text = _join(target.short_text, record.field(3, DATA_END))
        else:
            target.long_text = _join(target.long_text, record.field(6, DATA_END))

    def end(self, record: _Record) -> None:
        total = _number(record, 3, 14, 2, "bill total")
        gross = _number(record, 26, 37, 2, "gross total")
        if total is not None and not _is_zero(total):
            self.document.total = total
            if gross is not None and not _is_zero(gross):
                self.document.total_gross = gross
                self.document.vat_percent = _number(record, 22, 25, 2, "VAT percent")
        self.target = self.item = None
