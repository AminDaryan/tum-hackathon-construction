"""Numbering hierarchy: item and section codes that contradict the document's own numbering.

Codes are compared by their segments (:func:`app.core.codes.code_segments`, so ``01.02.0030``
and ``1.2.30`` are the same code). Every table that maps the code field is read in source order:

* ``item_outside_section`` (medium): an item code has more segments than the code of the
  item's innermost section but does not start with them (``01.03.0010`` in section ``01.02``).
* ``section_outside_parent`` (medium): the same for a section and the section it is in
  (``02.01`` inside section ``01``, for example when the heading of section ``02`` is missing).
* ``code_order`` (low): inside one section, an item code made only of numbers is lower than
  the numeric code of the item before it (``01.02.0030`` after ``01.02.0040``). The section
  scope is the one ``deterministic.field_constraints`` uses for ``unique_scope: section``: the
  innermost section, and a carry-forward row (a page break) starts a new scope. An equal code
  is not lower: a repeated code is a uniqueness question (``deterministic.field_constraints``).

All three are ``confirmed_rule_violation``: the document contradicts its own numbering. Finding
category (plan section 5a): error, for all three rules (an OZ outside its Titel, a Titel under
the wrong parent and an OZ out of order are listed under Error there).

Not compared, and counted in the coverage:

* codes with letters (``A.1``, ``2a``): they take part in the two prefix rules only;
* two codes of different numbering schemes: where one has a number and the other letters at
  the same level (a section ``A`` with items ``1.1``; an anonymised code such as a token), the
  prefix rules do not compare them;
* items and sections without a code, and whatever is inside a section without a code (a
  section without a code is skipped: its items and child sections are not compared);
* items outside every section, and rows that are neither items nor sections (adjustments,
  text, totals);
* an item outside its section does not enter the order of that section, so one wrong code is
  one finding: the item after it is compared with the item before it;
* a code read from a cell typed as a number with decimals (a spreadsheet keeps ``1.10`` as
  ``1.1``, so its last segment cannot be trusted): such an item does not enter the order, and
  such a section is not used as the prefix of its items and child sections. A code typed so
  is still compared with a section code of one segment, because its whole-number part is
  exact.

In a GAEB file the codes are built from the structure, so only the order rule can fire there.
More than ``max_row_issues`` findings of one rule in one table become one grouped finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field

from app.models.dataset import CellRef, Row, RowKind, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    JsonScalar,
    Severity,
    ValidationIssue,
)
from app.models.values import NumberValue
from app.validation.contracts.conditions import Coverage
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._reference_support import clip, describe_rows
from app.validation.deterministic._support import (
    FieldId,
    code_segments,
    field_label,
    row_guard,
    row_label,
)

RULE_ITEM = "item_outside_section"
RULE_SECTION = "section_outside_parent"
RULE_ORDER = "code_order"
RULES = (RULE_ITEM, RULE_SECTION, RULE_ORDER)
CATEGORY_NUMBERING = "numbering"

ITEMS_WITHOUT_CODE = "items_without_code"
ITEMS_WITHOUT_CODED_SECTION = "items_without_coded_section"
SECTIONS_WITHOUT_CODE = "sections_without_code"
SECTIONS_WITHOUT_CODED_PARENT = "sections_without_coded_parent"
LETTERS_NOT_ORDERED = "codes_with_letters_not_ordered"
TYPED_NOT_ORDERED = "codes_typed_as_decimal_numbers_not_ordered"
TYPED_PREFIX_NOT_COMPARED = "rows_in_sections_typed_as_decimal_numbers"
OTHER_SCHEME_NOT_COMPARED = "codes_of_another_scheme_not_compared"
FOUND = {
    RULE_ITEM: "items_outside_section",
    RULE_SECTION: "sections_outside_parent",
    RULE_ORDER: "codes_out_of_order",
}

_ROWS_LISTED = 20
_PAIRS_SHOWN = 8
_CODE_CHARS = 60

Segments = tuple[str, ...]


class HierarchyConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field that holds the item codes.")
    max_row_issues: int = plannable(
        20,
        ge=1,
        le=1000,
        description="Findings of one rule and table reported one by one; more are grouped.",
    )
    severity_item_outside_section: Severity = Field(
        default=Severity.MEDIUM, description="Severity of an item code outside its section."
    )
    severity_section_outside_parent: Severity = Field(
        default=Severity.MEDIUM,
        description="Severity of a section code outside the section it is in.",
    )
    severity_code_order: Severity = Field(
        default=Severity.LOW,
        description="Severity of an item code lower than the code of the item before it.",
    )

    def severity(self, rule: str) -> Severity:
        if rule == RULE_ITEM:
            return self.severity_item_outside_section
        if rule == RULE_SECTION:
            return self.severity_section_outside_parent
        return self.severity_code_order


@dataclass(frozen=True, slots=True)
class _Code:
    """A code as written, its segments, the cell it was read from (if any), and whether its
    last segment can be trusted (not for a cell typed as a number with decimals)."""

    text: str
    segments: Segments
    cell: CellRef | None
    exact: bool


@dataclass(frozen=True, slots=True)
class _Hit:
    """``row`` (code ``code``) contradicts ``other_row`` (code ``other``): its section, the
    section it is in, or the item before it."""

    rule: str
    row: Row
    code: _Code
    other_row: Row
    other: _Code


class HierarchyDetector(Detector[HierarchyConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.hierarchy",
        name="Numbering hierarchy",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Finds codes that contradict the document's own numbering: an item code that does "
            "not start with the code of its section, a section code that does not start with "
            "the code of the section it is in, and an item code lower than the one before it."
        ),
        required_fields=("item_code",),
        applicability="Tables that map the item code and have at least one section with a code.",
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(CATEGORY_NUMBERING,),
        limitations=(
            "Only the numbering is compared: whether an item belongs in its section by its "
            "content is not checked.",
            "Codes with letters are compared by their prefix only, not by their order; a code "
            "with numbers where its section has letters (or the reverse) is not compared.",
            "A code typed as a number with decimals may have lost trailing zeros (1.10 reads "
            "1.1): it is not ordered, and such a section is not used as a prefix.",
            "Sections without a code, and everything inside them, are not compared.",
        ),
        cost="low",
    )
    config_model = HierarchyConfig

    def required_fields(self, config: HierarchyConfig) -> tuple[str, ...]:
        return (config.code_field,)

    def applicability(self, context: ValidationContext, config: HierarchyConfig) -> Applicability:
        mapped = [t for t in context.tables() if t.column_for_field(config.code_field)]
        if not mapped:
            label = field_label(context, config.code_field)
            return Applicability.no(f"No table maps {label}.")
        coded = [t.name for t in mapped if _has_coded_section(context, t)]
        if not coded:
            return Applicability.no("No table has a section with a code.")
        return Applicability.yes(f"Compares item and section codes in: {', '.join(coded)}.")

    def validate(self, context: ValidationContext, config: HierarchyConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            if table.column_for_field(config.code_field) is None:
                label = field_label(context, config.code_field)
                result.notes.append(f"Table '{table.name}': {label} is not mapped; not checked.")
                continue
            hits = _Scan(context, config, table, result).run()
            for rule in RULES:
                found = [hit for hit in hits if hit.rule == rule]
                if not found:
                    continue
                result.count(FOUND[rule], len(found))
                if len(found) <= config.max_row_issues:
                    for hit in found:
                        context.checkpoint()
                        result.add(self._issue(context, config, table, hit))
                else:
                    result.add(self._group(context, config, table, rule, found))
        return result

    # ------------------------------------------------------------------ findings
    def _issue(
        self, context: ValidationContext, config: HierarchyConfig, table: Table, hit: _Hit
    ) -> ValidationIssue:
        code, other = _shown(hit.code), _shown(hit.other)
        here, there = row_label(table, hit.row), row_label(table, hit.other_row)
        if hit.rule == RULE_ITEM:
            title = f"Item code {code} is outside section {other}"
            explanation = (
                f"{here} has the item code {code}, but its section ({there}) has the code "
                f"{other}. The item code has more levels than the section code and does not "
                "start with it, so the document's own numbering puts the item in another "
                "section."
            )
            expected = f"a code that starts with {other}"
        elif hit.rule == RULE_SECTION:
            title = f"Section code {code} is outside section {other}"
            explanation = (
                f"{here} opens section {code} inside section {other} ({there}). The section "
                "code has more levels than the code of the section it is in and does not start "
                "with it, so the document's own numbering puts it in another section (or the "
                "heading of its own parent section is missing)."
            )
            expected = f"a code that starts with {other}"
        else:
            section = _section_text(table, hit.row)
            title = f"Item code {code} is lower than the code before it ({other})"
            explanation = (
                f"{here} has the item code {code}, which is lower than the code {other} of the "
                f"item before it ({there}){section}. The items of a section are numbered in "
                "ascending order, so an item may have been moved or its code mistyped."
            )
            expected = f"a code higher than {other}"
        cells = [hit.code.cell] if hit.code.cell is not None else []
        inputs = [hit.other.cell] if hit.other.cell is not None else []
        return context.issues.create(
            self.spec,
            rule_id=hit.rule,
            category=CATEGORY_NUMBERING,
            severity=config.severity(hit.rule),
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(title, 200),
            explanation=clip(explanation, 2000),
            table=table,
            row=hit.row,
            cells=cells,
            inputs=inputs,
            observed_value=hit.code.text,
            expected_value=clip(expected, 200),
            evidence=[
                _rule_evidence(hit.rule),
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Codes compared",
                    detail=clip(_pair(table, hit), 1000),
                    cells=[*cells, *inputs],
                    data=_pair_data(hit),
                ),
            ],
            suggested_action=_ACTIONS[hit.rule],
        )

    def _group(
        self,
        context: ValidationContext,
        config: HierarchyConfig,
        table: Table,
        rule: str,
        hits: list[_Hit],
    ) -> ValidationIssue:
        cap = config.max_row_issues
        cells = [hit.code.cell for hit in hits if hit.code.cell is not None][:cap]
        where = describe_rows([(table, hit.row) for hit in hits], limit=_ROWS_LISTED)
        count = len(hits)
        if rule == RULE_ITEM:
            title = f"{count} item codes are outside their sections in '{table.name}'"
            problem = (
                f"{count} items have codes with more levels than the code of their section "
                "that do not start with it"
            )
            hint = " When all items of one section disagree with it, check the section's code."
        elif rule == RULE_SECTION:
            title = f"{count} section codes are outside their parent sections in '{table.name}'"
            problem = (
                f"{count} sections have codes with more levels than the code of the section "
                "they are in that do not start with it"
            )
            hint = ""
        else:
            title = f"{count} item codes are lower than the code before them in '{table.name}'"
            problem = (
                f"{count} item codes are lower than the code of the item before them in the "
                "same section"
            )
            hint = ""
        pairs = "; ".join(_pair(table, hit) for hit in hits[:_PAIRS_SHOWN])
        more = f" and {count - _PAIRS_SHOWN} more" if count > _PAIRS_SHOWN else ""
        return context.issues.create(
            self.spec,
            rule_id=rule,
            category=CATEGORY_NUMBERING,
            severity=config.severity(rule),
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(title, 200),
            explanation=clip(
                f"In table '{table.name}', {problem} ({where}). They are reported as one "
                f"finding; the first {len(cells)} codes are highlighted.{hint}",
                2000,
            ),
            table=table,
            cells=cells,
            observed_value=f"{count} codes",
            evidence=[
                _rule_evidence(rule),
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Codes compared",
                    detail=clip(pairs + more, 1000),
                    cells=cells,
                    data={"codes": count, "codes_highlighted": len(cells)},
                ),
            ],
            suggested_action=_ACTIONS[rule],
        )


class _Scan:
    """One table in source order: the hits of all three rules."""

    def __init__(
        self,
        context: ValidationContext,
        config: HierarchyConfig,
        table: Table,
        result: DetectorResult,
    ) -> None:
        self.context, self.config, self.table, self.result = context, config, table, result
        self.section_code_field = context.profile.row_classification.section_code_field
        self.label_fields = context.profile.row_classification.label_fields
        self.sections: dict[str, _Code | None] = {}
        self.previous: dict[tuple[str, int], tuple[Row, _Code]] = {}
        self.hits: list[_Hit] = []

    def run(self) -> list[_Hit]:
        pages = 0
        for row in self.context.rows(self.table, kinds=None):
            if row.kind is RowKind.CARRY_FORWARD:
                pages += 1
            elif row.kind is RowKind.SECTION:
                with row_guard(self.result, self.table, row):
                    self._section(row)
            elif row.kind is RowKind.ITEM:
                with row_guard(self.result, self.table, row):
                    self._item(row, pages)
        return self.hits

    def _section(self, row: Row) -> None:
        code = self._section_code(row.row_id)
        if code is None:
            self.result.count(SECTIONS_WITHOUT_CODE)
            return
        parent_id = row.section_row_id
        parent = self._section_code(parent_id) if parent_id else None
        if parent_id is None or parent is None:
            self.result.count(SECTIONS_WITHOUT_CODED_PARENT)
            return
        self.result.count(Coverage.ROWS_CHECKED)
        if self._outside(code, parent):
            self.hits.append(_Hit(RULE_SECTION, row, code, self.table.row(parent_id), parent))

    def _item(self, row: Row, pages: int) -> None:
        code = self._item_code(row)
        if code is None:
            self.result.count(ITEMS_WITHOUT_CODE)
            return
        section_id = row.section_row_id
        section = self._section_code(section_id) if section_id else None
        if section_id is None or section is None:
            self.result.count(ITEMS_WITHOUT_CODED_SECTION)
            return
        self.result.count(Coverage.ROWS_CHECKED)
        if self._outside(code, section):
            self.hits.append(_Hit(RULE_ITEM, row, code, self.table.row(section_id), section))
            return  # not part of its section's order: one wrong code is one finding
        if not all(_numeric(part) for part in code.segments):
            self.result.count(LETTERS_NOT_ORDERED)
            return
        if not code.exact:
            self.result.count(TYPED_NOT_ORDERED)
            return
        scope = (section_id, pages)
        before = self.previous.get(scope)
        if before is not None and _order_key(code.segments) < _order_key(before[1].segments):
            self.hits.append(_Hit(RULE_ORDER, row, code, before[0], before[1]))
        self.previous[scope] = (row, code)

    def _outside(self, code: _Code, prefix: _Code) -> bool:
        """``code`` has more segments than ``prefix`` and does not start with them. Not
        compared (counted): a ``prefix`` whose last segment cannot be trusted, and codes of
        two numbering schemes (numbers against letters at the same level, such as a section
        'A' with items '1.1')."""
        if len(code.segments) <= len(prefix.segments):
            return False
        if not prefix.exact:
            self.result.count(TYPED_PREFIX_NOT_COMPARED)
            return False
        pairs = zip(prefix.segments, code.segments, strict=False)
        if any(_numeric(mine) != _numeric(theirs) for mine, theirs in pairs):
            self.result.count(OTHER_SCHEME_NOT_COMPARED)
            return False
        return code.segments[: len(prefix.segments)] != prefix.segments

    # ------------------------------------------------------------------ codes
    def _item_code(self, row: Row) -> _Code | None:
        text = self.context.text(self.table, row, self.config.code_field)
        segments = code_segments(text)
        if text is None or segments is None:
            return None
        ref = self.context.cell_ref(self.table, row, self.config.code_field)
        return _Code(text, segments, ref, not self._typed_decimal(row, self.config.code_field))

    def _section_code(self, row_id: str) -> _Code | None:
        """The section's code as normalization established it (``None`` without one)."""
        if row_id not in self.sections:
            row = self.table.row(row_id)
            text = row.classification.code
            segments = code_segments(text)
            code = None
            if text is not None and segments is not None:
                field = self.section_code_field
                exact = field is None or not self._typed_decimal(row, field)
                code = _Code(text, segments, self._section_cell(row), exact)
            self.sections[row_id] = code
        return self.sections[row_id]

    def _section_cell(self, row: Row) -> CellRef | None:
        """The cell the section's code was read from: the code field, else the label."""
        fields = [self.section_code_field] if self.section_code_field else []
        for field in [*fields, *self.label_fields]:
            if self.context.text(self.table, row, field) is not None:
                return self.context.cell_ref(self.table, row, field)
        return None

    def _typed_decimal(self, row: Row, field_id: str) -> bool:
        """True for a cell typed as a number with decimals: a spreadsheet keeps 1.10 as 1.1."""
        value = self.context.value(self.table, row, field_id)
        return isinstance(value, NumberValue) and value.value != value.value.to_integral_value()


def _has_coded_section(context: ValidationContext, table: Table) -> bool:
    return any(
        code_segments(row.classification.code) is not None
        for row in context.rows(table, kinds=(RowKind.SECTION,))
    )


def _numeric(segment: str) -> bool:
    return segment.isascii() and segment.isdigit()


def _order_key(segments: Segments) -> tuple[tuple[int, str], ...]:
    """Numeric order of ASCII-digit segments without leading zeros, without ``int()``."""
    return tuple((len(part), part) for part in segments)


def _shown(code: _Code) -> str:
    return clip(" ".join(code.text.split()), _CODE_CHARS)


def _section_text(table: Table, row: Row) -> str:
    """`` in section 01.02`` for a section code of numbers, the scheme of the codes ordered in
    it. A code with letters is not quoted here: it may be an anonymised token, not a code."""
    section_id = row.section_row_id
    code = table.row(section_id).classification.code if section_id else None
    segments = code_segments(code)
    if code is None or segments is None or not all(_numeric(part) for part in segments):
        return ""
    return f" in section {clip(code, _CODE_CHARS)}"


def _pair(table: Table, hit: _Hit) -> str:
    code, other = _shown(hit.code), _shown(hit.other)
    here, there = row_label(table, hit.row), row_label(table, hit.other_row)
    if hit.rule == RULE_ORDER:
        return f"{other} ({there}) is followed by {code} ({here})"
    return f"{code} ({here}) is inside {other} ({there})"


def _pair_data(hit: _Hit) -> dict[str, JsonScalar]:
    return {
        "code": clip(hit.code.text, 200),
        "code_levels": len(hit.code.segments),
        "compared_with": clip(hit.other.text, 200),
        "compared_levels": len(hit.other.segments),
        "compared_row": hit.other_row.source_row_number,
    }


def _rule_evidence(rule: str) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.RULE,
        label="Numbering rule",
        detail=_RULE_TEXT[rule],
        data={"rule": rule},
    )


_RULE_TEXT = {
    RULE_ITEM: (
        "An item code with more levels than the code of its section starts with the section "
        "code (codes compared by their segments; leading zeros do not count)."
    ),
    RULE_SECTION: (
        "A section code with more levels than the code of the section it is in starts with "
        "that code (codes compared by their segments; leading zeros do not count)."
    ),
    RULE_ORDER: (
        "Inside one section (a page break starts again), item codes made only of numbers are "
        "in ascending order; an equal code is not lower."
    ),
}

_ASK = (
    "If the document comes from someone else, ask its author which code is meant instead of "
    "renumbering it yourself."
)
_ACTIONS = {
    RULE_ITEM: f"Check which section the item belongs to, or whether its code is mistyped. {_ASK}",
    RULE_SECTION: (
        "Check whether the section's code is mistyped or the heading of its parent section is "
        f"missing. {_ASK}"
    ),
    RULE_ORDER: f"Check whether the item was moved or its code mistyped. {_ASK}",
}
