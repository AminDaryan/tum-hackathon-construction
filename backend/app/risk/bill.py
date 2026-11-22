"""The bill as the risk checks read it: positions with their texts, sections, notes and keys.

:func:`read_bill` reads a canonical dataset through the validation context's accessors, the
same way the detectors do (markers stay markers, unusable numbers stay ``None``, rows a
reviewer excluded are skipped). Any other reader can build a :class:`Bill` from plain values
with :func:`make_position` (the evaluation scripts do, for files the import cannot read yet).

Component keys tie positions to the same part of the works (building, storey, room, axis,
component, system). They come from a position's short text and the titles of its sections,
except sections that hold every position of their table (the whole bill), which every
position shares. :func:`link` decides whether work found in one position may count for
another: an explicit reference, a shared component, system, room or axis key, or the same
component word at the same location links them; a different value of the same kind separates
them; anything else stays a candidate only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from app.core.codes import code_segments
from app.models.dataset import CellRef, Row, RowKind, Table
from app.risk.models import LinkKind, PositionRef
from app.risk.tables import Components
from app.risk.text import find_all, fold
from app.validation.contracts.context import ValidationContext

Key = tuple[str, str]  # (kind, value), e.g. ("storey", "eg")
# Keys specific enough to tie two positions alone; a building or a storey needs the other too.
_SPECIFIC = frozenset({"component", "system", "room", "axis"})
_FIELDS = (
    "item_code",
    "description",
    "long_description",
    "quantity",
    "unit",
    "unit_price",
    "line_total",
)


@dataclass(frozen=True, slots=True)
class Position:
    key: str  # "<table_id>/<row_id>"
    table_id: str
    row_id: str
    table_name: str
    label: str  # the item code, or "row N" when the row has none
    item_code: str | None
    short_text: str
    long_text: str
    item_type: str | None
    folded: str  # folded short text, long text and item type, for matching
    folded_short: str
    unit: str | None
    dimension: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    line_total: Decimal | None
    currency: str | None
    counts_toward_totals: bool | None
    sections: tuple[str, ...]  # enclosing section ids, outermost first
    cells: Mapping[str, CellRef]
    keys: frozenset[Key] = frozenset()
    references: frozenset[tuple[str, ...]] = frozenset()  # code segments of named positions

    @property
    def lump_sum(self) -> bool:
        return self.dimension == "lump_sum"

    @property
    def original(self) -> str:
        """Short and long text as the bill states them (what quotes are cut from)."""
        return "\n".join(t for t in (self.short_text, self.long_text) if t)

    def ref(self, *fields: str) -> PositionRef:
        cells = [self.cells[f] for f in fields if f in self.cells]
        return PositionRef(
            label=self.label,
            item_code=self.item_code,
            table_id=self.table_id,
            row_id=self.row_id,
            cells=cells,
        )


@dataclass(frozen=True, slots=True)
class Section:
    section_id: str
    title: str
    keys: frozenset[Key]
    bill_wide: bool  # holds every position of its table


@dataclass(frozen=True, slots=True)
class Note:
    """Text that belongs to no position: preliminary notes of the bill or of a section."""

    section_id: str | None  # None: a general note of the whole bill
    text: str
    folded: str
    source: str  # "general note" or "note of section '<title>'"


@dataclass(frozen=True, slots=True)
class Bill:
    positions: tuple[Position, ...]
    sections: Mapping[str, Section] = field(default_factory=dict)
    notes: tuple[Note, ...] = ()
    currency: str | None = None
    counted_total: Decimal | None = None
    documents: int = 1  # documents the project scope searched (one dataset today)

    @property
    def priced(self) -> bool:
        return any(p.unit_price is not None and p.unit_price != 0 for p in self.positions)

    def by_code(self, segments: tuple[str, ...]) -> Position | None:
        return self._codes().get(segments)

    def _codes(self) -> dict[tuple[str, ...], Position]:
        codes: dict[tuple[str, ...], Position] = {}
        for position in self.positions:
            segments = code_segments(position.item_code)
            if segments:
                codes.setdefault(segments, position)
        return codes

    def scope_id(self, position: Position, scope: str) -> str:
        """Where a dependency rule searches: the outermost section of the position that is not
        the whole bill ("section" and "component" scope), or the whole document."""
        if scope == "project":
            return "document"
        for section_id in position.sections:
            section = self.sections.get(section_id)
            if section is not None and not section.bill_wide:
                return section_id
        return f"table:{position.table_id}"

    def scope_title(self, scope_id: str) -> str:
        if scope_id == "document":
            return "the whole document"
        section = self.sections.get(scope_id)
        if section is not None:
            return f"section '{section.title}'"
        return "the whole table"

    def in_scope(self, scope_id: str) -> list[Position]:
        if scope_id == "document":
            return list(self.positions)
        if scope_id.startswith("table:"):
            table_id = scope_id.removeprefix("table:")
            return [p for p in self.positions if p.table_id == table_id]
        return [p for p in self.positions if scope_id in p.sections]

    def notes_for(self, position: Position) -> list[Note]:
        """General notes and the notes of every section that encloses the position."""
        return [n for n in self.notes if n.section_id is None or n.section_id in position.sections]


# ----------------------------------------------------------------------------- keys and links
def keys_of(folded: str, components: Components) -> frozenset[Key]:
    keys: set[Key] = set()
    for spec in components.keys:
        for _, _, found in find_all(spec.pattern, folded):
            groups = [g or "" for g in found.groups()]
            value = spec.value
            for index, group in enumerate(groups, start=1):
                value = value.replace(f"{{{index}}}", "".join(group.split()).rstrip("."))
            keys.add((spec.kind, value))
    return frozenset(keys)


def references_of(folded: str, components: Components) -> frozenset[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for pattern in components.references:
        for _, _, match in find_all(pattern, folded):
            segments = code_segments(match.group(1))
            if segments:
                found.add(segments)
    return frozenset(found)


def link(a: Position, b: Position, word: str | None = None) -> tuple[LinkKind, str]:
    """Whether work found in ``b`` may count for ``a``, and why.

    Linked: ``b`` and ``a`` name each other; or they share a component, system, room or axis
    key, or both the building and the storey; or ``b`` names ``word`` (the component word that
    made ``a`` relevant, e.g. "kellerwand") and the same location, or ``a`` names no location.
    Different: ``b`` names another value of a key kind ``a`` has. Anything else is not linked:
    a candidate only."""
    if a.key == b.key:
        return LinkKind.SAME_POSITION, "stated in the position itself"
    a_code, b_code = code_segments(a.item_code), code_segments(b.item_code)
    if (b_code and b_code in a.references) or (a_code and a_code in b.references):
        return LinkKind.EXPLICIT_REFERENCE, f"{a.label} and {b.label} name each other"
    kinds = {k for k, _ in a.keys} & {k for k, _ in b.keys}
    for kind in sorted(kinds):
        mine = {v for k, v in a.keys if k == kind}
        theirs = {v for k, v in b.keys if k == kind}
        if not mine & theirs:
            return (
                LinkKind.DIFFERENT,
                f"{b.label} names another {kind} ({', '.join(sorted(theirs))} instead of "
                f"{', '.join(sorted(mine))})",
            )
    shared = sorted(a.keys & b.keys)
    named = ", ".join(f"{kind} {value}" for kind, value in shared)
    shared_kinds = {kind for kind, _ in shared}
    if shared_kinds & _SPECIFIC or {"building", "storey"} <= shared_kinds:
        return LinkKind.SHARED_KEY, f"same {named}"
    # A German plural may change the word's end (Kellerwand -> Kellerwaende): compare without it.
    stem = word[:-2] if word and len(word) > 6 else word
    if stem and stem in b.folded and (shared or not a.keys):
        where = f" and the same {named}" if shared else "; neither names a location"
        return LinkKind.SHARED_KEY, f"{b.label} names the same component ('{word}'){where}"
    if shared:
        return (
            LinkKind.NOT_LINKED,
            f"{b.label} shares only the {named}; no component, system, room or axis ties it to "
            f"{a.label}",
        )
    return LinkKind.NOT_LINKED, f"nothing ties {b.label} to {a.label} (no shared key or reference)"


# ----------------------------------------------------------------------------- building
def make_position(
    *,
    table_id: str,
    row_id: str,
    table_name: str = "",
    item_code: str | None,
    short_text: str | None,
    long_text: str | None = None,
    item_type: str | None = None,
    unit: str | None = None,
    dimension: str | None = None,
    quantity: Decimal | None = None,
    unit_price: Decimal | None = None,
    line_total: Decimal | None = None,
    currency: str | None = None,
    counts_toward_totals: bool | None = True,
    sections: tuple[str, ...] = (),
    section_keys: Iterable[Key] = (),
    cells: Mapping[str, CellRef] | None = None,
    row_number: int | None = None,
    components: Components,
) -> Position:
    short = " ".join((short_text or "").split())
    long = (long_text or "").strip()
    folded_short = fold(short)
    original = "\n".join(t for t in (short, long) if t)
    # Folded original first, so a match position in it is also a position in the quote source.
    folded = " ".join(t for t in (fold(original), fold(item_type)) if t)
    label = (item_code or "").strip() or (f"row {row_number}" if row_number else row_id)
    return Position(
        key=f"{table_id}/{row_id}",
        table_id=table_id,
        row_id=row_id,
        table_name=table_name,
        label=label[:200],
        item_code=(item_code or "").strip() or None,
        short_text=short,
        long_text=long,
        item_type=item_type,
        folded=folded,
        folded_short=folded_short,
        unit=unit,
        dimension=dimension,
        quantity=quantity,
        unit_price=unit_price,
        line_total=line_total,
        currency=currency,
        counts_toward_totals=counts_toward_totals,
        sections=sections,
        cells=MappingProxyType(dict(cells or {})),
        keys=keys_of(folded_short, components) | frozenset(section_keys),
        references=references_of(folded, components),
    )


def counted_total(positions: Iterable[Position]) -> tuple[Decimal | None, str | None]:
    """Sum of the line totals of positions that count toward the total, and their currency.
    ``(None, None)`` when no position has a line total or the currencies differ."""
    counted = [p for p in positions if p.counts_toward_totals is True and p.line_total is not None]
    if not counted:
        return None, None
    currencies = {p.currency for p in counted}
    if len(currencies) > 1:
        return None, None
    return sum((p.line_total for p in counted if p.line_total is not None), Decimal(0)), next(
        iter(currencies)
    )


def _unit_text(
    context: ValidationContext, table: Table, row: Row, unit_field: str | None
) -> str | None:
    """The unit as the bill writes it ("St", "psch"), not its vocabulary id ("pcs", "ls")."""
    if unit_field is None:
        return None
    cell = context.cell(table, row, unit_field)
    written = (cell.raw_value or "").strip() if cell is not None else ""
    return written or context.text(table, row, unit_field)


def read_bill(context: ValidationContext, components: Components) -> Bill:
    """The bill of a validation context's dataset (every table)."""
    positions: list[Position] = []
    sections: dict[str, Section] = {}
    notes: list[Note] = []
    unit_field = context.unit_field_id()
    for table in context.tables():
        section_rows = list(context.rows(table, (RowKind.SECTION,)))
        item_rows = list(context.rows(table))
        titles = {
            row.row_id: _row_text(context, table, row) or f"row {row.source_row_number}"
            for row in section_rows
        }
        holds = Counter(s for row in item_rows for s in row.section_path)
        for row in section_rows:
            bill_wide = bool(item_rows) and holds[row.row_id] == len(item_rows)
            sections[row.row_id] = Section(
                section_id=row.row_id,
                title=titles[row.row_id],
                keys=frozenset() if bill_wide else keys_of(fold(titles[row.row_id]), components),
                bill_wide=bill_wide,
            )
        continuation: dict[str, list[str]] = {}
        for row in context.rows(table, (RowKind.TEXT,)):
            text = _row_text(context, table, row)
            if not text:
                continue
            if row.belongs_to_row_id is not None:
                continuation.setdefault(row.belongs_to_row_id, []).append(text)
                continue
            section = sections.get(row.section_row_id or "")
            if section is not None and section.bill_wide:
                section = None  # a note of the whole bill
            notes.append(
                Note(
                    section_id=section.section_id if section else None,
                    text=text,
                    folded=fold(text),
                    source=f"note of section '{section.title}'" if section else "general note",
                )
            )
        for row in item_rows:
            unit = context.unit(table, row, unit_field) if unit_field else None
            long_parts = [context.text(table, row, "long_description") or ""]
            long_parts += continuation.get(row.row_id, [])
            section_keys = {
                key for s in row.section_path if s in sections for key in sections[s].keys
            }
            positions.append(
                make_position(
                    table_id=table.table_id,
                    row_id=row.row_id,
                    table_name=table.name,
                    item_code=context.text(table, row, "item_code"),
                    short_text=context.text(table, row, "description"),
                    long_text="\n".join(p for p in long_parts if p),
                    item_type=context.text(table, row, "item_type"),
                    unit=_unit_text(context, table, row, unit_field),
                    dimension=unit.unit.dimension if unit is not None else None,
                    quantity=context.number(table, row, "quantity"),
                    unit_price=context.number(table, row, "unit_price"),
                    line_total=context.number(table, row, "line_total"),
                    currency=context.currency_evidence(table, row, ["line_total", "unit_price"]),
                    counts_toward_totals=row.counts_toward_totals,
                    sections=tuple(row.section_path),
                    section_keys=section_keys,
                    cells={
                        f: context.cell_ref(table, row, f)
                        for f in _FIELDS
                        if context.column(table, f) is not None
                    },
                    row_number=row.source_row_number,
                    components=components,
                )
            )
    total, currency = counted_total(positions)
    return Bill(
        positions=tuple(positions),
        sections=MappingProxyType(sections),
        notes=tuple(notes),
        currency=currency,
        counted_total=total,
    )


def _row_text(context: ValidationContext, table: Table, row: Row) -> str:
    """The text of a section or note row: its description, else its item code, else every
    text cell of the row."""
    for field_id in ("description", "item_code"):
        text = context.text(table, row, field_id)
        if text:
            return text
    parts = [context.text_at(row, column.column_id) for column in table.columns]
    return " ".join(p for p in parts if p)
