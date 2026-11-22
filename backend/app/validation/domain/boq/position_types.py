"""Contingency positions and hourly work in a bill, which a bidder must price like any other.

One rule (plan 5a, B2 brief D), finding category in brackets (the category table itself is
maintained elsewhere):

* ``contingency_and_hourly`` [risk]: the bill holds contingency positions (GAEB item type
  "Bedarfsposition mit GB" or "ohne GB", the item type codes of spreadsheet bills such as BmGB
  and BoGB, or a text that says Bedarfsposition, Eventualposition,
  "nur auf (besondere) Anordnung des AG", "nach besonderer Anordnung") or hourly work (item type
  "Stundenlohnarbeiten", or an hour unit with a text that names labour: some bills write "Std"
  for piece x day, so the unit alone is not enough). One finding per table that lists them,
  counts contingency positions with and without total and says whether they count toward the
  totals; semantic warning, low with contingency positions, info with hourly work only.

Rows are read directly (``_clause_support``), not through the item frame, so a tender exported
to Excel without a unit price column is read too.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field, field_validator

from app.models.dataset import CellRef, Table
from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, Severity, ValidationIssue
from app.models.values import DataType
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
from app.validation.deterministic._reference_support import checked_pattern, clip
from app.validation.deterministic._support import FieldId
from app.validation.domain.boq._clause_support import (
    HOUR_UNIT_IDS,
    HOURLY_ITEM_TYPE_PATTERN,
    LABOUR_PATTERN,
    NOTE_ITEM_TYPE_PATTERN,
    ItemText,
    find_in_item,
    is_hourly_labour,
    item_texts,
    positions_list,
    search_text,
    text_tables,
)

RULE = "contingency_and_hourly"
CATEGORY = "position_type"
ITEMS_READ = "items_read"
CONTINGENCY_ITEMS = "contingency_items"
HOURLY_ITEMS = "hourly_items"

# GAEB item types ("Bedarfsposition ohne GB") and the short codes of spreadsheet bills (BmGB,
# BoGB, B, E), as the profile's totals rules read them; "contingency" is the one English code
# those rules name (type_contingency), so an English bill's item type column is read too. The
# totals rules name no English contingency or hourly wording in texts, so neither is matched
# here ("provisional", "daywork" and the like are left to a later step).
CONTINGENCY_ITEM_TYPE_PATTERN = (
    r"\b(?:bedarfs|eventual)position\b"
    r"|^\s*(?:bmgb|emgb|bogb|eogb|b\s*[mo]\.?\s*gb|b|e|bedarf|eventual|contingency)\s*$"
)
CONTINGENCY_TEXT_PATTERN = (
    r"\bbedarfsposition(?:en)?\b|\beventualposition(?:en)?\b"
    r"|\bnur\s+auf\s+(?:besondere\s+)?anordnung\s+(?:des\s+ag|des\s+auftraggebers)\b"
    r"|\bnach\s+besonderer\s+anordnung\b"
)
WITH_TOTAL_PATTERN = r"\bmit\s+(?:gb|gesamtbetrag)\b|^\s*(?:bmgb|emgb|b\s*m\.?\s*gb)\s*$"
WITHOUT_TOTAL_PATTERN = r"\bohne\s+(?:gb|gesamtbetrag)\b|^\s*(?:bogb|eogb|b\s*o\.?\s*gb)\s*$"

RECOMMENDATION = (
    "Price contingency positions and hourly rates at rates that cover cost, like every other "
    "position: the client may order them at these prices. If the tender does not say how "
    "contingency positions are weighed in the bid comparison, ask. In public tenders "
    "contingency positions should in principle not be in the bill, and hourly work only as far "
    "as unavoidable (§ 7 (1) Nr. 4 VOB/A)."
)


class BoqPositionTypesConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field holding the position number.")
    description_field: FieldId = plannable(
        "description", description="Field holding the short text (Kurztext)."
    )
    long_description_field: FieldId = plannable(
        "long_description", description="Field holding the long text (Langtext)."
    )
    item_type_field: FieldId = plannable(
        "item_type", description="Field holding the item type (GAEB Positionsart)."
    )
    note_item_type_pattern: str = Field(
        default=NOTE_ITEM_TYPE_PATTERN,
        description="Item types of notes that stand on their own (Hinweis): not item text.",
    )
    contingency_item_type_pattern: str = Field(
        default=CONTINGENCY_ITEM_TYPE_PATTERN, description="Item types of contingency positions."
    )
    contingency_text_pattern: str = Field(
        default=CONTINGENCY_TEXT_PATTERN,
        description="Texts that make a position a contingency position (Eventualposition).",
    )
    with_total_pattern: str = Field(
        default=WITH_TOTAL_PATTERN, description="Contingency positions with a total (mit GB)."
    )
    without_total_pattern: str = Field(
        default=WITHOUT_TOTAL_PATTERN,
        description="Contingency positions without a total (ohne GB).",
    )
    hourly_item_type_pattern: str = Field(
        default=HOURLY_ITEM_TYPE_PATTERN, description="Item types of hourly work."
    )
    hour_unit_ids: tuple[str, ...] = Field(
        default=HOUR_UNIT_IDS, description="Unit ids (of the unit catalogue) of an hour."
    )
    labour_pattern: str = Field(
        default=LABOUR_PATTERN,
        description="Words that make a position in hours hourly labour (Facharbeiter, Helfer).",
    )
    max_cells_per_issue: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Cells highlighted in one finding (its evidence lists every position).",
    )

    @field_validator(
        "note_item_type_pattern",
        "contingency_item_type_pattern",
        "contingency_text_pattern",
        "with_total_pattern",
        "without_total_pattern",
        "hourly_item_type_pattern",
        "labour_pattern",
    )
    @classmethod
    def _valid_pattern(cls, value: str) -> str:
        return checked_pattern(value, groups=None)


@dataclass(frozen=True, slots=True)
class _Found:
    """A position of one kind and the cell that shows it."""

    item: ItemText
    cell: CellRef
    total: str  # "with", "without" or "" (contingency positions only)


class BoqPositionTypesDetector(Detector[BoqPositionTypesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_position_types",
        name="Contingency positions and hourly work",
        version="1.0.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Lists the contingency positions (Bedarfspositionen, Eventualpositionen) and the "
            "hourly work of a bill of quantities, with or without total, so that the bidder "
            "prices them at rates that cover cost: the client may order them at these prices."
        ),
        required_fields=("description",),
        optional_fields=("item_type", "long_description", "item_code", "unit"),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the item type, the short or the long description.",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(CATEGORY,),
        limitations=(
            "A contingency position is recognised by its GAEB item type or by the words of "
            "its text; one marked only by a section heading is missed.",
            "Hourly work in an hour unit is recognised only when its text names labour "
            "(Facharbeiter, Helfer, Lohn, ...); plant hired by the hour is not listed.",
        ),
        references=("VOB/A 2019 § 7 (1) Nr. 4 (contingency positions and hourly work)",),
        cost="low",
    )
    config_model = BoqPositionTypesConfig

    def required_fields(self, config: BoqPositionTypesConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(
        self, context: ValidationContext, config: BoqPositionTypesConfig
    ) -> Applicability:
        tables = text_tables(context, _fields(config))
        if not tables:
            return Applicability.no("No table maps the item type or an item text.")
        return Applicability.yes(f"Item types or texts are mapped in: {_names(tables)}.")

    def validate(
        self, context: ValidationContext, config: BoqPositionTypesConfig
    ) -> DetectorResult:
        result = DetectorResult()
        for table in text_tables(context, _fields(config)):
            contingency: list[_Found] = []
            hourly: list[_Found] = []
            for item in item_texts(
                context,
                table,
                (config.description_field, config.long_description_field),
                code_field=config.code_field,
                item_type_field=config.item_type_field,
                note_item_type_pattern=config.note_item_type_pattern,
            ):
                context.checkpoint()
                result.count(ITEMS_READ)
                if (found := _contingency(context, config, item)) is not None:
                    contingency.append(found)
                if (found := _hourly(context, config, item)) is not None:
                    hourly.append(found)
            result.count(CONTINGENCY_ITEMS, len(contingency))
            result.count(HOURLY_ITEMS, len(hourly))
            if contingency or hourly:
                result.add(self._issue(context, config, table, contingency, hourly))
        return result

    def _issue(
        self,
        context: ValidationContext,
        config: BoqPositionTypesConfig,
        table: Table,
        contingency: list[_Found],
        hourly: list[_Found],
    ) -> ValidationIssue:
        parts = []
        if contingency:
            parts.append(_count(len(contingency), "contingency position"))
        if hourly:
            parts.append(_count(len(hourly), "position") + " of hourly work")
        title = f"{' and '.join(parts)} to price at rates that cover cost"
        sentences = []
        if contingency:
            sentences.append(
                f"{_count(len(contingency), 'contingency position')} ({_totals(contingency)}); "
                f"{_counted(contingency)}: {positions_list([f.item.label for f in contingency])}."
            )
        if hourly:
            sentences.append(
                f"Hourly work in {_count(len(hourly), 'position')}: "
                f"{positions_list([f.item.label for f in hourly])}."
            )
        sentences.append(
            "The client may order these positions at the prices of the bid, whatever the "
            "quantities in the bill."
        )
        cells = list(dict.fromkeys(f.cell for f in [*contingency, *hourly]))[
            : config.max_cells_per_issue
        ]
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.RULE,
                label="Position types",
                detail=(
                    "Contingency positions: GAEB item type Bedarfsposition (mit or ohne GB) or a "
                    "text that says Bedarfsposition, Eventualposition or 'nur auf Anordnung des "
                    "AG'. Hourly work: item type Stundenlohnarbeiten, or an hour unit with a text "
                    "that names labour."
                ),
                data={
                    "rule_id": RULE,
                    "contingency": len(contingency),
                    "contingency_with_total": sum(f.total == "with" for f in contingency),
                    "contingency_without_total": sum(f.total == "without" for f in contingency),
                    "hourly": len(hourly),
                },
            ),
            *(
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label=label,
                    detail=clip(positions_list([f.item.label for f in found]), 2000),
                    cells=list(dict.fromkeys(f.cell for f in found)),  # every position
                    data={"positions": len(found)},
                )
                for label, found in (
                    ("Contingency positions", contingency),
                    ("Hourly work", hourly),
                )
                if found
            ),
        ]
        return context.issues.create(
            self.spec,
            rule_id=RULE,
            category=CATEGORY,
            severity=Severity.LOW if contingency else Severity.INFO,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(title[:1].upper() + title[1:], 200),
            explanation=" ".join(sentences),
            table=table,
            cells=cells,
            evidence=evidence,
            suggested_action=RECOMMENDATION,
            subject=RULE,
        )


def _fields(config: BoqPositionTypesConfig) -> tuple[str, ...]:
    return (config.item_type_field, config.description_field, config.long_description_field)


def _names(tables: Sequence[Table]) -> str:
    return ", ".join(t.name for t in tables)


def _contingency(
    context: ValidationContext, config: BoqPositionTypesConfig, item: ItemText
) -> _Found | None:
    """The item as a contingency position, shown by its item type or by its text."""
    if item.item_type and search_text(config.contingency_item_type_pattern, item.item_type):
        cell = context.cell_ref(item.table, item.row, config.item_type_field)
        return _Found(item, cell, _total(config, item.item_type))
    phrases = find_in_item(config.contingency_text_pattern, item)
    if not phrases:
        return None
    phrase = phrases[0]
    total = _total(config, phrase.sentence.text)
    return _Found(item, context.cell_ref(item.table, phrase.row, phrase.cell.field_id), total)


def _total(config: BoqPositionTypesConfig, text: str) -> str:
    if search_text(config.with_total_pattern, text):
        return "with"
    if search_text(config.without_total_pattern, text):
        return "without"
    return ""


def _hourly(
    context: ValidationContext, config: BoqPositionTypesConfig, item: ItemText
) -> _Found | None:
    unit_id = item.unit.unit.unit_id if item.unit is not None else None
    if not is_hourly_labour(
        item.item_type,
        unit_id,
        [cell.text for cell in item.cells],
        hour_unit_ids=config.hour_unit_ids,
        item_type_pattern=config.hourly_item_type_pattern,
        labour_pattern=config.labour_pattern,
    ):
        return None
    if item.item_type and search_text(config.hourly_item_type_pattern, item.item_type):
        field_id = config.item_type_field
    else:
        field_id = context.unit_field_id() or config.description_field
    return _Found(item, context.cell_ref(item.table, item.row, field_id), "")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _totals(found: Sequence[_Found]) -> str:
    counts = Counter(f.total for f in found)
    parts = []
    if counts["with"]:
        parts.append(f"{counts['with']} with total")
    if counts["without"]:
        parts.append(f"{counts['without']} without total")
    if counts[""]:
        parts.append(f"{counts['']} not marked")
    return ", ".join(parts)


def _counted(found: Sequence[_Found]) -> str:
    """Whether the contingency positions count toward the totals, as the rows say."""
    counts = Counter(f.item.row.counts_toward_totals for f in found)
    it, count, does = ("it", "counts", "does") if len(found) == 1 else ("they", "count", "do")
    if counts[True] == len(found):
        return f"{it} {count} toward the totals"
    if counts[False] == len(found):
        return f"{it} {does} not count toward the totals"
    if counts[None] == len(found):
        return f"whether {it} {count} toward the totals is not known"
    known = [
        f"{counts[True]} count toward the totals" if counts[True] else "",
        f"{counts[False]} do not" if counts[False] else "",
        f"for {counts[None]} it is not known" if counts[None] else "",
    ]
    return ", ".join(part for part in known if part)
