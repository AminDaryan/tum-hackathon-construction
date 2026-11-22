"""Item numbering of a bill: missing items, misplaced items and empty sections.

A tender estimator first checks that the bill is complete. The ordinal numbers (OZ) show it:

* ``numbering_gap``: items of one group are numbered in a regular step (``2.1.10``, ``2.1.20``,
  ...); a step skipped (``2.1.30`` between ``2.1.20`` and ``2.1.40``) is a missing number ->
  suspected anomaly, low, one per gap. Numbers are often deleted on purpose (a removed item);
  only the client can say, so the finding asks.
* ``misplaced_item``: an item whose OZ does not start with the OZ of the section it is printed
  in (``3.2.10`` under ``2.1``): filed in the wrong section, or its number mistyped ->
  suspected anomaly, medium. Where ``deterministic.hierarchy`` (step B2) compares the two
  numbers, it reports the item as an error and this rule leaves it to that check (ADR 0013):
  the section is the item's own, the item's number has more parts, both numbers use digits (or
  both letters) at each level, and the section's number is not a decimal typed in a
  spreadsheet. This rule keeps the other cases, such as ``TEL00009`` in section ``08.01``.
* ``empty_section``: a numbered section heading with no item below it (no item numbered under
  it and none in its rows): its items are missing, or the heading is left over -> suspected
  anomaly, medium. A section holding only notes (preliminary remarks) is not empty, and of
  nested empty sections only the innermost is reported.

A group is judged for gaps only with at least ``min_items`` numbers of which ``regular_share``
follow the most common step, and a gap of at most ``max_missing`` numbers is reported (a larger
jump starts a new block on purpose). Repeated item numbers are reported by
``deterministic.field_constraints`` (unique item codes).
"""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import ClassVar

from pydantic import Field

from app.core.codes import code_segments
from app.models.dataset import Row, RowKind, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType, NumberValue
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
from app.validation.deterministic._support import FieldId, field_label
from app.validation.domain.boq._tender import code_parts, quote

RULE_GAP = "numbering_gap"
RULE_MISPLACED = "misplaced_item"
RULE_EMPTY = "empty_section"
CATEGORY_MISSING = "missing_item"
CATEGORY_NUMBERING = "numbering"
ITEMS_NUMBERED = "items_numbered"
GROUPS_JUDGED = "groups_judged"
SECTIONS_NUMBERED = "sections_numbered"
LEFT_TO_HIERARCHY = "misplaced_left_to_hierarchy"
_Item = tuple[Row, tuple[str, ...]]  # a row and the parts of its number


class NumberingConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field holding the item number.")
    description_field: FieldId = plannable(
        "description", description="Field holding the short text (named in findings)."
    )
    min_items: int = Field(
        default=4, ge=3, le=50, description="Numbers in a group before its gaps are judged."
    )
    regular_share: float = Field(
        default=0.75,
        gt=0.5,
        le=1.0,
        description="Share of a group's steps that must equal its most common step.",
    )
    max_missing: int = Field(
        default=3, ge=1, le=20, description="Most numbers one reported gap may span."
    )


class BoqNumberingDetector(Detector[NumberingConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_numbering",
        name="Missing items in the numbering",
        version="1.0.0",
        category=DetectorCategory.STATISTICAL,
        description=(
            "Reads the item numbers (OZ) of a bill for completeness: numbers skipped in an "
            "otherwise regular sequence, items filed under a section whose number they do not "
            "carry, and numbered section headings without any item."
        ),
        required_fields=("item_code",),
        optional_fields=("description",),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the item number of a bill of quantities.",
        evidence_classes=(EvidenceClass.SUSPECTED_ANOMALY,),
        issue_categories=(CATEGORY_MISSING, CATEGORY_NUMBERING),
        limitations=(
            "Numbers are often removed on purpose (a deleted item); a gap is a question for the "
            "client, not an error.",
            "Only numeric last parts are compared; numbers with letters (1.2.10a) are skipped "
            "for gaps.",
        ),
        references=(
            "VOB/A § 7 (1): the description of the work must be complete; GAEB OZ structure "
            "(ordinal numbers by level).",
        ),
        cost="low",
    )
    config_model = NumberingConfig

    def required_fields(self, config: NumberingConfig) -> tuple[str, ...]:
        return (config.code_field,)

    def applicability(self, context: ValidationContext, config: NumberingConfig) -> Applicability:
        tables = [t.name for t in context.tables() if context.has_fields(t, config.code_field)]
        if not tables:
            return Applicability.no("No table maps the item number.")
        return Applicability.yes(f"Item numbers are mapped in: {', '.join(tables)}.")

    def validate(self, context: ValidationContext, config: NumberingConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            if context.has_fields(table, config.code_field):
                self._table(context, config, table, result)
        return result

    def _table(
        self,
        context: ValidationContext,
        config: NumberingConfig,
        table: Table,
        result: DetectorResult,
    ) -> None:
        items: list[_Item] = []
        for row in context.rows(table):
            parts = code_parts(context.text(table, row, config.code_field))
            if parts:
                items.append((row, parts))
                result.count(ITEMS_NUMBERED)
        sections: dict[str, _Item] = {}
        for row in context.rows(table, [RowKind.SECTION]):
            parts = code_parts(context.text(table, row, config.code_field))
            if parts:
                sections[row.row_id] = (row, parts)
                result.count(SECTIONS_NUMBERED)
        self._gaps(context, config, table, items, result)
        self._misplaced(context, config, table, items, sections, result)
        self._empty(context, config, table, items, sections, result)

    # ------------------------------------------------------------------ gaps
    def _gaps(
        self,
        context: ValidationContext,
        config: NumberingConfig,
        table: Table,
        items: list[_Item],
        result: DetectorResult,
    ) -> None:
        groups: dict[tuple[str, ...], dict[int, Row]] = {}
        for row, parts in items:
            if len(parts) >= 2 and parts[-1].isdigit():
                groups.setdefault(parts[:-1], {}).setdefault(int(parts[-1]), row)
        for prefix, numbered in groups.items():
            numbers = sorted(numbered)
            if len(numbers) < config.min_items:
                continue
            context.checkpoint()
            steps = Counter(b - a for a, b in pairwise(numbers))
            step, count = steps.most_common(1)[0]
            if step <= 0 or count < config.regular_share * (len(numbers) - 1):
                continue
            result.count(GROUPS_JUDGED)
            for before, after in pairwise(numbers):
                gap = after - before
                if gap == step or gap % step or gap // step - 1 > config.max_missing:
                    continue
                missing = [".".join([*prefix, str(n)]) for n in range(before + step, after, step)]
                result.add(
                    self._gap_issue(
                        context,
                        config,
                        table,
                        prefix,
                        step,
                        missing,
                        numbered[before],
                        numbered[after],
                    )
                )

    def _gap_issue(
        self,
        context: ValidationContext,
        config: NumberingConfig,
        table: Table,
        prefix: tuple[str, ...],
        step: int,
        missing: list[str],
        before: Row,
        after: Row,
    ) -> ValidationIssue:
        code = config.code_field
        first = context.text(table, before, code) or ""
        last = context.text(table, after, code) or ""
        cells = [context.cell_ref(table, before, code), context.cell_ref(table, after, code)]
        listed = ", ".join(missing)
        plural = len(missing) > 1
        return context.issues.create(
            self.spec,
            rule_id=RULE_GAP,
            category=CATEGORY_MISSING,
            severity=Severity.LOW,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=f"Item number{'s' if plural else ''} {listed} missing between {first} and {last}",
            explanation=(
                f"The items numbered {'.'.join(prefix)}.… go up in steps of {step}, but "
                f"{listed} {'are' if plural else 'is'} missing between {first} and {last}. "
                "An item may have been left out of the bill, or deleted on purpose; a tender "
                "estimator would ask before pricing."
            ),
            table=table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Numbering step",
                    detail=f"step {step}; missing: {listed}",
                    cells=cells,
                    data={"step": step, "missing": len(missing)},
                )
            ],
            suggested_action=(
                f"Ask the client whether {listed} {'were' if plural else 'was'} deleted on "
                "purpose or is missing from the bill."
            ),
            subject=f"gap:{'.'.join(prefix)}:{missing[0]}",
        )

    # ------------------------------------------------------------------ misplaced
    def _misplaced(
        self,
        context: ValidationContext,
        config: NumberingConfig,
        table: Table,
        items: list[_Item],
        sections: dict[str, _Item],
        result: DetectorResult,
    ) -> None:
        for row, parts in items:
            section = next((sections[s] for s in reversed(row.section_path) if s in sections), None)
            if section is None:
                continue
            section_row, section_parts = section
            if parts[: len(section_parts)] == section_parts:
                continue
            if _hierarchy_reports(context, table, row, section_row, config.code_field):
                result.count(LEFT_TO_HIERARCHY)
                continue
            code = config.code_field
            item_code = context.text(table, row, code) or ""
            section_code = context.text(table, section_row, code) or ""
            label = context.text(table, section_row, config.description_field) or ""
            cells = [context.cell_ref(table, row, code)]
            result.add(
                context.issues.create(
                    self.spec,
                    rule_id=RULE_MISPLACED,
                    category=CATEGORY_NUMBERING,
                    severity=Severity.MEDIUM,
                    evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
                    title=f"Item {item_code} is in section {section_code}",
                    explanation=(
                        f"Item {item_code} is printed in section {section_code} "
                        f"{quote(label, 60)!r}, but its number does not start with "
                        f"{section_code}. The item may be filed in the wrong section, or its "
                        "number is mistyped; either changes which section total it counts in."
                    ),
                    table=table,
                    row=row,
                    cells=cells,
                    evidence=[
                        EvidenceItem(
                            kind=EvidenceKind.COMPARISON,
                            label="Item number and section number",
                            detail=f"{item_code} in {section_code}",
                            cells=[*cells, context.cell_ref(table, section_row, code)],
                        )
                    ],
                    suggested_action=(
                        "Check the item number against the printed bill and the section it "
                        "belongs to."
                    ),
                )
            )

    # ------------------------------------------------------------------ empty sections
    def _empty(
        self,
        context: ValidationContext,
        config: NumberingConfig,
        table: Table,
        items: list[_Item],
        sections: dict[str, _Item],
        result: DetectorResult,
    ) -> None:
        item_parts = [parts for _, parts in items]
        in_section: set[str] = set()  # sections holding an item or a note
        for row in context.rows(table, [RowKind.ITEM, RowKind.TEXT]):
            in_section.update(row.section_path)
        parents: set[str] = set()  # sections holding another section: only the inner is reported
        for section_row, _ in sections.values():
            parents.update(section_row.section_path)
        for section_id, (row, parts) in sections.items():
            if section_id in in_section or section_id in parents:
                continue
            if any(p[: len(parts)] == parts and len(p) > len(parts) for p in item_parts):
                continue
            code = context.text(table, row, config.code_field) or ""
            label = context.text(table, row, config.description_field) or ""
            cells = [context.cell_ref(table, row, config.code_field)]
            result.add(
                context.issues.create(
                    self.spec,
                    rule_id=RULE_EMPTY,
                    category=CATEGORY_MISSING,
                    severity=Severity.MEDIUM,
                    evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
                    title=f"Section {code} has no items: {quote(label, 80)}",
                    explanation=(
                        f"The section {code} {quote(label, 80)!r} has a heading but no item: "
                        f"no item is numbered {code}.… and none is printed in it. Its items "
                        "may be missing from the bill, or the heading is left over."
                    ),
                    table=table,
                    row=row,
                    cells=cells,
                    evidence=[
                        EvidenceItem(
                            kind=EvidenceKind.VALUE,
                            label=field_label(context, config.code_field),
                            detail=f"{code}: no item below it",
                            cells=cells,
                        )
                    ],
                    suggested_action=(
                        "Ask the client whether the section's items are missing, or whether "
                        "the section was dropped."
                    ),
                )
            )


def _hierarchy_reports(
    context: ValidationContext, table: Table, row: Row, section_row: Row, code_field: str
) -> bool:
    """Whether ``deterministic.hierarchy`` reports ``row`` as outside ``section_row``: it compares
    an item with its own section, by the section's code as normalization read it, when the
    item's code has more parts and both use digits (or both letters) at each level, and the
    section's code cell is not a decimal typed in a spreadsheet (``1.1`` kept as ``1.1``)."""
    if row.section_row_id != section_row.row_id:
        return False
    code = code_segments(context.text(table, row, code_field))
    prefix = code_segments(section_row.classification.code)
    if code is None or prefix is None or len(code) <= len(prefix):
        return False
    field = context.profile.row_classification.section_code_field
    value = context.value(table, section_row, field) if field else None
    if isinstance(value, NumberValue) and value.value != value.value.to_integral_value():
        return False
    if any(_digits(a) != _digits(b) for a, b in zip(prefix, code, strict=False)):
        return False
    return code[: len(prefix)] != prefix


def _digits(segment: str) -> bool:
    return segment.isascii() and segment.isdigit()
