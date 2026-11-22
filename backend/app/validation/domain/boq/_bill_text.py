"""The texts of a bill, as the BoQ wording checks read them (private module: not discovered).

``boq_companion_work``, ``boq_separate_payment`` and ``boq_required_attributes`` read a bill's
texts the same way:

* **Rows are read directly**, following ``standard_text_keys``, not through the item frame
  (:mod:`app.validation.support.items`): the frame covers only tables that map a unit price,
  and a tender exported to a spreadsheet without an EP column must be checked as well. Item
  rows and text rows (notes such as GAEB "Hinweis") are read; a check decides which it uses.
* **An entry's text** is its Kurztext (``description``) and its Langtext
  (``long_description``). Continuation rows (text rows that ``belongs_to_row_id`` links to an
  item) are appended to that item's Langtext.
* **Anonymisation tokens** (``[PERSON_074]``, ``ORT_030``, ``PER89``, ``TEL00009``, ``###``)
  are replaced by spaces of the same length before any pattern sees the text
  (:func:`app.validation.support.tokens.mask_tokens`), so no check flags or quotes a token as
  wording, a typo or a material. Offsets stay those of the text as written, so quotes are cut
  from the original.
* **Patterns** are applied through :mod:`app.core.patterns` (case-insensitive) to windows of
  at most ``MAX_MATCH_CHARS`` characters, cut at whitespace and overlapping by
  :data:`WINDOW_OVERLAP` characters (``windows`` of ``deterministic._reference_support``):
  each call stays bounded however long a Langtext is, and a word deep inside one is still
  found. A match longer than the overlap that crosses a cut can be missed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core import patterns
from app.core.codes import code_segments
from app.models.dataset import CellRef, Row, RowKind, Table
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import Applicability
from app.validation.deterministic._reference_support import (
    clip,
    find_spans,
    match_window,
    windows,
)
from app.validation.support.tokens import mask_tokens

__all__ = [
    "TEXT_ROW_KINDS",
    "WINDOW_OVERLAP",
    "Bill",
    "BillFields",
    "Entry",
    "Found",
    "description_applicability",
    "entry_cells",
    "list_codes",
    "read_bill",
    "search",
    "search_all",
    "search_start",
]

WINDOW_OVERLAP = 100
MAX_MATCHES = 16  # matches collected from one text by search_all
TEXT_ROW_KINDS = frozenset({RowKind.ITEM, RowKind.TEXT})


@dataclass(frozen=True, slots=True)
class BillFields:
    """The fields a check reads its texts from."""

    description: str
    long_description: str
    item_code: str


@dataclass(frozen=True, slots=True)
class Found:
    """A match: offsets into the text it was searched in."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Entry:
    """An item or a note of a bill. ``short`` and ``long`` are the texts with tokens masked;
    ``original`` is ``text`` as written (same length, so offsets carry over)."""

    table: Table
    row: Row
    is_item: bool
    code: str | None
    short: str
    long: str
    original: str

    @property
    def text(self) -> str:
        """Kurztext and Langtext, separated by a line break."""
        return f"{self.short}\n{self.long}" if self.long else self.short

    @property
    def long_offset(self) -> int:
        """Where the Langtext starts in :attr:`text`."""
        return len(self.short) + 1

    @property
    def label(self) -> str:
        """The OZ, or the source row when the entry has none."""
        return self.code or f"row {self.row.source_row_number}"

    @property
    def top_section(self) -> str | None:
        """The first segment of a dotted OZ ("01" of "01.02.0030"), ``None`` without one."""
        segments = code_segments(self.code)
        return segments[0] if segments is not None and len(segments) > 1 else None

    @property
    def section(self) -> tuple[str, ...] | None:
        """The innermost section: its row id, else the OZ without its last segment."""
        if self.row.section_row_id is not None:
            return ("row", self.row.section_row_id)
        segments = code_segments(self.code)
        return ("code", *segments[:-1]) if segments is not None and len(segments) > 1 else None

    def quote(self, found: Found, limit: int = 160) -> str:
        """The sentence around a match in :attr:`text`, as written, clipped to ``limit``
        characters. A long sentence is shown from shortly before the match."""
        text = self.original
        stops = (text.rfind(". ", 0, found.start), text.rfind("\n", 0, found.start))
        start = max((stop + 1 for stop in stops if stop >= 0), default=0)
        ends = [i for i in (text.find(". ", found.end), text.find("\n", found.end)) if i >= 0]
        end = min(ends) + 1 if ends else len(text)
        prefix = ""
        if found.start - start > limit // 2:
            start = text.find(" ", found.start - limit // 3, found.start) + 1 or found.start
            prefix = "…"
        return clip(prefix + " ".join(text[start:end].split()), limit)

    def quote_short(self, limit: int = 100) -> str:
        """The Kurztext as written, clipped."""
        return clip(" ".join(self.original[: len(self.short)].split()), limit)


@dataclass(slots=True)
class Bill:
    """The entries of one table in source order."""

    table: Table
    entries: list[Entry] = field(default_factory=list)

    @property
    def items(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.is_item]

    @property
    def has_long_texts(self) -> bool:
        """Whether any item has a Langtext (a bid file may carry Kurztexts only)."""
        return any(entry.is_item and entry.long.strip() for entry in self.entries)


def description_applicability(context: ValidationContext, description_field: str) -> Applicability:
    """A text check applies where a table maps the item description (``description_field``)."""
    tables = [t.name for t in context.tables() if context.has_fields(t, description_field)]
    if not tables:
        return Applicability.no("No table maps the item description.")
    return Applicability.yes(f"Item descriptions are mapped in: {', '.join(tables)}.")


def read_bill(context: ValidationContext, table: Table, fields: BillFields) -> Bill:
    """The items and notes of ``table`` with their texts (see the module docstring)."""
    has_long = context.has_fields(table, fields.long_description)
    has_code = context.has_fields(table, fields.item_code)
    parts: dict[str, tuple[Row, str, list[str]]] = {}
    order: list[str] = []
    for row in context.rows(table, TEXT_ROW_KINDS):
        short = context.text(table, row, fields.description) or ""
        long = (context.text(table, row, fields.long_description) or "") if has_long else ""
        owner = row.belongs_to_row_id
        if row.kind is RowKind.TEXT and owner is not None and owner in parts:
            parts[owner][2].extend(text for text in (short, long) if text)
            continue
        parts[row.row_id] = (row, short, [long] if long else [])
        order.append(row.row_id)
    bill = Bill(table)
    for row_id in order:
        row, short, longs = parts[row_id]
        long = "\n".join(longs)
        original = f"{short}\n{long}" if long else short
        code = context.text(table, row, fields.item_code) if has_code else None
        bill.entries.append(
            Entry(
                table=table,
                row=row,
                is_item=row.kind is RowKind.ITEM,
                code=" ".join(code.split()) if code else None,
                short=mask_tokens(short),
                long=mask_tokens(long),
                original=original,
            )
        )
    return bill


def search(pattern: str, text: str) -> Found | None:
    """The first match of ``pattern`` anywhere in ``text`` (window by window)."""
    for offset, window in windows(text, WINDOW_OVERLAP):
        match = patterns.search(pattern, window)
        if match is not None:
            return Found(offset + match.start(), offset + match.end())
    return None


def search_start(pattern: str, text: str) -> Found | None:
    """A match of ``pattern`` in the first window of ``text`` only: for patterns anchored at
    the start of the text (``^``), which must not match at a later window's start."""
    match = patterns.search(pattern, match_window(text)[0])
    return None if match is None else Found(match.start(), match.end())


def search_all(pattern: str, text: str, *, limit: int = MAX_MATCHES) -> list[Found]:
    """Non-overlapping matches of ``pattern`` in ``text``, leftmost first, at most ``limit``,
    found window by window as ``find_spans`` finds them; a match found again in the overlap
    of the next window is counted once."""
    found: list[Found] = []
    for offset, window in windows(text, WINDOW_OVERLAP):
        for start, end, _group in find_spans(pattern, window, limit=limit):
            hit = Found(offset + start, offset + end)
            if all(hit.start >= f.end or hit.end <= f.start for f in found):
                found.append(hit)
            if len(found) >= limit:
                return sorted(found, key=lambda f: f.start)
    return sorted(found, key=lambda f: f.start)


def list_codes(entries: list[Entry]) -> str:
    """Every entry's OZ (or row), comma-separated, in the given order."""
    return ", ".join(entry.label for entry in entries)


def entry_cells(
    context: ValidationContext, entries: list[Entry], field_id: str, cap: int
) -> list[CellRef]:
    """References to ``field_id`` of the first ``cap`` entries."""
    return [context.cell_ref(e.table, e.row, field_id) for e in entries[:cap]]
