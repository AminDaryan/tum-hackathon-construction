"""Reading and matching shared by the BoQ text checks (private module: not discovered).

``domain.boq_clauses`` and ``domain.boq_position_types`` read the texts of item rows directly
from every table that maps the short or the long description, as ``standard_text_keys`` reads
its rows, and not through the item frame: the frame covers only tables that map a unit price,
and a tender exported to Excel without an EP column must be read too. An item's text is its
Kurztext, its Langtext and the text of its continuation rows (long text written in the rows
below an item, ``Row.belongs_to_row_id``), so a bill without a Langtext column is read from
the Kurztext and its continuation lines. The continuation lines of one field are joined into one
text, as the bill's reader reads them, so a clause wrapped onto the next line is still one
sentence; a match is located in the line it starts in. A continuation row whose own item type
names a note (GAEB "Hinweis", "Ausführungsbeschreibung") stands on its own: normalization may
attach it to the item above, but it is not part of that item's text and is not read.

Patterns are detector parameters (the ``boq`` profile may override them) and meet document
text only through :mod:`app.core.patterns`. They are applied one sentence at a time
(:mod:`app.validation.support.sentences`); a sentence longer than ``MAX_MATCH_CHARS`` is
examined in windows of that size that overlap by half of it, each cut at whitespace
(``windows`` of ``deterministic._reference_support``), so no single search looks at more than
``MAX_MATCH_CHARS`` characters and a clause at the end of a long Langtext is still found. A
match that touches an anonymisation token (:mod:`app.validation.support.tokens`) is skipped.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from app.core import patterns
from app.models.dataset import CellRef, Row, RowKind, Table
from app.profiles.units import UnitLookup, unit_key
from app.validation.contracts.context import ValidationContext
from app.validation.deterministic._reference_support import Span, clip, find_spans, windows
from app.validation.domain.boq._bill_text import TEXT_ROW_KINDS
from app.validation.support.sentences import Sentence, split_sentences
from app.validation.support.tokens import token_spans

QUOTE_CHARS = 160  # a quoted clause is clipped to this many characters
# Long sentences are searched in windows that overlap by half a window, so a clause up to that
# long that one window cuts is whole in the next.
SENTENCE_WINDOW_OVERLAP = patterns.MAX_MATCH_CHARS // 2

# Defaults shared by the position type and bid price checks (plan 5a, B2 brief D and E).
HOURLY_ITEM_TYPE_PATTERN = r"\bstundenlohnarbeiten\b"
# Words that name hourly labour: the brief's list, plus operators and site staff (a rate "mit
# Bedienung" pays a wage too). An hour unit alone is not enough: some bills write "Std" for
# piece x day.
LABOUR_PATTERN = (
    r"\b(?:bau)?facharbeiter\w*|\bbauwerker\w*|\b(?:bau|hilfs)?helfer\w*"
    r"|\b(?:bau|hilfs)?arbeiter\w*|\b(?:ober)?monteur\w*|\bvorarbeiter\w*"
    r"|\bpolier(?:e|s|in|innen)?\b|\blohn\w*|\barbeitsstunden?\b|\bstundenlohn\w*"
    r"|\bbedienung\w*|\bbediener\w*|\bfahrer\b|\bmaschinenführer\w*"
    r"|\bingenieur\w*|\b(?:projekt|bau)leiter\w*"
)
HOUR_UNIT_IDS = ("h",)
# Item types of notes that stand on their own (GAEB Remark and PerfDescr). An "Unterbeschreibung"
# (sub-description) is part of the item it follows and is read with it.
NOTE_ITEM_TYPE_PATTERN = r"\bhinweis\b|\bausführungsbeschreibung\b|\bvorbemerkung\b"


@dataclass(frozen=True, slots=True)
class TextCell:
    """A text an item holds: a cell of the item row, or the continuation lines of one field
    joined by spaces (``lines`` holds the offset in ``text`` and the row of each line)."""

    table: Table
    row: Row
    field_id: str
    text: str
    lines: tuple[tuple[int, Row], ...] = ()

    def row_at(self, offset: int) -> Row:
        """The row that holds the character at ``offset``."""
        row = self.row
        for start, line_row in self.lines:
            if start > offset:
                break
            row = line_row
        return row


@dataclass(frozen=True, slots=True)
class ItemText:
    """An item row with its texts in reading order."""

    table: Table
    row: Row
    code: str | None  # the item code as written
    cells: tuple[TextCell, ...]
    unit_text: str | None
    unit: UnitLookup | None
    item_type: str | None

    @property
    def label(self) -> str:
        """The position number, or the row when the item has none."""
        return self.code or f"row {self.row.source_row_number}"


@dataclass(frozen=True, slots=True)
class Phrase:
    """A match of a pattern in one sentence of a text cell (offsets into ``cell.text``);
    ``group`` is the span of the pattern's first group, when it has one and it matched."""

    cell: TextCell
    sentence: Sentence
    start: int
    end: int
    group: tuple[int, int] | None = None

    @property
    def matched(self) -> str:
        return self.cell.text[self.start : self.end]

    @property
    def row(self) -> Row:
        """The row the match starts in."""
        return self.cell.row_at(self.start)

    @property
    def captured(self) -> str | None:
        return None if self.group is None else self.cell.text[self.group[0] : self.group[1]]


@dataclass(slots=True)
class MatchStats:
    """What the matching examined, for the coverage of a run."""

    sentences: int = 0
    long_sentences: int = 0  # sentences examined in several windows
    token_matches: int = 0  # matches skipped because they touch an anonymisation token


# ---------------------------------------------------------------------------- reading
def text_tables(context: ValidationContext, field_ids: Sequence[str]) -> list[Table]:
    """Tables that map at least one of ``field_ids``."""
    return [t for t in context.tables() if any(context.has_fields(t, f) for f in field_ids)]


def item_texts(
    context: ValidationContext,
    table: Table,
    text_fields: Sequence[str],
    *,
    code_field: str,
    item_type_field: str | None,
    note_item_type_pattern: str | None = None,
) -> Iterator[ItemText]:
    """The item rows of ``table`` with their texts (see the module docstring). Items without
    any text are yielded too (the position type checks read their item type and unit). A
    continuation row whose item type matches ``note_item_type_pattern`` is not read."""
    mapped = [f for f in dict.fromkeys(text_fields) if context.has_fields(table, f)]
    unit_field = context.unit_field_id()
    typed = item_type_field is not None and context.has_fields(table, item_type_field)
    items: list[tuple[Row, list[TextCell]]] = []
    lines: dict[str, dict[str, list[tuple[Row, str]]]] = {}  # item row id -> field -> lines
    for row in context.rows(table, TEXT_ROW_KINDS):
        texts = [(f, text) for f in mapped if (text := context.text(table, row, f))]
        if row.kind is RowKind.ITEM:
            items.append((row, [TextCell(table, row, f, text) for f, text in texts]))
            lines[row.row_id] = {}
        elif row.belongs_to_row_id is not None and row.belongs_to_row_id in lines:
            if typed and note_item_type_pattern and item_type_field:
                own_type = context.text(table, row, item_type_field)
                if own_type and search_text(note_item_type_pattern, own_type):
                    continue
            for field_id, text in texts:
                lines[row.belongs_to_row_id].setdefault(field_id, []).append((row, text))
    for row, cells in items:
        for field_id, field_lines in lines[row.row_id].items():
            cells.append(_joined(table, field_id, field_lines))
        yield ItemText(
            table=table,
            row=row,
            code=context.text(table, row, code_field),
            cells=tuple(cells),
            unit_text=context.text(table, row, unit_field) if unit_field else None,
            unit=context.unit(table, row),
            item_type=context.text(table, row, item_type_field)
            if typed and item_type_field
            else None,
        )


def _joined(table: Table, field_id: str, lines: Sequence[tuple[Row, str]]) -> TextCell:
    """The continuation lines of one field as one text."""
    offsets: list[tuple[int, Row]] = []
    parts: list[str] = []
    position = 0
    for row, text in lines:
        offsets.append((position, row))
        parts.append(text)
        position += len(text) + 1
    return TextCell(table, lines[0][0], field_id, " ".join(parts), tuple(offsets))


def unit_keys(words: Sequence[str]) -> frozenset[str]:
    """Unit words compared as the unit catalogue compares units ("Psch." equals "psch")."""
    return frozenset(unit_key(word) for word in words)


def is_lump_sum(item: ItemText, unit_words: frozenset[str], item_type_pattern: str) -> bool:
    """A lump sum: its unit is of the lump sum dimension, its unit text is one of
    ``unit_words`` (see :func:`unit_keys`), or its item type matches ``item_type_pattern``."""
    if item.unit is not None and item.unit.unit.dimension == "lump_sum":
        return True
    if item.unit_text and unit_key(item.unit_text) in unit_words:
        return True
    return item.item_type is not None and search_text(item_type_pattern, item.item_type)


def is_hourly_labour(
    item_type: str | None,
    unit_id: str | None,
    texts: Sequence[str],
    *,
    hour_unit_ids: Sequence[str],
    item_type_pattern: str,
    labour_pattern: str,
) -> bool:
    """Hourly work: the item type says so (GAEB "Stundenlohnarbeiten"), or the unit is an hour
    and the text names labour."""
    if item_type and search_text(item_type_pattern, item_type):
        return True
    if unit_id not in hour_unit_ids:
        return False
    return any(search_text(labour_pattern, text) for text in texts)


# ---------------------------------------------------------------------------- matching
def sentences_of(
    item: ItemText, stats: MatchStats | None = None
) -> Iterator[tuple[TextCell, Sentence]]:
    """Every sentence of every text of ``item``, in reading order."""
    for cell in item.cells:
        for sentence in split_sentences(cell.text):
            if stats is not None:
                stats.sentences += 1
                if len(sentence.text) > patterns.MAX_MATCH_CHARS:
                    stats.long_sentences += 1
            yield cell, sentence


def find_in_sentence(
    pattern: str, cell: TextCell, sentence: Sentence, stats: MatchStats | None = None
) -> list[Phrase]:
    """The matches of ``pattern`` in one sentence of ``cell``, leftmost first, without
    matches that touch an anonymisation token."""
    return [
        Phrase(cell=cell, sentence=sentence, start=start, end=end, group=group)
        for start, end, group in _sentence_spans(pattern, sentence, stats)
    ]


def find_in_item(pattern: str, item: ItemText, stats: MatchStats | None = None) -> list[Phrase]:
    """The matches of ``pattern`` in every sentence of ``item``, in reading order."""
    return [
        phrase
        for cell, sentence in sentences_of(item, stats)
        for phrase in find_in_sentence(pattern, cell, sentence, stats)
    ]


def search_text(pattern: str, text: str) -> bool:
    """Whether ``pattern`` matches in ``text`` (sentence by sentence and in windows, as
    :func:`find_in_sentence` searches), outside anonymisation tokens."""
    return any(_sentence_spans(pattern, sentence, None) for sentence in split_sentences(text))


def _sentence_spans(pattern: str, sentence: Sentence, stats: MatchStats | None) -> list[Span]:
    """Matches in one sentence, as offsets into the sentence's text cell. A match found in
    two overlapping windows is kept once."""
    tokens = token_spans(sentence.text)
    found: dict[tuple[int, int], Span] = {}
    for offset, window in windows(sentence.text, SENTENCE_WINDOW_OVERLAP):
        for start, end, group in find_spans(pattern, window):
            left, right = offset + start, offset + end
            if any(a < right and left < b for a, b in tokens):
                if stats is not None:
                    stats.token_matches += 1
                continue
            base = sentence.start + offset
            span = (base + start, base + end)
            if span not in found:
                moved = None if group is None else (base + group[0], base + group[1])
                found[span] = (span[0], span[1], moved)
    return [found[span] for span in sorted(found)]


# ---------------------------------------------------------------------------- reporting
def excerpt(phrase: Phrase, focus: tuple[int, int] | None = None, limit: int = QUOTE_CHARS) -> str:
    """The sentence of ``phrase`` for a quote, whitespace collapsed: whole when it fits in
    ``limit`` characters, else the part from shortly before ``focus`` (the match by default),
    cut at whitespace and marked with an ellipsis where it was cut."""
    sentence = phrase.sentence
    whole = " ".join(sentence.text.split())
    if len(whole) <= limit:
        return whole
    text = phrase.cell.text
    first, last = focus or (phrase.start, phrase.end)
    lead = max((limit - (last - first)) // 3, 0)
    start = max(sentence.start, first - lead)
    while start > sentence.start and not text[start - 1].isspace() and first - start <= lead + 30:
        start -= 1
    if start > sentence.start and not text[start - 1].isspace():
        start = first  # inside a very long word: start at the match instead
    part = " ".join(text[start : sentence.end].split())
    return clip(("…" if start > sentence.start else "") + part, limit)


def positions_list(labels: Sequence[str]) -> str:
    """``"02.03.0013"``, ``"02.03.0013 and 02.05.0031"``, ``"a, b and c"``."""
    unique = list(dict.fromkeys(labels))
    if len(unique) <= 1:
        return "".join(unique)
    return f"{', '.join(unique[:-1])} and {unique[-1]}"


def cell_refs(context: ValidationContext, phrases: Sequence[Phrase], cap: int) -> list[CellRef]:
    """The cells the phrases were found in, each once and in order, at most ``cap``."""
    seen: dict[tuple[str, str], CellRef] = {}
    for phrase in phrases:
        if len(seen) >= cap:
            break
        row, field_id = phrase.row, phrase.cell.field_id
        if (row.row_id, field_id) not in seen:
            seen[row.row_id, field_id] = context.cell_ref(phrase.cell.table, row, field_id)
    return list(seen.values())
