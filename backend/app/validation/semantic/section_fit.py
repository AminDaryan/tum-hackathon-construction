"""Positions whose text is much closer to another section than to their own (plan check T1,
``semantic.section_fit``).

A row is compared at the level of its innermost section (a Titel, or an Untertitel inside one)
with the sibling sections of that section: the sections of the same table with the same parent
(the other Titel of the same Los, the other Untertitel of the same Titel). A section holds the
items of its subsections; sections with fewer than ``min_section_size`` item rows do not take
part, and a row whose section has no large enough sibling is compared one level up. Comparing
siblings, not the top level, matters because the top level is often a Los (lot) per building,
and lots repeat the same work.

A row's fit with a section is the mean of its ``top_k`` highest text similarities (shared text
index, :mod:`app.validation.support.similar`) to that section's members, the row itself left
out. The row is reported when a sibling section fits with at least ``min_similarity`` and by at
least ``min_margin`` more than its own section, and no member of its own section is at least
``max_own_similarity`` similar to it (a twin at home shows the row belongs there, even when a
parallel section holds more like it).

Real sections often hold mixed work, so the check is conservative: it needs a clear margin, a
closely matching other section and enough members on both sides. Every finding is a
``semantic_warning``: a position may belong where it is for reasons its text does not show,
so a reviewer decides. No amount is stated: a position in the wrong section changes section
subtotals, not the bill's total.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from pydantic import Field

from app.models.dataset import Row, Table
from app.models.issue import (
    AnomalyScore,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.support.items import ItemRecord, item_frame
from app.validation.support.similar import text_index

RULE_ID = "position_closer_to_other_section"
ROWS_COMPARED = "rows_compared"
ROWS_IN_SMALL_SECTIONS = "rows_in_small_sections"
ROWS_WITHOUT_SECTION = "rows_without_section"
_SHOWN = 5

Section = tuple[str, tuple[str, ...]]  # (table id, section path: row ids of section rows)


class SectionFitConfig(DetectorConfig):
    top_k: int = Field(
        default=3, ge=1, le=20, description="Most similar members averaged per section."
    )
    min_section_size: int = Field(
        default=4,
        ge=2,
        le=100,
        description="Item rows a section needs (the row itself included) to be compared.",
    )
    min_similarity: float = Field(
        default=0.7, gt=0, lt=1, description="Fit with the other section a finding needs."
    )
    min_margin: float = Field(
        default=0.5,
        gt=0,
        lt=1,
        description="How much better the other section must fit than the row's own.",
    )
    max_own_similarity: float = Field(
        default=0.5,
        gt=0,
        le=1,
        description=(
            "A row with a position at least this similar in its own section fits there and is "
            "not reported."
        ),
    )
    medium_margin: float = Field(
        default=0.7, gt=0, lt=1, description="Margin from which severity is medium."
    )


@dataclass(frozen=True, slots=True)
class _Misfit:
    record: ItemRecord
    own: Section
    other: Section
    own_fit: float
    other_fit: float
    own_closest: tuple[tuple[ItemRecord, float], ...]
    other_closest: tuple[tuple[ItemRecord, float], ...]

    @property
    def margin(self) -> float:
        return self.other_fit - self.own_fit


class SectionFitDetector(Detector[SectionFitConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="semantic.section_fit",
        name="Position closer to another section",
        version="1.0.0",
        category=DetectorCategory.SEMANTIC,
        description=(
            "Compares each position's text with the positions of its own section and with those "
            "of its sibling sections (same parent section) of the table, and reports a position "
            "much closer to another section than to its own."
        ),
        required_fields=("description",),
        optional_fields=("long_description", "item_code"),
        supported_data_types=(DataType.TEXT,),
        applicability="Priced tables with descriptions and sections (Titel).",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(IssueCategory.SEMANTIC,),
        limitations=(
            "Needs section rows; tables without them are not checked.",
            "Sections often hold mixed work; a position may belong where it is for reasons its "
            "text does not show.",
            "Sections with fewer than the configured number of item rows are not compared.",
            "The score is uncalibrated: a difference of text similarities, not a probability "
            "of error.",
        ),
        references=("ADR 0010: T1, a text much closer to another Titel than to its own",),
        cost="medium",
    )
    config_model = SectionFitConfig

    def applicability(self, context: ValidationContext, config: SectionFitConfig) -> Applicability:
        tables = [
            t.name
            for t in context.tables()
            if context.has_fields(t, "unit_price", "description")
            and any(r.section_path for r in context.rows(t))
        ]
        if not tables:
            return Applicability.no("No priced table with descriptions has section rows.")
        return Applicability.yes(f"Descriptions and sections are found in: {', '.join(tables)}.")

    def validate(self, context: ValidationContext, config: SectionFitConfig) -> DetectorResult:
        result = DetectorResult()
        records = item_frame(context).records
        similarity = text_index(context)
        tables = {t.table_id: t for t in context.tables()}
        for misfit in _misfits(records, similarity, config, result):
            context.checkpoint()
            table = tables[misfit.record.table_id]
            result.add(self._issue(context, config, table, table.row(misfit.record.row_id), misfit))
        return result

    def _issue(
        self,
        context: ValidationContext,
        config: SectionFitConfig,
        table: Table,
        row: Row,
        misfit: _Misfit,
    ) -> ValidationIssue:
        record = misfit.record
        code = record.item_code or "this position"
        own_name = _section_name(context, table, misfit.own[1][-1])
        other_name = _section_name(context, table, misfit.other[1][-1])
        own_cell = record.cell("description")
        return context.issues.create(
            self.spec,
            rule_id=RULE_ID,
            category=IssueCategory.SEMANTIC,
            severity=Severity.MEDIUM if misfit.margin >= config.medium_margin else Severity.LOW,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=f"Position closer to section {other_name} than to its own section {own_name}"[
                :200
            ],
            explanation=(
                f"The text of {code} matches the positions of section {other_name} "
                f"(mean similarity {misfit.other_fit:.2f} of the {config.top_k} closest) much "
                f"better than those of its own section {own_name} ({misfit.own_fit:.2f}). It "
                "may have been placed in the wrong section; sections often hold mixed work, so "
                "this is a signal for review, not a confirmed error."
            ),
            table=table,
            row=row,
            cells=[own_cell] if own_cell is not None else [],
            inputs=[
                cell
                for member in (record, *(m for m, _ in misfit.other_closest))
                for cell in member.cells.values()
            ],
            evidence=[
                _comparison(f"Closest positions in section {other_name}", misfit.other_closest),
                _comparison(f"Closest positions in its own section {own_name}", misfit.own_closest),
            ],
            suggested_action=(
                f"Check whether {code} belongs in section {other_name}; if it does, move it "
                "there with a code of that section, otherwise leave it."
            ),
            anomaly_score=AnomalyScore(
                value=round(misfit.margin, 2),
                method=f"mean of the top {config.top_k} text similarities, other minus own section",
                interpretation=(
                    "How much closer the text is to the other section's positions than to its "
                    "own section's (cosine similarity, 0 to 1)."
                ),
                threshold=config.min_margin,
            ),
        )


def _comparison(label: str, members: Sequence[tuple[ItemRecord, float]]) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.COMPARISON,
        label=label,
        detail="; ".join(
            f"{m.item_code or '?'} (similarity {s:.2f}): {_short(m.description)}"
            for m, s in members
        ),
        cells=[c for m, _ in members if (c := m.cell("description")) is not None],
        data={"positions": len(members), "highest_similarity": round(members[0][1], 2)}
        if members
        else {"positions": 0},
    )


def _misfits(
    records: Sequence[ItemRecord],
    similarity: np.ndarray,
    config: SectionFitConfig,
    result: DetectorResult,
) -> list[_Misfit]:
    # Members of every section at every level: a section holds the items of its subsections.
    members: dict[Section, list[int]] = {}
    for i, record in enumerate(records):
        if not (record.section_path and record.description):
            result.count(ROWS_WITHOUT_SECTION)
            continue
        for depth in range(1, len(record.section_path) + 1):
            members.setdefault((record.table_id, record.section_path[:depth]), []).append(i)
    large = {s: np.array(m) for s, m in members.items() if len(m) >= config.min_section_size}
    siblings: dict[Section, list[Section]] = {}
    for key in large:
        siblings.setdefault((key[0], key[1][:-1]), []).append(key)
    out: list[_Misfit] = []
    for i, record in enumerate(records):
        if not (record.section_path and record.description):
            continue
        compared = _compared(record, large, siblings)
        if compared is None:
            result.count(ROWS_IN_SMALL_SECTIONS)
            continue
        own, others = compared
        result.count(ROWS_COMPARED)
        own_rows = large[own]
        own_closest = _closest(similarity, i, own_rows[own_rows != i], config.top_k)
        if own_closest and own_closest[0][1] >= config.max_own_similarity:
            continue
        own_fit = _fit(own_closest)
        fits = [(_closest(similarity, i, large[s], config.top_k), s) for s in others]
        other_closest, other = max(fits, key=lambda f: _fit(f[0]))
        other_fit = _fit(other_closest)
        if other_fit < config.min_similarity or other_fit - own_fit < config.min_margin:
            continue
        out.append(
            _Misfit(
                record,
                own,
                other,
                own_fit,
                other_fit,
                tuple((records[j], s) for j, s in own_closest[:_SHOWN]),
                tuple((records[j], s) for j, s in other_closest[:_SHOWN]),
            )
        )
    return out


def _compared(
    record: ItemRecord,
    large: dict[Section, np.ndarray],
    siblings: dict[Section, list[Section]],
) -> tuple[Section, list[Section]] | None:
    """The row's innermost section large enough to compare and its large sibling sections
    (same parent section), going up a level while there are none."""
    path = record.section_path
    for depth in range(len(path), 0, -1):
        own: Section = (record.table_id, path[:depth])
        if own not in large:
            continue
        others = [s for s in siblings.get((record.table_id, path[: depth - 1]), []) if s != own]
        if others:
            return own, others
    return None


def _closest(similarity: np.ndarray, i: int, rows: np.ndarray, k: int) -> list[tuple[int, float]]:
    values = similarity[i, rows]
    order = np.argsort(-values, kind="stable")[:k]
    return [(int(rows[o]), float(values[o])) for o in order]


def _fit(closest: Sequence[tuple[int, float]]) -> float:
    return float(np.mean([s for _, s in closest])) if closest else 0.0


def _section_name(context: ValidationContext, table: Table, section_id: str) -> str:
    if not table.has_row(section_id):
        return "(unknown)"
    section = table.row(section_id)
    code = section.classification.code
    text = context.text(table, section, "description")
    if code and text:
        return f"{code} '{_short(text, 40)}'"
    if code or text:
        return code or f"'{_short(text, 40)}'"
    return f"in row {section.source_row_number}"


def _short(text: str | None, limit: int = 60) -> str:
    if not text:
        return "(no text)"
    return text if len(text) <= limit else text[: limit - 1] + "…"
