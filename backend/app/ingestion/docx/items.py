"""A bill written in a Word document as a list of item paragraphs, read into the bill model.

Some bills, and extracts of bills, are written as paragraphs rather than a table::

    Asphalt
    2.3.10 – Straßendecke schneiden (Vor- und Nachschnitt) [m]
    2.3.20 – Straßenaufbruch bituminöser Oberbau [m²]
    oder
    3.1.60 <tab> Muffendruckrohr TYT <tab> m <tab> 120,000 <tab> 45,50 <tab> 5.460,00

**Items.** A paragraph that starts with an item number (OZ: at least two numeric parts, ``1.10``,
``01.02.0030``; ``Pos.`` may stand before it), then a dash, tab or space and the text. Its unit
is the bracketed text at the end (``[m²]``) or a unit among its tab-separated columns; numbers
among those columns, in German notation (``1.234,50``), are the quantity, the unit price and the
line total, in that order. A document is read as a bill only when at least :data:`MIN_ITEMS`
such paragraphs state a unit or a quantity, so numbered text (contract conditions,
``1.1 Geltungsbereich``) is not mistaken for one.

**Sections.** A Word heading (heading style or outline level); a numbered paragraph without a
unit whose number begins later item numbers (``2.3 Asphalt`` before ``2.3.10``, also one-part
``01 Erdarbeiten``), which sits inside the numbered section its number begins with; and a short
unnumbered line followed by an item or set apart by an empty line (``Asphalt``).

**Text.** Other paragraphs after an item are its long text. A single linking word (``oder``,
``mit``) or an ellipsis between items, and text before the first item, become note rows, so the
reader sees them in place. All of this is inferred from the layout, and the adapter says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingestion.docx.document import Paragraph
from app.ingestion.gaeb.model import (
    DOCX_VERSION,
    EntryKind,
    GaebCategory,
    GaebDocument,
    GaebEntry,
    XmlValue,
)
from app.ingestion.pdf.bill import german_decimal

MIN_ITEMS = 3  # item paragraphs with a unit or quantity before a document counts as a bill
MAX_LABEL_CHARS = 80  # an unnumbered section label is a short line
MAX_LABEL_WORDS = 10

_OZ = r"\d{1,4}(?:\.\d{1,4}){1,5}[a-z]?\.?"
_ITEM = re.compile(
    rf"^(?:Pos(?:ition)?\.?\s*)?(?P<oz>{_OZ})(?:\s*[–—-]\s+|\t+|\s+)(?P<rest>\S.*)$", re.S
)
# A one-part group number before its label: "01 Erdarbeiten", "2. Rohbau".
_TITLE = re.compile(r"^(?P<oz>\d{1,4})\.?\s+(?P<label>[^\d\s].*)$", re.S)
_BRACKET_UNIT = re.compile(r"\s*\[(?P<unit>[^\[\]\n]{1,15})\]\s*$")
_NUMBER = re.compile(r"^-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?$")
_UNIT = re.compile(r"^[A-Za-zÄÖÜäöüß%][A-Za-zÄÖÜäöüß0-9²³./%\-]{0,11}$")
_CURRENCY = re.compile(r"\s*(?:€|EUR)\s*$", re.I)
_LINKS = frozenset(
    {"oder", "mit", "und", "bzw.", "alternativ", "wahlweise", "zzgl.", "or", "and", "with"}
)
_ELLIPSIS = re.compile(r"^(?:…|\.{2,})$")
_SENTENCE_END = (".", ":", ";", ",", "!", "?")


@dataclass(frozen=True, slots=True)
class _Line:
    """A paragraph read as an item line: its number, text and stated values."""

    paragraph: Paragraph
    number: str
    text: str
    unit: str | None
    numbers: tuple[str, ...]  # decimal text, in the order written

    @property
    def measured(self) -> bool:
        return self.unit is not None or bool(self.numbers)

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(part.lstrip("0") or "0" for part in self.number.rstrip(".").split("."))


@dataclass(frozen=True, slots=True)
class ItemList:
    """The bill and what was read: counts for the adapter's note."""

    document: GaebDocument
    items: int
    sections: int
    notes: int


def read_item_list(paragraphs: list[Paragraph]) -> ItemList | None:
    """The bill the paragraphs write as a list, or ``None`` when they are not one."""
    lines = {p.number: line for p in paragraphs if (line := item_line(p)) is not None}
    if sum(1 for line in lines.values() if line.measured) < MIN_ITEMS:
        return None
    return _Builder(paragraphs, lines).build()


def item_line(paragraph: Paragraph) -> _Line | None:
    """The paragraph as an item line, when it starts with an item number."""
    match = _ITEM.match(paragraph.text.strip())
    if match is None:
        return None
    columns = [part.strip() for part in match.group("rest").split("\t") if part.strip()]
    text = columns[0] if columns else ""
    unit: str | None = None
    numbers: list[str] = []
    extra: list[str] = []
    for column in columns[1:]:
        value = _CURRENCY.sub("", column)
        bracket = _BRACKET_UNIT.fullmatch(value)
        if _NUMBER.fullmatch(value):
            numbers.append(german_decimal(value))
        elif bracket is not None and unit is None:
            unit = bracket.group("unit").strip()
        elif _UNIT.fullmatch(value) and unit is None:
            unit = value
        else:
            extra.append(column)
    bracket = _BRACKET_UNIT.search(text)
    if bracket is not None:
        unit = unit or bracket.group("unit").strip()
        text = text[: bracket.start()]
    text = " ".join([text, *extra]).strip()
    return _Line(paragraph, match.group("oz"), text, unit, tuple(numbers))


@dataclass(slots=True)
class _Open:
    """An open section: its level among the open sections, whether a Word heading opened it,
    and its number's parts (``None`` for an unnumbered heading or label)."""

    level: int
    category: GaebCategory
    heading: bool
    parts: tuple[str, ...] | None


@dataclass(slots=True)
class _Builder:
    paragraphs: list[Paragraph]
    lines: dict[int, _Line]
    document: GaebDocument = field(
        default_factory=lambda: GaebDocument(
            version=DOCX_VERSION, phase="", dp="", schema_file=None, schema_sha256=None, line=None
        )
    )
    stack: list[_Open] = field(default_factory=list)
    item: GaebEntry | None = None  # the item that following text belongs to
    after_blank: bool = False  # the paragraph being read follows an empty one
    items: int = 0
    sections: int = 0
    notes: int = 0

    def build(self) -> ItemList:
        filled = [p for p in self.paragraphs if p.text.strip()]
        blank_before = {
            p.number
            for before, p in zip(self.paragraphs, self.paragraphs[1:], strict=False)
            if not before.text.strip()
        }
        measured = [line.parts for line in self.lines.values() if line.measured]
        for index, paragraph in enumerate(filled):
            following = filled[index + 1] if index + 1 < len(filled) else None
            self.after_blank = paragraph.number in blank_before
            line = self.lines.get(paragraph.number)
            title = _TITLE.match(paragraph.text.strip()) if line is None else None
            if line is not None and line.measured:
                self.add_item(line)
            elif paragraph.heading_level is not None:
                number, label = (line.number, line.text) if line else ("", paragraph.text)
                self.section(number, label, paragraph, paragraph.heading_level, heading=True)
            elif line is not None and _begins(line.parts, measured):
                self.numbered_section(line.number, line.text, paragraph)
            elif line is not None:
                self.add_item(line)  # numbered, without unit or quantity (a lump sum, say)
            elif (
                title is not None
                and _is_label(title.group("label"))
                and _begins((title.group("oz").lstrip("0") or "0",), measured)
            ):
                self.numbered_section(title.group("oz"), title.group("label"), paragraph)
            else:
                self.text(paragraph, following)
        return ItemList(self.document, self.items, self.sections, self.notes)

    # ------------------------------------------------------------------ sections
    def section(
        self, number: str, label: str, paragraph: Paragraph, level: int, *, heading: bool = False
    ) -> None:
        """A heading or an unnumbered label: it closes the open sections of its level or below."""
        while self.stack and self.stack[-1].level >= level:
            self.stack.pop()
        self.open(number, label, paragraph, level, heading=heading)

    def numbered_section(self, number: str, label: str, paragraph: Paragraph) -> None:
        """A numbered group (``2 Erdarbeiten``, ``2.3 Asphalt``): it sits inside the open
        numbered group its number begins with (2.3 in 2), or else inside the innermost heading
        or label; 3.1 after 2.3 leaves both 2.3 and 2."""
        parts = tuple(part.lstrip("0") or "0" for part in number.rstrip(".").split("."))
        while self.stack and self.stack[-1].parts is not None:
            top = self.stack[-1].parts
            if len(top) < len(parts) and parts[: len(top)] == top:
                break
            self.stack.pop()
        level = self.stack[-1].level + 1 if self.stack else 1
        self.open(number, label, paragraph, level, parts=parts)

    def open(
        self,
        number: str,
        label: str,
        paragraph: Paragraph,
        level: int,
        *,
        heading: bool = False,
        parts: tuple[str, ...] | None = None,
    ) -> None:
        category = GaebCategory(
            element_id=None,
            number=number.rstrip("."),
            label=" ".join(label.split()),
            line=paragraph.number,
            level=len(self.stack) + 1,  # depth in the bill
        )
        self.children().append(category)
        self.stack.append(_Open(level, category, heading, parts))
        self.item = None
        self.sections += 1

    def children(self) -> list[GaebCategory | GaebEntry]:
        return self.stack[-1].category.children if self.stack else self.document.body

    def label_level(self) -> int:
        """An unnumbered label groups items under the innermost Word heading, else at the top."""
        headings = [open_.level for open_ in self.stack if open_.heading]
        return headings[-1] + 1 if headings else 1

    # ------------------------------------------------------------------ items and text
    def add_item(self, line: _Line) -> None:
        at = line.paragraph.number
        values = [XmlValue(number, at) for number in line.numbers]
        entry = GaebEntry(
            kind=EntryKind.ITEM,
            element="Item",
            element_id=None,
            number=line.number.rstrip("."),
            line=at,
            short_text=" ".join(line.text.split()),
            qty=values[0] if len(values) > 0 else None,
            unit=XmlValue(line.unit, at) if line.unit else None,
            unit_price=values[1] if len(values) > 1 else None,
            total=values[2] if len(values) > 2 else None,
        )
        self.children().append(entry)
        self.item = entry
        self.items += 1

    def text(self, paragraph: Paragraph, following: Paragraph | None) -> None:
        text = paragraph.text.strip()
        before_item = following is not None and following.number in self.lines
        if text.lower() in _LINKS or _ELLIPSIS.match(text):
            self.note(paragraph)
        elif _is_label(text) and (before_item or self.after_blank):
            # a short line before an item, or set apart by an empty line: a group heading
            self.section("", text, paragraph, self.label_level())
        elif self.item is not None:
            self.item.long_text = f"{self.item.long_text}\n{text}" if self.item.long_text else text
        else:
            self.note(paragraph)

    def note(self, paragraph: Paragraph) -> None:
        self.children().append(
            GaebEntry(
                kind=EntryKind.NOTE,
                element="Remark",
                element_id=None,
                number="",
                line=paragraph.number,
                short_text=" ".join(paragraph.text.split()),
            )
        )
        self.notes += 1


def _begins(parts: tuple[str, ...], item_numbers: list[tuple[str, ...]]) -> bool:
    """Whether ``parts`` is the beginning of a (longer) item number."""
    return any(len(other) > len(parts) and other[: len(parts)] == parts for other in item_numbers)


def _is_label(text: str) -> bool:
    return (
        len(text) <= MAX_LABEL_CHARS
        and len(text.split()) <= MAX_LABEL_WORDS
        and "\t" not in text
        and not text.endswith(_SENTENCE_END)
    )
