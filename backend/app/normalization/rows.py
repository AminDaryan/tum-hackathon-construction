"""Row kinds, the section hierarchy, subtotal scopes, totals membership and continuation lines.

Row kinds follow the decision table in ``RowClassificationRules`` (``app/models/profile.py``).
The profile's ``item_value_fields`` name the value columns: fields with role ``quantity`` are
quantities, the first of several ``monetary`` ones is the unit price (rate) and the last one
the line total. Amount cells are the cells of every mapped monetary field (any numeric cell
outside identifier, label, unit and category columns when no monetary field is mapped). When
none of the item value fields is mapped (a generic profile, or a file without value columns),
every non-blank row that no pattern claims is an item (rule ``default.item``).

Sections: a section nests under the innermost open section whose code is a strict prefix of
its own code (level = parent level + 1); otherwise its level is the pattern's level, else the
depth of its code, else 1. Opening a section closes open sections at its level or deeper. A
subtotal closes the innermost open section with the same code (identifier cell, else the
pattern's ``code`` group); without a code the innermost open section; with no matching open
section the scope stays unknown (``closes_section_id = None``). Grand and gross totals close
every section. Reviewer decisions override kinds, levels, closed sections and totals
membership; rows a reviewer excluded keep their kind but take no part in the structure. A kind
or membership decided that way is attributed to rule ``user`` when the reviewer made it and to
``declared`` when the file itself declared it (a GAEB bill).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core import patterns
from app.core.codes import code_segments, is_strict_prefix
from app.models.dataset import SCOPE_BOUNDARY_KINDS, Cell, Row, RowClassification, RowKind
from app.models.profile import DomainProfile, FieldRole, LabelMatch, TotalsTextSource
from app.models.schema import TableDecisions
from app.models.values import DataType, ParseStatus, TextValue, ValueMarker

MAX_MATCHED_TEXT = 120
MAX_SECTION_LEVEL = 9
_TOTAL_LIKE = frozenset(
    {
        RowKind.CARRY_FORWARD,
        RowKind.GROSS_TOTAL,
        RowKind.TAX,
        RowKind.GRAND_TOTAL,
        RowKind.ADJUSTMENT,
        RowKind.SUBTOTAL,
    }
)
_STRUCTURE_ROLES = frozenset(
    {FieldRole.IDENTIFIER, FieldRole.LABEL, FieldRole.UNIT, FieldRole.CATEGORY}
)
# Rules of TEXT rows that may still become a section by their code (decision table rule 6).
_PLAIN_TEXT = "text"
_UNCLASSIFIED = "text.unclassified_amount"


@dataclass(slots=True)
class RowInput:
    """A data row before classification."""

    row_id: str
    position: int
    source_row: int
    cells: dict[str, Cell]  # column id -> cell
    hidden: bool = False
    outline_level: int | None = None
    excluded: bool = False
    repeated_header: bool = False


@dataclass(slots=True)
class RowWarnings:
    """Source row numbers behind the row-level extraction warnings."""

    unclassified_amount_rows: list[int] = field(default_factory=list)
    section_amount_rows: list[int] = field(default_factory=list)
    hidden_rows: list[int] = field(default_factory=list)


@dataclass(slots=True)
class _State:
    kind: RowKind
    rule: str
    match: LabelMatch | None = None
    code: str | None = None
    level: int | None = None  # pattern level (sections)


_OpenSection = tuple[str, int, tuple[str, ...] | None]  # (row id, level, code segments)


class RowClassifier:
    """Classifies the data rows of one table."""

    def __init__(
        self,
        profile: DomainProfile,
        field_columns: dict[str, str],  # field id -> column id (mapped fields only)
        column_order: Sequence[str],  # column ids in source order
        decisions: TableDecisions | None,
        reviewer: TableDecisions | None,  # the reviewer's part of ``decisions``
    ) -> None:
        rules = profile.row_classification
        self._rules = rules
        self._columns = field_columns
        self._order = list(column_order)
        self._decisions = decisions
        self._reviewer = reviewer
        roles = {f.field_id: f.role for f in profile.fields}
        values = list(rules.item_value_fields)
        money = [f for f in values if roles.get(f) is FieldRole.MONETARY]
        self._quantities = [f for f in values if roles.get(f) is FieldRole.QUANTITY]
        self._rate = money[0] if len(money) > 1 else None
        self._total = money[-1] if money else None
        self._values_mapped = any(f in field_columns for f in values)
        self._amounts = [
            f.field_id
            for f in profile.fields
            if f.role is FieldRole.MONETARY and f.field_id in field_columns
        ]
        self._unit = next(
            (
                f.field_id
                for f in profile.fields
                if f.role is FieldRole.UNIT and f.field_id in field_columns
            ),
            None,
        )
        self._label_fields = [f for f in rules.label_fields if f in field_columns]
        self._category = [
            f.field_id
            for f in profile.fields
            if f.role is FieldRole.CATEGORY and f.field_id in field_columns
        ]
        code_field = rules.section_code_field
        self._code_column = field_columns.get(code_field) if code_field else None
        self._structure_columns = {
            field_columns[f.field_id]
            for f in profile.fields
            if f.role in _STRUCTURE_ROLES and f.field_id in field_columns
        }

    # ------------------------------------------------------------------ public
    def classify(self, inputs: list[RowInput]) -> tuple[list[Row], RowWarnings]:
        warnings = RowWarnings()
        states = self._kinds(inputs, warnings)
        self._sections_from_codes(inputs, states, warnings)
        belongs = self._continuations(inputs, states)
        return self._structure(inputs, states, belongs), warnings

    # ------------------------------------------------------------------ kinds
    def _kinds(self, inputs: list[RowInput], warnings: RowWarnings) -> list[_State]:
        states: list[_State] = []
        in_block = False
        user_kinds = self._decisions.row_kinds if self._decisions else {}
        for row in inputs:
            if row.hidden:
                warnings.hidden_rows.append(row.source_row)
            user_kind = user_kinds.get(row.source_row)
            if user_kind is not None:
                rule = self._decided_by(row.source_row, "row_kinds")
                state = _State(user_kind, rule, code=self._code(row, None))
            else:
                state, in_block = self._kind(row, in_block, warnings)
            states.append(state)
        return states

    def _kind(self, row: RowInput, in_block: bool, warnings: RowWarnings) -> tuple[_State, bool]:
        if all(cell.is_empty for cell in row.cells.values()):
            return _State(RowKind.BLANK, "blank"), in_block
        if row.repeated_header:
            return _State(RowKind.TEXT, "repeated_header"), in_block
        quantity = any(self._filled(row, f) for f in self._quantities)
        rate = self._rate is not None and self._filled(row, self._rate)
        total = self._total is not None and self._filled(row, self._total)
        amount = self._has_amount(row)
        match = self._rules.match_label(self._label(row))
        if (
            match is not None
            and match.kind in _TOTAL_LIKE
            and not quantity
            and not (rate and total)
        ):
            if not amount:
                return _State(RowKind.TEXT, "text.total_without_amount", match), in_block
            still_in_block = in_block and match.kind not in SCOPE_BOUNDARY_KINDS
            return _State(match.kind, match.rule, match, self._code(row, match)), still_in_block
        if match is not None and match.starts_summary_block and not quantity and not rate:
            return _State(RowKind.TEXT, match.rule, match), True
        if in_block and amount and not quantity and not rate:
            return _State(RowKind.SUMMARY_LINE, "summary.line", match), True
        section = match if match is not None and match.kind is RowKind.SECTION else None
        if not self._values_mapped:
            if section is not None:
                return self._section(row, section), in_block
            return _State(RowKind.ITEM, "default.item", match), in_block
        if quantity or rate:
            return _State(RowKind.ITEM, "values.item", match), in_block
        if total and self._unit is not None and self._filled(row, self._unit):
            return _State(RowKind.ITEM, "values.lump_sum", match), in_block
        if section is not None:
            if amount:
                warnings.section_amount_rows.append(row.source_row)
            return self._section(row, section), in_block
        if self._numeric_outside_structure(row):
            warnings.unclassified_amount_rows.append(row.source_row)
            return _State(RowKind.TEXT, _UNCLASSIFIED, match), in_block
        return _State(RowKind.TEXT, _PLAIN_TEXT, match), in_block

    def _section(self, row: RowInput, match: LabelMatch) -> _State:
        return _State(RowKind.SECTION, match.rule, match, self._code(row, match), match.level)

    def _sections_from_codes(
        self, inputs: list[RowInput], states: list[_State], warnings: RowWarnings
    ) -> None:
        """Decision table rule 6, by code: a text row whose code is a strict prefix of the
        next item's code opens a section (rule ``code.section``)."""
        if self._code_column is None:
            return
        pattern = self._rules.section_code_pattern
        next_item: tuple[str, ...] | None = None
        for index in range(len(inputs) - 1, -1, -1):
            row, state = inputs[index], states[index]
            if row.excluded:
                continue
            if state.kind is RowKind.ITEM:
                next_item = code_segments(self._text(row, self._code_column))
                continue
            if state.kind is not RowKind.TEXT or state.rule not in (_PLAIN_TEXT, _UNCLASSIFIED):
                continue
            code = self._text(row, self._code_column)
            if not is_strict_prefix(code_segments(code), next_item):
                continue
            if pattern and (code is None or not patterns.fullmatch(pattern, code)):
                continue
            if state.rule == _UNCLASSIFIED:
                warnings.unclassified_amount_rows.remove(row.source_row)
                warnings.section_amount_rows.append(row.source_row)
            states[index] = _State(RowKind.SECTION, "code.section", state.match, code)
        warnings.section_amount_rows.sort()

    def _continuations(self, inputs: list[RowInput], states: list[_State]) -> list[str | None]:
        """Plain text rows directly below an item (or below its continuation lines), without a
        code and without numbers, continue that item."""
        belongs: list[str | None] = [None] * len(inputs)
        current: str | None = None
        for index, (row, state) in enumerate(zip(inputs, states, strict=True)):
            if row.excluded:
                continue
            if state.kind is RowKind.ITEM:
                current = row.row_id
                continue
            if (
                current is not None
                and state.kind is RowKind.TEXT
                and state.rule == _PLAIN_TEXT
                and (self._code_column is None or self._text(row, self._code_column) is None)
            ):
                belongs[index] = current
                continue
            current = None
        return belongs

    # ------------------------------------------------------------------ structure
    def _structure(
        self, inputs: list[RowInput], states: list[_State], belongs: list[str | None]
    ) -> list[Row]:
        decisions = self._decisions
        levels = decisions.section_levels if decisions else {}
        closes_user = decisions.closes_section if decisions else {}
        counts_user = decisions.counts_toward_totals if decisions else {}
        sections_by_source = {
            row.source_row: row.row_id
            for row, state in zip(inputs, states, strict=True)
            if state.kind is RowKind.SECTION and not row.excluded
        }
        continuation_texts: dict[str, list[str]] = {}
        for row, owner in zip(inputs, belongs, strict=True):
            if owner is not None:
                continuation_texts.setdefault(owner, []).extend(self._texts(row))
        section_rules: dict[str, tuple[bool | None, str]] = {}
        open_sections: list[_OpenSection] = []
        rows: list[Row] = []
        for row, state, owner in zip(inputs, states, belongs, strict=True):
            path = [section_id for section_id, _, _ in open_sections]
            closes: str | None = None
            level: int | None = None
            if row.excluded:
                pass
            elif state.kind is RowKind.SECTION:
                segments = code_segments(state.code)
                level = levels.get(row.source_row) or self._level(state, segments, open_sections)
                while open_sections and open_sections[-1][1] >= level:
                    open_sections.pop()
                path = [section_id for section_id, _, _ in open_sections]
                open_sections.append((row.row_id, level, segments))
                rule = self._rules.match_totals(
                    {"label": self._labels(row), "category": self._categories(row)}
                )
                if rule is not None:
                    section_rules[row.row_id] = (rule.counts_toward_totals, rule.rule_id)
            elif state.kind is RowKind.SUBTOTAL:
                if row.source_row in closes_user:
                    target = closes_user[row.source_row]
                    closes = sections_by_source.get(target) if target is not None else None
                else:
                    closes = self._closed_section(state.code, open_sections)
                ids = [section_id for section_id, _, _ in open_sections]
                if closes in ids:
                    del open_sections[ids.index(closes) :]
            elif state.kind in (RowKind.GRAND_TOTAL, RowKind.GROSS_TOTAL):
                open_sections.clear()
            counts, totals_rule, above = self._membership(
                row, state, path, section_rules, continuation_texts, counts_user
            )
            match = state.match
            coded = state.kind in (RowKind.SECTION, RowKind.SUBTOTAL)
            rows.append(
                Row(
                    row_id=row.row_id,
                    position=row.position,
                    source_row_number=row.source_row,
                    cells=row.cells,
                    classification=RowClassification(
                        kind=state.kind,
                        rule=state.rule,
                        matched_text=_clip(match.matched_text) if match else None,
                        section_level=level,
                        code=state.code if coded else None,
                        counts_toward_totals=counts,
                        totals_rule=totals_rule,
                        not_counted_above_section_id=above,
                    ),
                    section_path=path,
                    closes_section_id=closes,
                    excluded=row.excluded,
                    source_hidden=row.hidden,
                    outline_level=row.outline_level,
                    belongs_to_row_id=owner,
                )
            )
        return rows

    @staticmethod
    def _level(
        state: _State, segments: tuple[str, ...] | None, open_sections: list[_OpenSection]
    ) -> int:
        for _, level, open_segments in reversed(open_sections):
            if is_strict_prefix(open_segments, segments):
                return min(level + 1, MAX_SECTION_LEVEL)
        if state.level is not None:
            return state.level
        if segments:
            return min(len(segments), MAX_SECTION_LEVEL)
        return 1

    @staticmethod
    def _closed_section(code: str | None, open_sections: list[_OpenSection]) -> str | None:
        if not open_sections:
            return None
        segments = code_segments(code)
        if segments is None:
            return open_sections[-1][0]
        for section_id, _, open_segments in reversed(open_sections):
            if open_segments == segments:
                return section_id
        return None

    def _decided_by(self, source_row: int, decision: str) -> str:
        """``user`` when the reviewer decided this row, ``declared`` when the file did."""
        reviewer = self._reviewer
        decided = reviewer is not None and source_row in getattr(reviewer, decision)
        return "user" if decided else "declared"

    def _membership(
        self,
        row: RowInput,
        state: _State,
        path: list[str],
        section_rules: dict[str, tuple[bool | None, str]],
        continuation_texts: dict[str, list[str]],
        counts_user: dict[int, bool | None],
    ) -> tuple[bool | None, str | None, str | None]:
        """``(counts_toward_totals, totals_rule, not_counted_above_section_id)``."""
        if state.kind is not RowKind.ITEM:
            return True, None, None
        if row.source_row in counts_user:
            decided_by = self._decided_by(row.source_row, "counts_toward_totals")
            return counts_user[row.source_row], decided_by, None
        if self._total is not None and self._marker(row, self._total) is ValueMarker.RATE_ONLY:
            return False, "marker.rate_only", None
        texts: dict[TotalsTextSource, list[str]] = {
            "label": self._labels(row),
            "category": self._categories(row),
            "amount_text": self._amount_texts(row),
            "continuation_text": continuation_texts.get(row.row_id, []),
        }
        rule = self._rules.match_totals(texts)
        if rule is not None:
            return rule.counts_toward_totals, rule.rule_id, None
        for section_id in reversed(path):
            inherited = section_rules.get(section_id)
            if inherited is not None:
                counts, rule_id = inherited
                return counts, rule_id, (None if counts is True else section_id)
        return True, None, None

    # ------------------------------------------------------------------ cell access
    def _cell(self, row: RowInput, field_id: str) -> Cell | None:
        column = self._columns.get(field_id)
        return None if column is None else row.cells.get(column)

    def _filled(self, row: RowInput, field_id: str) -> bool:
        cell = self._cell(row, field_id)
        return cell is not None and not cell.is_empty

    def _marker(self, row: RowInput, field_id: str) -> ValueMarker | None:
        cell = self._cell(row, field_id)
        return cell.marker if cell is not None else None

    def _has_amount(self, row: RowInput) -> bool:
        if self._amounts:
            return any(self._filled(row, f) for f in self._amounts)
        return self._numeric_outside_structure(row)

    def _numeric_outside_structure(self, row: RowInput) -> bool:
        return any(
            column not in self._structure_columns
            and (cell.data_type is DataType.NUMBER or cell.parse_status is ParseStatus.AMBIGUOUS)
            for column, cell in row.cells.items()
        )

    def _label(self, row: RowInput) -> str | None:
        for field_id in self._label_fields:
            text = self._text(row, self._columns[field_id])
            if text:
                return _match_text(text)
        if self._rules.fallback_to_first_text_cell:
            for column in self._order:
                text = _plain_text(row.cells.get(column))
                if text:
                    return _match_text(text)
        return None

    def _labels(self, row: RowInput) -> list[str]:
        texts = [
            _match_text(t) for f in self._label_fields if (t := self._text(row, self._columns[f]))
        ]
        if texts:
            return texts
        label = self._label(row)
        return [label] if label else []

    def _texts(self, row: RowInput) -> list[str]:
        """Every plain text of a row (continuation lines)."""
        return [_match_text(t) for c in self._order if (t := _plain_text(row.cells.get(c)))]

    def _categories(self, row: RowInput) -> list[str]:
        return [_match_text(t) for f in self._category if (t := self._text(row, self._columns[f]))]

    def _amount_texts(self, row: RowInput) -> list[str]:
        texts = []
        for field_id in self._amounts:
            cell = self._cell(row, field_id)
            if cell is not None and cell.data_type is DataType.TEXT and cell.raw_value:
                texts.append(_match_text(cell.raw_value))
        return texts

    def _code(self, row: RowInput, match: LabelMatch | None) -> str | None:
        if self._code_column is not None:
            text = self._text(row, self._code_column)
            if text and code_segments(text) is not None:
                return text
        return match.code if match is not None else None

    @staticmethod
    def _text(row: RowInput, column: str) -> str | None:
        cell = row.cells.get(column)
        if cell is None or cell.is_empty:
            return None
        if isinstance(cell.normalized_value, TextValue):
            return cell.normalized_value.value or None
        raw = (cell.raw_value or "").strip()
        return raw or None


def _plain_text(cell: Cell | None) -> str | None:
    if (
        cell is None
        or cell.data_type is not DataType.TEXT
        or cell.parse_status is not ParseStatus.NOT_APPLICABLE
        or not isinstance(cell.normalized_value, TextValue)
    ):
        return None
    return cell.normalized_value.value or None


def _match_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text[: patterns.MAX_MATCH_CHARS * 2]).split())


def _clip(text: str) -> str:
    return text if len(text) <= MAX_MATCHED_TEXT else text[: MAX_MATCHED_TEXT - 1] + "…"
