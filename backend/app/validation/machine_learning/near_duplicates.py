"""Nearly identical positions in one Titel (plan check D1, ``machine_learning.near_duplicates``).

Two priced item rows are a near copy when they lie in the same table and the same top-level
section (Titel; a table without sections counts as one), share the position kind, the unit, the
currency and the exact unit price, their quantities differ by at most
``max_quantity_difference``, and their texts (short and long text) are almost the same:

* the cosine similarity in the run's text index (:mod:`app.validation.support.similar`)
  reaches ``min_similarity``;
* they hold the same numbers in the same order, or are the same comma-separated parts in
  another order: real bills list positions on purpose that differ
  in one dimension (DN 100 against DN 125, 24 cm against 30 cm);
* every word only one text holds pairs with a word only the other holds that is a typo of it
  (the same letters in another order, or one letter more, less or changed in a word of five
  letters or more) or an abbreviation of it ("StB" for "Stahlbeton"). Real bills also list
  positions on purpose that differ in one word ("Vorlauf" and "Rücklauf",
  "Niederspannungskabel" and "Mittelspannungskabel"), which the similarity alone cannot tell
  from a typo.

Texts with the same description key are exact copies, left to ``deterministic.exact_duplicates``
and the rule checks (ADR 0007: one reporting detector per condition). Rows that do not count
toward totals are not compared.

Each pair is one ``suspected_anomaly`` on the later row, with the earlier row in the evidence:
similar positions can be distinct work, so a reviewer decides. Its financial impact is the later
row's line total as a ``potential_double_count``. The score is the text similarity, uncalibrated.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import ClassVar

from pydantic import Field

from app.models.dataset import CellRef, Row, Table
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
from app.validation.contracts.issue_factory import money_impact
from app.validation.deterministic._reference_support import clip
from app.validation.deterministic._support import fmt
from app.validation.support.items import ItemRecord, item_frame
from app.validation.support.similar import text_index
from app.validation.support.text_keys import description_key

RULE_ID = "near_duplicate_position"
ROWS_COMPARED = "rows_compared"
ROWS_NOT_COMPARED = "rows_not_compared"
PAIRS_SAME_TEXT = "pairs_same_text"
PAIRS_DIFFERENT_NUMBERS = "pairs_different_numbers"
PAIRS_DIFFERENT_WORDS = "pairs_different_words"
PAIRS_REPORTED = "pairs_reported"
_FIELDS_SHOWN = ("item_code", "description", "quantity", "unit_price", "line_total")
_DIGITS = re.compile(r"\d+")
_WORDS = re.compile(r"[^\W\d_]+")
# Words shorter than this must match exactly or as an abbreviation: one changed letter turns
# "Typ A" into "Typ B" or "Rohr" into "Rohe", which are other work, not typos.
_MIN_TYPO_LENGTH = 5


class NearDuplicatesConfig(DetectorConfig):
    min_similarity: float = Field(
        default=0.60,
        gt=0,
        le=1,
        description=(
            "Cosine similarity of the texts from which two positions are near copies (one "
            "swapped letter in a short text scores about 0.7: the rare misspelt word weighs much)."
        ),
    )
    max_quantity_difference: float = Field(
        default=0.10,
        ge=0,
        lt=1,
        description="Largest relative difference of the quantities (0.10 = ±10 %).",
    )
    severity_near_duplicate: Severity = Field(
        default=Severity.MEDIUM, description="Severity of a near copy."
    )


class NearDuplicatesDetector(Detector[NearDuplicatesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="machine_learning.near_duplicates",
        name="Nearly identical positions in one section",
        version="1.0.0",
        category=DetectorCategory.MACHINE_LEARNING,
        description=(
            "Finds positions of the same top-level section with the same unit, unit price, "
            "numbers and nearly the same quantity whose texts differ only slightly (a reordered "
            "phrase, an abbreviation, a typo) under another item code, and the line total that "
            "may be counted twice."
        ),
        required_fields=("unit_price", "unit", "description"),
        optional_fields=("long_description", "quantity", "line_total", "item_code", "currency"),
        supported_data_types=(DataType.NUMBER, DataType.TEXT),
        applicability="Tables that map a unit price, a unit and a description.",
        evidence_classes=(EvidenceClass.SUSPECTED_ANOMALY,),
        issue_categories=(IssueCategory.DUPLICATE,),
        limitations=(
            "Compares positions within one top-level section of one table only.",
            "Similar wording with the same numbers does not prove the same work; a bill may "
            "list similar work twice on purpose.",
            "Positions with identical text are left to the rule checks; positions whose texts "
            "differ in any number are never compared.",
            "The score is the text similarity, uncalibrated: not a probability of error.",
        ),
        cost="medium",
    )
    config_model = NearDuplicatesConfig

    def applicability(
        self, context: ValidationContext, config: NearDuplicatesConfig
    ) -> Applicability:
        unit_field = context.unit_field_id()
        tables = [
            t.name
            for t in context.tables()
            if unit_field and context.has_fields(t, "unit_price", unit_field, "description")
        ]
        if not tables:
            return Applicability.no("No table maps a unit price, a unit and a description.")
        return Applicability.yes(
            f"Unit prices, units and descriptions are mapped in: {', '.join(tables)}."
        )

    def validate(self, context: ValidationContext, config: NearDuplicatesConfig) -> DetectorResult:
        result = DetectorResult()
        records = item_frame(context).records
        similarity = text_index(context)
        tables = {t.table_id: t for t in context.tables()}
        rows = {(t.table_id, row.row_id): row for t in tables.values() for row in context.rows(t)}
        groups: dict[tuple[object, ...], list[int]] = {}
        for i, record in enumerate(records):
            if not _comparable(record):
                result.count(ROWS_NOT_COMPARED)
                continue
            result.count(ROWS_COMPARED)
            table = tables[record.table_id]
            row = rows[(record.table_id, record.row_id)]
            currency = context.currency_evidence(table, row, ["unit_price", "line_total"])
            key = (
                record.table_id,
                record.section_path[0] if record.section_path else None,
                record.unit_id,
                currency,
                record.unit_price,
                record.item_type,
            )
            groups.setdefault(key, []).append(i)
        for members in groups.values():
            for later_at, j in enumerate(members):
                for i in members[:later_at]:
                    context.checkpoint()
                    earlier, later = records[i], records[j]
                    if not _quantities_close(earlier, later, config.max_quantity_difference):
                        continue
                    if earlier.description_key == later.description_key:
                        result.count(PAIRS_SAME_TEXT)
                        continue
                    score = float(similarity[i, j])
                    if score < config.min_similarity:
                        continue
                    if not _same_numbers(earlier, later):
                        result.count(PAIRS_DIFFERENT_NUMBERS)
                        continue
                    if not _same_words(_words(earlier), _words(later)):
                        result.count(PAIRS_DIFFERENT_WORDS)
                        continue
                    result.count(PAIRS_REPORTED)
                    result.add(
                        self._issue(
                            context,
                            config,
                            tables[later.table_id],
                            rows[(later.table_id, later.row_id)],
                            rows[(earlier.table_id, earlier.row_id)],
                            earlier,
                            later,
                            score,
                        )
                    )
        return result

    def _issue(
        self,
        context: ValidationContext,
        config: NearDuplicatesConfig,
        table: Table,
        row: Row,
        earlier_row: Row,
        earlier: ItemRecord,
        later: ItemRecord,
        score: float,
    ) -> ValidationIssue:
        earlier_name = earlier.item_code or "an earlier position"
        later_name = later.item_code or "this position"
        impact = None
        currency = context.currency_evidence(table, row, ["line_total", "unit_price"])
        if currency and later.line_total:
            impact = money_impact(
                later.line_total,
                currency,
                f"line total of {later_name}, a near copy of {earlier_name}",
                kind="potential_double_count",
            )
        return context.issues.create(
            self.spec,
            rule_id=RULE_ID,
            category=IssueCategory.DUPLICATE,
            severity=config.severity_near_duplicate,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=clip(f"{later_name} nearly repeats {earlier_name} in the same section", 200),
            explanation=clip(
                f"{later_name} has the same unit, the same unit price"
                f"{_quantity_note(earlier, later)} as {earlier_name} (row "
                f"{earlier_row.source_row_number}), and its text differs only slightly "
                f"(similarity {score:.2f}, the same numbers). If both describe the same work, "
                "it is counted twice. Similar positions can be distinct work, so this is a "
                "signal for review, not a confirmed error.",
                2000,
            ),
            table=table,
            row=row,
            cells=_cells(later),
            inputs=[*later.cells.values(), *earlier.cells.values()],
            observed_value=clip(later.description or "", 200),
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"Compared with {earlier_name}",
                    detail=clip(
                        f"{earlier_name}: '{earlier.description or ''}'; "
                        f"{later_name}: '{later.description or ''}'",
                        1000,
                    ),
                    cells=[*_cells(earlier), *_cells(later)],
                    data={
                        "similarity": round(score, 3),
                        "unit_price": fmt(later.unit_price),
                        "earlier_quantity": fmt(earlier.quantity),
                        "later_quantity": fmt(later.quantity),
                    },
                ),
            ],
            suggested_action=(
                f"Check whether {later_name} and {earlier_name} describe the same work; if so, "
                "remove the copy, otherwise make the difference explicit in the text."
            ),
            financial_impact=impact,
            anomaly_score=AnomalyScore(
                value=round(score, 3),
                method="cosine similarity of TF-IDF weighted character n-grams of the texts",
                interpretation="1 = the same n-grams; positions with identical text are skipped.",
                threshold=config.min_similarity,
            ),
            subject=f"near_copy_of:{earlier.table_id}:{earlier.row_id}",
        )


def _comparable(record: ItemRecord) -> bool:
    return (
        record.counts_toward_totals is not False
        and record.unit_id is not None
        and record.unit_price is not None
        and bool(record.description_key)
    )


def _quantities_close(a: ItemRecord, b: ItemRecord, limit: float) -> bool:
    if a.quantity is None or b.quantity is None:
        return a.quantity is None and b.quantity is None
    larger = max(abs(a.quantity), abs(b.quantity))
    if larger == 0:
        return True
    return float(abs(a.quantity - b.quantity) / larger) <= limit + 1e-9


def _text(record: ItemRecord) -> str:
    return f"{record.description or ''} {record.long_description or ''}"


def _same_numbers(a: ItemRecord, b: ItemRecord) -> bool:
    """The same numbers in the same order, or the same comma-separated parts in another order
    (a reordered phrase moves its numbers; "grade 2, phase 3" and "grade 3, phase 2" differ)."""
    if _DIGITS.findall(_text(a)) == _DIGITS.findall(_text(b)):
        return True
    return _parts(a) == _parts(b)


def _parts(record: ItemRecord) -> list[str]:
    return sorted(part.strip() for part in description_key(_text(record)).split(","))


def _words(record: ItemRecord) -> Counter[str]:
    return Counter(_WORDS.findall(_text(record).casefold()))


def _same_words(a: Counter[str], b: Counter[str]) -> bool:
    """Whether the words of two texts are the same up to order, typos and abbreviations: each
    word only one text holds pairs with a word only the other holds that is a typo of it or
    an abbreviation of it (or it of that word). Another word ("Vorlauf" for "Rücklauf",
    "Mittelspannungskabel" for "Niederspannungskabel") makes the texts different work."""
    only_a = sorted((a - b).elements())
    only_b = sorted((b - a).elements())
    if len(only_a) != len(only_b):
        return False
    for word in only_a:
        match = next((other for other in only_b if _variant(word, other)), None)
        if match is None:
            return False
        only_b.remove(match)
    return True


def _variant(a: str, b: str) -> bool:
    """A typo (the same letters in another order, or one letter added, dropped or changed in a
    long word) or an abbreviation (the short word's letters appear in order in the long word,
    starting with its first letter: "StB" for "Stahlbeton", "u" for "und")."""
    short, long = sorted((a, b), key=len)
    if short[0] == long[0] and len(short) < len(long) and _subsequence(short, long):
        return True
    if sorted(a) == sorted(b):
        return True
    return len(long) >= _MIN_TYPO_LENGTH and _one_edit(short, long)


def _subsequence(short: str, long: str) -> bool:
    letters = iter(long)
    return all(letter in letters for letter in short)


def _one_edit(short: str, long: str) -> bool:
    if len(long) - len(short) > 1:
        return False
    start = 0
    while start < len(short) and short[start] == long[start]:
        start += 1
    if len(short) == len(long):
        return short[start + 1 :] == long[start + 1 :]
    return short[start:] == long[start + 1 :]


def _cells(record: ItemRecord) -> list[CellRef]:
    return [c for field in _FIELDS_SHOWN if (c := record.cell(field)) is not None]


def _quantity_note(earlier: ItemRecord, later: ItemRecord) -> str:
    if earlier.quantity == later.quantity:
        return " and the same quantity"
    return f" and a similar quantity ({fmt(later.quantity)} against {fmt(earlier.quantity)})"
