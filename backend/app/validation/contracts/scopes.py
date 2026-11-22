"""Total scopes: which rows a subtotal or grand total sums, read every admissible way.

The rules are written in ``docs/architecture/validation-engine.md`` ("Total scopes"); this
module is their only implementation. ``deterministic.subtotal`` and
``deterministic.grand_total`` use it through :meth:`ValidationContext.rows_in_scope` and
:func:`judge`, so two detectors can never disagree about which rows a total sums.

* :func:`subtotal_bases` / :func:`grand_total_bases` build the candidate *bases* of a total
  row. Subtotal: the section it closes (the only basis when it exists), else the items whose
  code starts with its code, and the block since the previous boundary (or, when that block
  holds summary lines and no items, the summary block). Grand total: the counted items of its
  span, the summary lines of its span, and "previous grand total plus adjustments" when the
  span holds only adjustments and tax lines ("Summe nach Nachlass", or a "Gesamtsumme" after
  net and tax that was not worded as gross).
* :func:`net_layout` finds the net total of a TAX or GROSS_TOTAL row (the nearest preceding
  GRAND_TOTAL, with only adjustments, tax lines and text between them);
  :func:`net_bases` gives a tax line's candidate nets (that total, and that total plus the
  adjustments) and :func:`gross_total_bases` a gross total's basis (net, adjustments and tax
  lines).
* :func:`readings` enumerates the exact sums a basis admits: undecided items
  (``counts_toward_totals is None``) in or out, adjustments with their sign as written or
  reversed, hidden rows all in or all out. At most :data:`MAX_READINGS` distinct sums; beyond
  that only the all-in, all-out and as-written readings are kept (``truncated``).
* :func:`judge` compares a reported total with every reading of every complete basis and
  returns the outcome of the table in the doc.

Members are summed by their *reported* amounts, read through the context (``number`` and
``marker``), so the cell-condition rules hold here too: a zero-contribution marker
(``nil``, ``included_elsewhere``, ``not_applicable``, ``by_others``) counts as 0; any other
unusable amount of a counted member makes the basis incomplete (never summed partially). An
undecided item without a usable amount can only be "out" and is listed in
``Basis.without_amount``.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from app.core.codes import code_segments
from app.models.dataset import SCOPE_BOUNDARY_KINDS, Row, RowKind, Table
from app.models.profile import FieldRole
from app.validation.contracts.decimal_math import (
    Reconciliation,
    RoundingSpec,
    TolerancePolicy,
    add_all,
    multiply,
    reconcile,
)

if TYPE_CHECKING:
    from app.validation.contracts.context import ValidationContext

MAX_READINGS = 4096

_SPAN_BOUNDARIES = frozenset({RowKind.GRAND_TOTAL, RowKind.GROSS_TOTAL})
_SUMMED = frozenset({RowKind.ITEM, RowKind.ADJUSTMENT})
# Between a net total and its tax lines or gross total: members, and rows that are passed over.
_AFTER_NET = frozenset({RowKind.ADJUSTMENT, RowKind.TAX})
_AFTER_NET_NAMES = ((RowKind.ADJUSTMENT, "adjustments"), (RowKind.TAX, "tax lines"))
_IGNORED_AFTER_NET = frozenset({RowKind.TEXT, RowKind.BLANK, RowKind.CARRY_FORWARD})


class TermKind(StrEnum):
    REQUIRED = "required"  # always counted
    OPTIONAL = "optional"  # an undecided item: in or out
    ADJUSTMENT = "adjustment"  # a discount or surcharge: sign as written or reversed


@dataclass(frozen=True, slots=True)
class Term:
    row: Row
    kind: TermKind
    amount: Decimal  # the reported amount; 0 for a zero-contribution marker
    hidden: bool


class BasisKind(StrEnum):
    SECTION = "section"
    CODE = "code"
    BLOCK = "block"
    SUMMARY_BLOCK = "summary_block"
    SPAN = "span"  # grand total: the counted items (and adjustments) of its span
    SPAN_SUMMARY = "span_summary"  # grand total: the summary lines of its span
    AFTER_ADJUSTMENT = "after_adjustment"  # grand total: previous grand total + adjustments
    NET = "net"  # tax line: the net total alone
    NET_AFTER_ADJUSTMENT = "net_after_adjustment"  # tax line: net + the adjustments after it
    NET_AND_TAX = "net_and_tax"  # gross total: net + adjustments + tax lines


@dataclass(frozen=True, slots=True)
class NetLayout:
    """The rows from a net total to the TAX or GROSS_TOTAL row after it, in source order."""

    net: Row  # the nearest preceding GRAND_TOTAL
    adjustments: tuple[Row, ...]
    taxes: tuple[Row, ...]


@dataclass(frozen=True, slots=True)
class Basis:
    """One candidate set of members of a total."""

    kind: BasisKind
    description: str  # for explanations, e.g. "the items whose code starts with 01.02"
    terms: tuple[Term, ...]
    left_out: tuple[Row, ...] = ()  # items that never count here (listed in a note)
    without_amount: tuple[Row, ...] = ()  # undecided items without a usable amount: only "out"
    unusable: tuple[Row, ...] = ()  # counted members without a usable amount
    currencies: frozenset[str] = frozenset()  # explicit currencies of the members and total

    @property
    def complete(self) -> bool:
        return not self.unusable and len(self.currencies) <= 1

    @property
    def has_members(self) -> bool:
        return bool(self.terms or self.unusable)

    @property
    def members(self) -> frozenset[str]:
        return frozenset(term.row.row_id for term in self.terms)


@dataclass(frozen=True, slots=True)
class Reading:
    total: Decimal
    choices: tuple[str, ...]  # how it differs from the plain reading; () is the plain one

    def describe(self) -> str:
        return "; ".join(self.choices) if self.choices else "every member as written"


@dataclass(frozen=True, slots=True)
class ReadingSet:
    readings: tuple[Reading, ...]
    truncated: bool


class Outcome(StrEnum):
    CONSISTENT = "consistent"
    VIOLATION = "violation"  # confirmed_rule_violation
    UNDECIDED = "undecided"  # needs_external_context: the enumeration was truncated
    AMBIGUOUS_STRUCTURE = "ambiguous_structure"  # extraction_uncertainty
    DISPLAY_ROUNDING = "display_rounding"  # informational extraction_uncertainty
    NO_SCOPE = "no_scope"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class Verdict:
    outcome: Outcome
    bases: tuple[Basis, ...]  # the candidate bases with members
    basis: Basis | None = None  # the matching basis, or the one holding the closest reading
    reading: Reading | None = None
    reconciliation: Reconciliation | None = None
    readings_tested: int = 0
    truncated: bool = False


# ---------------------------------------------------------------------------- bases
def subtotal_bases(
    context: ValidationContext, table: Table, total: Row, field_id: str
) -> list[Basis]:
    """Candidate bases of a SUBTOTAL row (only those with members)."""
    index, at = _locate(context, table, total)
    inside = frozenset(total.section_path) | (
        {total.closes_section_id} if total.closes_section_id else frozenset()
    )
    build = _Builder(context, table, total, field_id, inside)
    section_id = total.closes_section_id
    if section_id is not None:
        start = index.position.get(section_id, 0)  # members follow their section's heading
        members = [
            r for r in index.rows[start:at] if r.kind in _SUMMED and section_id in r.section_path
        ]
        name = _section_name(table, section_id)
        basis = build(BasisKind.SECTION, f"the items of section {name}", members)
        return [basis] if basis.has_members else []
    bases: list[Basis] = []
    code = code_segments(total.classification.code)
    if code is not None and _identifier_field(context, table) is not None:
        # ITEM rows of the span whose code strictly extends ``code`` (see ``_TableIndex``).
        extending = index.items_by_prefix.get(code, [])
        first = bisect_left(extending, index.span_start[at])
        members = [index.rows[i] for i in extending[first : bisect_left(extending, at)]]
        bases.append(
            build(
                BasisKind.CODE,
                f"the items whose code starts with {total.classification.code}",
                members,
            )
        )
    block = index.rows[index.block_start[at] : at]
    summaries = [row for row in block if row.kind is RowKind.SUMMARY_LINE]
    if summaries and not any(row.kind is RowKind.ITEM for row in block):
        bases.append(
            build(BasisKind.SUMMARY_BLOCK, f"the summary lines {_rows_text(summaries)}", summaries)
        )
    else:
        members = [row for row in block if row.kind in _SUMMED]
        bases.append(build(BasisKind.BLOCK, f"the items {_rows_text(members)}", members))
    return [basis for basis in bases if basis.has_members]


def grand_total_bases(
    context: ValidationContext, table: Table, total: Row, field_id: str
) -> list[Basis]:
    """Candidate bases of a GRAND_TOTAL row (only those with members)."""
    index, at = _locate(context, table, total)
    start = index.span_start[at]
    span = index.rows[start:at]
    build = _Builder(context, table, total, field_id, frozenset())
    bases: list[Basis] = []
    adjustments = [row for row in span if row.kind is RowKind.ADJUSTMENT]
    items = [row for row in span if row.kind is RowKind.ITEM]
    summaries = [row for row in span if row.kind is RowKind.SUMMARY_LINE]
    if items:
        members = [row for row in span if row.kind in _SUMMED]
        bases.append(build(BasisKind.SPAN, f"the items {_rows_text(items)}", members))
    if summaries:
        bases.append(
            build(
                BasisKind.SPAN_SUMMARY,
                f"the summary lines {_rows_text(summaries)}",
                summaries + adjustments,
            )
        )
    previous = index.rows[start - 1] if start > 0 else None
    after = [row for row in span if row.kind in _AFTER_NET]
    if (
        after
        and not items
        and not summaries
        and previous is not None
        and previous.kind is RowKind.GRAND_TOTAL
    ):
        bases.append(
            build(
                BasisKind.AFTER_ADJUSTMENT,
                f"the total in row {previous.source_row_number} and the "
                f"{_after_net_text(after)} after it",
                [previous, *after],
            )
        )
    return [basis for basis in bases if basis.has_members]


def net_layout(context: ValidationContext, table: Table, row: Row) -> NetLayout | None:
    """The net total of a TAX or GROSS_TOTAL ``row`` and the adjustments and tax lines between
    them; ``None`` when no GRAND_TOTAL precedes ``row`` after the previous GROSS_TOTAL, or when
    other rows (items, sections, subtotals, summary lines) stand between them."""
    index, at = _locate(context, table, row)
    between: list[Row] = []
    for candidate in reversed(index.rows[:at]):
        if candidate.kind is RowKind.GRAND_TOTAL:
            between.reverse()
            return NetLayout(
                net=candidate,
                adjustments=tuple(r for r in between if r.kind is RowKind.ADJUSTMENT),
                taxes=tuple(r for r in between if r.kind is RowKind.TAX),
            )
        if candidate.kind in _AFTER_NET:
            between.append(candidate)
        elif candidate.kind not in _IGNORED_AFTER_NET:
            return None
    return None


def net_bases(
    context: ValidationContext, table: Table, layout: NetLayout, tax: Row, field_id: str
) -> list[Basis]:
    """Candidate nets of a TAX row: its net total alone, and (when there are adjustments
    between them) that total plus the adjustments, each as written or reversed."""
    build = _Builder(context, table, tax, field_id, frozenset())
    number = layout.net.source_row_number
    bases = [build(BasisKind.NET, f"the net total in row {number}", [layout.net])]
    if layout.adjustments:
        bases.append(
            build(
                BasisKind.NET_AFTER_ADJUSTMENT,
                f"the net total in row {number} and the adjustments after it",
                [layout.net, *layout.adjustments],
            )
        )
    return [basis for basis in bases if basis.has_members]


def gross_total_bases(
    context: ValidationContext, table: Table, total: Row, field_id: str
) -> list[Basis]:
    """The basis of a GROSS_TOTAL row: its net total, the adjustments and the tax lines between
    them. None without a net, or without a tax line (the tax is then not stated)."""
    layout = net_layout(context, table, total)
    if layout is None or not layout.taxes:
        return []
    after = [*layout.adjustments, *layout.taxes]
    after.sort(key=lambda row: row.position)
    build = _Builder(context, table, total, field_id, frozenset())
    basis = build(
        BasisKind.NET_AND_TAX,
        f"the net total in row {layout.net.source_row_number} and the "
        f"{_after_net_text(after)} after it",
        [layout.net, *after],
    )
    return [basis] if basis.has_members else []


def _after_net_text(rows: Sequence[Row]) -> str:
    kinds = {row.kind for row in rows}
    names = [name for kind, name in _AFTER_NET_NAMES if kind in kinds]
    return " and ".join(names)


@dataclass(frozen=True, slots=True)
class _Builder:
    context: ValidationContext
    table: Table
    total: Row
    field_id: str
    counts_inside: frozenset[str]  # sections whose not-counted-above items count here

    def __call__(self, kind: BasisKind, description: str, rows: Sequence[Row]) -> Basis:
        terms: list[Term] = []
        left_out: list[Row] = []
        without_amount: list[Row] = []
        unusable: list[Row] = []
        currencies: set[str] = set()
        for row in rows:
            term_kind = self._term_kind(row)
            if term_kind is None:
                left_out.append(row)
                continue
            amount = self._amount(row)
            if amount is None:
                (without_amount if term_kind is TermKind.OPTIONAL else unusable).append(row)
                continue
            currency = self.context.currency_evidence(self.table, row, [self.field_id])
            if currency is not None:
                currencies.add(currency)
            terms.append(Term(row, term_kind, amount, row.source_hidden))
        own = self.context.currency_evidence(self.table, self.total, [self.field_id])
        if own is not None:
            currencies.add(own)
        return Basis(
            kind=kind,
            description=description,
            terms=tuple(terms),
            left_out=tuple(left_out),
            without_amount=tuple(without_amount),
            unusable=tuple(unusable),
            currencies=frozenset(currencies),
        )

    def _term_kind(self, row: Row) -> TermKind | None:
        if row.kind is RowKind.ADJUSTMENT:
            return TermKind.ADJUSTMENT
        if row.kind is not RowKind.ITEM:  # summary lines, a previous grand total
            return TermKind.REQUIRED
        counts = row.classification.counts_toward_totals
        if counts is True:
            return TermKind.REQUIRED
        if counts is None:
            return TermKind.OPTIONAL
        above = row.classification.not_counted_above_section_id
        return TermKind.REQUIRED if above is not None and above in self.counts_inside else None

    def _amount(self, row: Row) -> Decimal | None:
        value = self.context.number(self.table, row, self.field_id)
        if value is not None:
            return value
        marker = self.context.marker(self.table, row, self.field_id)
        zero = marker is not None and marker in self.context.profile.zero_contribution_markers
        return Decimal(0) if zero else None


@dataclass(frozen=True, slots=True)
class _TableIndex:
    """Where a table's included rows stand, built once per context (the rows never change), so
    finding a total's members costs the size of its scope, not of everything before it."""

    rows: tuple[Row, ...]  # included rows in source order (excluded rows are never members)
    position: dict[str, int]  # row id -> index in ``rows``
    span_start: tuple[int, ...]  # per index (and len(rows)): just after the last GRAND/GROSS
    block_start: tuple[int, ...]  # per index (and len(rows)): just after the last boundary
    items_by_prefix: dict[tuple[str, ...], list[int]]  # code prefix -> ITEM indices extending it


def _locate(context: ValidationContext, table: Table, row: Row) -> tuple[_TableIndex, int]:
    """The table's index and ``row``'s position in it (``len(rows)`` when not included)."""
    key = ("scopes", table.table_id)
    index = context.memo.get(key)
    if not isinstance(index, _TableIndex):
        index = _build_index(context, table)
        context.memo[key] = index
    return index, index.position.get(row.row_id, len(index.rows))


def _build_index(context: ValidationContext, table: Table) -> _TableIndex:
    rows = tuple(context.rows(table, kinds=None))
    span_start: list[int] = []
    block_start: list[int] = []
    span = block = 0
    for position, row in enumerate(rows):
        span_start.append(span)
        block_start.append(block)
        if row.kind in _SPAN_BOUNDARIES:
            span = position + 1
        if row.kind in SCOPE_BOUNDARY_KINDS:
            block = position + 1
    span_start.append(span)
    block_start.append(block)
    items_by_prefix: dict[tuple[str, ...], list[int]] = defaultdict(list)
    identifier = _identifier_field(context, table)
    if identifier is not None:
        for position, row in enumerate(rows):
            if row.kind is not RowKind.ITEM:
                continue
            segments = code_segments(context.text(table, row, identifier))
            for depth in range(1, len(segments or ())):  # strict prefixes only
                assert segments is not None
                items_by_prefix[segments[:depth]].append(position)
    return _TableIndex(
        rows=rows,
        position={row.row_id: position for position, row in enumerate(rows)},
        span_start=tuple(span_start),
        block_start=tuple(block_start),
        items_by_prefix=dict(items_by_prefix),
    )


def _identifier_field(context: ValidationContext, table: Table) -> str | None:
    for field in context.profile.fields_with_role(FieldRole.IDENTIFIER):
        if table.column_for_field(field.field_id) is not None:
            return field.field_id
    return None


def _section_name(table: Table, section_id: str) -> str:
    if not table.has_row(section_id):
        return "(unknown)"
    section = table.row(section_id)
    return section.classification.code or f"in row {section.source_row_number}"


def _rows_text(rows: Sequence[Row]) -> str:
    if not rows:
        return "(none)"
    first, last = rows[0].source_row_number, rows[-1].source_row_number
    return f"in row {first}" if first == last else f"in rows {first} to {last}"


# ---------------------------------------------------------------------------- readings
def readings(basis: Basis, limit: int = MAX_READINGS) -> ReadingSet:
    """The distinct exact sums ``basis`` admits, each with the first choices that give it."""
    hidden = [term for term in basis.terms if term.hidden]
    visible = [term for term in basis.terms if not term.hidden]
    variants: list[tuple[list[Term], tuple[str, ...]]] = [(list(basis.terms), ())]
    if hidden and visible:
        plural = "s" if len(hidden) != 1 else ""
        variants.append((visible, (f"without the {len(hidden)} hidden row{plural}",)))
    found: dict[Decimal, tuple[str, ...]] = {}
    truncated = False
    for terms, prefix in variants:
        sums, cut = _sums(terms, limit)
        truncated = truncated or cut
        for total, choices in sums.items():
            found.setdefault(total, prefix + choices)
    return ReadingSet(tuple(Reading(total, choices) for total, choices in found.items()), truncated)


def _sums(terms: Sequence[Term], limit: int) -> tuple[dict[Decimal, tuple[str, ...]], bool]:
    """Distinct sums: undecided items in or out, adjustments as written or reversed."""
    optional = [term for term in terms if term.kind is TermKind.OPTIONAL]
    adjustments = [
        term for term in terms if term.kind is TermKind.ADJUSTMENT and not term.amount.is_zero()
    ]
    start = add_all(term.amount for term in terms if term.kind is not TermKind.OPTIONAL)
    states: dict[Decimal, tuple[str, ...]] = {start: ()}
    steps = [
        (term.amount, f"with the undecided item in row {term.row.source_row_number}")
        for term in optional
    ] + [
        (
            multiply(Decimal(-2), term.amount),
            f"with the sign of row {term.row.source_row_number} reversed",
        )
        for term in adjustments
    ]
    for delta, note in steps:
        grown = dict(states)
        for total, choices in states.items():
            grown.setdefault(add_all([total, delta]), (*choices, note))
        if len(grown) > limit:
            everything = add_all([start, *(term.amount for term in optional)])
            fallback: dict[Decimal, tuple[str, ...]] = {start: ()}
            fallback.setdefault(everything, ("with every undecided item",))
            return fallback, True
        states = grown
    return states, False


# ---------------------------------------------------------------------------- judging
def judge(
    reported: Decimal,
    bases: Sequence[Basis],
    *,
    rounding: RoundingSpec,
    tolerance: TolerancePolicy,
    drift_per_term: Decimal | None = None,
) -> Verdict:
    """The outcome for one total row (the table in the doc).

    ``drift_per_term`` is passed only for display-rounded sources (delimited text): a
    difference within ``allowed + drift_per_term × terms`` is then ``DISPLAY_ROUNDING``.
    """
    candidates = tuple(basis for basis in bases if basis.has_members)
    if not candidates:
        return Verdict(Outcome.NO_SCOPE, candidates)
    complete = [basis for basis in candidates if basis.complete]
    if not complete:
        return Verdict(Outcome.INCOMPLETE, candidates)
    best: tuple[Basis, Reading, Reconciliation] | None = None
    tested = 0
    truncated = False
    for basis in complete:
        found = readings(basis)
        truncated = truncated or found.truncated
        for reading in found.readings:
            tested += 1
            result = reconcile(
                reported,
                reading.total,
                rounding=rounding,
                tolerance=tolerance,
                terms=len(basis.terms),
            )
            if result.matched:
                return Verdict(
                    Outcome.CONSISTENT, candidates, basis, reading, result, tested, truncated
                )
            if best is None or abs(result.difference) < abs(best[2].difference):
                best = (basis, reading, result)
    assert best is not None  # a complete basis with members has at least one reading
    basis, reading, result = best
    if drift_per_term is not None and abs(result.difference) <= add_all(
        [result.allowed, multiply(drift_per_term, Decimal(len(basis.terms)))]
    ):
        outcome = Outcome.DISPLAY_ROUNDING
    elif len({candidate.members for candidate in complete}) > 1:
        outcome = Outcome.AMBIGUOUS_STRUCTURE
    elif truncated:
        outcome = Outcome.UNDECIDED
    else:
        outcome = Outcome.VIOLATION
    return Verdict(outcome, candidates, basis, reading, result, tested, truncated)
