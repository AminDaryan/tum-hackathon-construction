"""A quantity a power of ten off its identical positions (plan check S3,
``statistical.quantity_factor``).

Positions are identical when their short texts have the same comparison key
(:func:`~app.validation.support.text_keys.description_key`) and they have the same unit, the
same multiplier and the same item type, and do not name different standard texts. Quantities
of identical work legitimately differ within a bill (another building, another phase), so a
difference alone is never reported: only a quantity 10, 100 or 1,000 times (or a tenth, a
hundredth, a thousandth of) the others, within ``factor_tolerance``
(:func:`~app.validation.support.robust.power_of_ten`), the factor a misplaced decimal point or
a quantity entered in a smaller unit leaves behind. The unit slip a factor fits (cm entered as
m) comes from ``unit_slips`` and is named in the explanation.

* In a group of three or more, a quantity is compared with the median of the *other* members
  (leave one out), and only when those agree within ``max_peer_ratio``.
* Two positions alone cannot say which one is wrong: one finding highlights both quantities,
  anchored on the one the named unit slip fits (else the larger).

Items that do not count toward the totals are left out. Every finding is a
``suspected_anomaly`` whose financial impact (``reference_deviation``) is (quantity − reference
quantity) × unit price × the row's discount factor.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

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
from app.validation.contracts.decimal_math import RoundingSpec, multiply, subtract
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.contracts.issue_factory import money_impact
from app.validation.deterministic._support import fmt
from app.validation.support.items import ItemRecord, item_frame
from app.validation.support.robust import exact_median, power_of_ten

RULE_ID = "quantity_power_of_ten"
ROWS_COMPARED = "rows_compared"
ROWS_WITHOUT_IDENTICAL = "rows_without_identical_positions"
ROWS_WITHOUT_QUANTITY = "rows_without_quantity"
_MEMBERS_SHOWN = 10


class QuantityFactorConfig(DetectorConfig):
    factor_tolerance: float = Field(
        default=0.15,
        ge=0,
        lt=0.5,
        description="Relative tolerance of the factor 10, 100 or 1,000 to the reference quantity.",
    )
    max_peer_ratio: float = Field(
        default=1.5,
        ge=1,
        description="Largest / smallest quantity the other identical positions may differ by.",
    )
    small_count_limit: Decimal = Field(
        default=Decimal(100),
        ge=0,
        description=(
            "Whole-number piece counts whose largest value is below this are not compared "
            "(1 and 10 pieces are common legitimately)."
        ),
    )
    unit_slips: dict[str, dict[int, str]] = Field(
        default_factory=lambda: {"m": {2: "cm", 3: "mm"}, "t": {3: "kg"}, "kg": {-3: "t"}},
        description=(
            "Per unit id: the exponent k of a factor 10**k between a quantity and its "
            "reference, and the unit the quantity was then probably entered in."
        ),
    )


@dataclass(frozen=True, slots=True)
class _Finding:
    record: ItemRecord  # the anchor: the row reported
    members: tuple[ItemRecord, ...]  # the other members of its group
    reference: Decimal  # the reference quantity
    exponent: int  # quantity ≈ reference × 10**exponent
    single: bool  # True: compared with agreeing others; False: a pair


class QuantityFactorDetector(Detector[QuantityFactorConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="statistical.quantity_factor",
        name="Quantity a power of ten off identical positions",
        version="1.0.1",
        category=DetectorCategory.STATISTICAL,
        description=(
            "Groups positions with the same text, unit and item type and reports a quantity "
            "10, 100 or 1,000 times (or 1/10 to 1/1,000 of) the others, naming the unit slip "
            "it fits, with the amount at stake if it were measured like them."
        ),
        required_fields=("quantity", "unit", "description", "unit_price"),
        optional_fields=("currency", "standard_text_key", "item_type", "discount_percent"),
        supported_data_types=(DataType.NUMBER, DataType.TEXT),
        applicability="Tables that map a quantity, a unit, a short text and a unit price.",
        evidence_classes=(EvidenceClass.SUSPECTED_ANOMALY,),
        issue_categories=(IssueCategory.STATISTICAL_OUTLIER,),
        limitations=(
            "Only positions with the same short text are compared; reworded copies are not.",
            "Identical work can legitimately be measured ten times larger elsewhere; a "
            "reviewer decides.",
            "A factor near another value (a slip compared with a copy of another size) is "
            "missed: only factors within the tolerance of 10, 100 or 1,000 count.",
            "Items that do not count toward the totals are not compared.",
        ),
        references=(),
        cost="low",
    )
    config_model = QuantityFactorConfig

    def applicability(
        self, context: ValidationContext, config: QuantityFactorConfig
    ) -> Applicability:
        unit_field = context.unit_field_id()
        tables = [
            t.name
            for t in context.tables()
            if unit_field
            and context.has_fields(t, "quantity", unit_field, "description", "unit_price")
        ]
        if not tables:
            return Applicability.no("No table maps a quantity, a unit and a short text.")
        return Applicability.yes(
            f"Quantities, units and short texts are mapped in: {', '.join(tables)}."
        )

    def validate(self, context: ValidationContext, config: QuantityFactorConfig) -> DetectorResult:
        result = DetectorResult()
        records = [r for r in item_frame(context).records if r.counts_toward_totals is not False]
        measured = [r for r in records if _comparable(r)]
        result.count(ROWS_WITHOUT_QUANTITY, len(records) - len(measured))
        tables = {t.table_id: t for t in context.tables()}
        rows = {(t.table_id, row.row_id): row for t in tables.values() for row in context.rows(t)}
        for group in _groups(measured):
            context.checkpoint()
            if len(group) < 2:
                result.count(ROWS_WITHOUT_IDENTICAL, len(group))
                continue
            result.count(ROWS_COMPARED, len(group))
            for finding in _findings(group, config):
                table = tables[finding.record.table_id]
                row = rows[(finding.record.table_id, finding.record.row_id)]
                result.add(self._issue(context, config, table, row, finding))
        return result

    def _issue(
        self,
        context: ValidationContext,
        config: QuantityFactorConfig,
        table: Table,
        row: Row,
        finding: _Finding,
    ) -> ValidationIssue:
        record, reference, k = finding.record, finding.reference, finding.exponent
        quantity = record.quantity
        assert quantity is not None  # _comparable
        others = finding.members
        factor = f"{10 ** abs(k):,} times" if k > 0 else f"1/{10 ** abs(k):,} of"
        slip_unit = config.unit_slips.get(record.unit_id or "", {}).get(k)
        unit_text = record.unit_id or ""
        if slip_unit:
            slip = f" A quantity entered in {slip_unit} instead of {unit_text} leaves this factor."
        else:
            slip = " A misplaced decimal point leaves this factor."
        code = record.item_code or "this position"
        listing = "; ".join(
            f"{m.item_code or '?'}: {fmt(m.quantity)}" for m in others[:_MEMBERS_SHOWN]
        )
        if len(others) > _MEMBERS_SHOWN:
            listing += f" and {len(others) - _MEMBERS_SHOWN} more"
        if finding.single:
            compared = f"the median {fmt(reference)} of {len(others)} identical positions"
            cells = [c for c in (record.cell("quantity"),) if c is not None]
        else:
            other = others[0].item_code or "an identical position"
            compared = f"the quantity {fmt(reference)} of the identical position {other}"
            cells = [c for m in (record, *others) if (c := m.cell("quantity")) is not None]
        explanation = (
            f"The quantity {fmt(quantity)} of {code} is {factor} {compared} (same text and "
            f"unit).{slip} Quantities of identical work can differ, so this is a signal for "
            "review, not a confirmed error."
        )
        if not finding.single:
            explanation += " Two positions alone cannot say which quantity is wrong."
        question = (
            f"Was the quantity entered in {slip_unit}?"
            if slip_unit
            else ("Is the decimal point of the quantity in the right place?")
        )
        impact = None
        currency = context.currency_evidence(table, row, ["unit_price", "line_total"])
        price = record.unit_price
        if currency and price is not None and record.discount_factor is not None:
            amount = multiply(subtract(quantity, reference), price, record.discount_factor)
            impact = money_impact(
                RoundingSpec().apply(amount),
                currency,
                "(quantity − reference quantity of identical positions) × unit price",
                reported=quantity,
                recomputed=reference,
                kind="reference_deviation",
            )
        data: dict[str, str | int | float | bool | None] = {
            "identical_positions": len(others),
            "reference_quantity": fmt(reference),
            "factor_exponent": k,
        }
        if slip_unit:
            data["entered_in"] = slip_unit
        return context.issues.create(
            self.spec,
            rule_id=RULE_ID,
            category=IssueCategory.STATISTICAL_OUTLIER,
            severity=Severity.HIGH if abs(k) >= 2 else Severity.MEDIUM,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=(f"Quantity {fmt(quantity)} is {factor} identical positions ({fmt(reference)})")[
                :200
            ],
            explanation=explanation,
            table=table,
            row=row,
            cells=cells,
            inputs=[cell for member in (record, *others) for cell in member.cells.values()],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"Compared with {len(others)} positions with the same text and unit",
                    detail=listing,
                    cells=[c for m in others[:_MEMBERS_SHOWN] if (c := m.cell("quantity"))],
                    data=data,
                ),
            ],
            suggested_action=(
                f"{question} Check the quantity of {code} against the measurement or the "
                "drawings and correct it if it is a slip."
            ),
            financial_impact=impact,
            anomaly_score=AnomalyScore(
                value=float(k),
                method="power of ten between the quantity and the reference quantity",
                interpretation=(
                    "k of the factor 10**k between the quantity and the reference quantity of "
                    "identical positions (positive = larger)."
                ),
            ),
        )


def _comparable(record: ItemRecord) -> bool:
    return (
        record.unit_id is not None
        and record.description_key is not None
        and record.quantity is not None
        and record.quantity > 0
    )


def _groups(records: Sequence[ItemRecord]) -> list[list[ItemRecord]]:
    """Records with the same text key, unit, multiplier and item type; split by standard text
    key when the group names more than one (members without a key then form their own group)."""
    by_text: dict[tuple[object, ...], list[ItemRecord]] = defaultdict(list)
    for r in records:
        kind = r.item_type.casefold().strip() if r.item_type else None
        by_text[(r.description_key, r.unit_id, r.multiplier, kind)].append(r)
    groups: list[list[ItemRecord]] = []
    for members in by_text.values():
        keys = {m.standard_text_key for m in members} - {None}
        if len(keys) <= 1:
            groups.append(members)
            continue
        by_key: dict[str | None, list[ItemRecord]] = defaultdict(list)
        for member in members:
            by_key[member.standard_text_key].append(member)
        groups.extend(by_key.values())
    return groups


def _quantity(record: ItemRecord) -> Decimal:
    assert record.quantity is not None  # _comparable
    return record.quantity


def _small_counts(group: Sequence[ItemRecord], config: QuantityFactorConfig) -> bool:
    values = [_quantity(r) for r in group]
    return (
        all(r.dimension == "count" for r in group)
        and all(v == v.to_integral_value() for v in values)
        and max(values) < config.small_count_limit
    )


def _findings(group: Sequence[ItemRecord], config: QuantityFactorConfig) -> list[_Finding]:
    if len(group) == 2:
        first, second = group
        if _small_counts(group, config):
            return []
        k = power_of_ten(
            float(_quantity(first)) / float(_quantity(second)), config.factor_tolerance
        )
        if k is None:
            return []
        larger, smaller = (first, second) if k > 0 else (second, first)
        size = abs(k)
        slips = config.unit_slips.get(larger.unit_id or "", {})
        if size not in slips and -size in slips:
            return [_Finding(smaller, (larger,), _quantity(larger), -size, False)]
        return [_Finding(larger, (smaller,), _quantity(smaller), size, False)]
    out: list[_Finding] = []
    if _small_counts(group, config):
        return out
    for i, record in enumerate(group):
        others = tuple(r for j, r in enumerate(group) if j != i)
        values = [_quantity(o) for o in others]
        if float(max(values)) / float(min(values)) > config.max_peer_ratio:
            continue
        reference = exact_median(values)
        assert reference is not None
        k = power_of_ten(float(_quantity(record)) / float(reference), config.factor_tolerance)
        if k is not None:
            out.append(_Finding(record, others, reference, k, True))
    return out
