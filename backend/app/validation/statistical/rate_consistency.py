"""Identical positions with different unit prices (plan check S2, ``statistical.rate_consistency``).

Positions are identical when their short texts have the same comparison key
(:func:`~app.validation.support.text_keys.description_key`), they are in the same unit and the
same currency, and they do not name different standard texts (``standard_text_key``; a text
with keys from several standard texts is split by key). Identical work normally has one unit
price in a bill, so any difference beyond a small relative tolerance is a question for review.
Items that do not count toward the totals (contingencies without total) are compared too, since
a contingency that repeats a position is normally priced like it (``compare_items_not_in_totals``),
but a finding is anchored on a counted item when the group has one, and an item outside the
totals carries no amount at stake.

* In a group of three or more, each price is compared with the median of the *other* members
  (leave one out), in robust scales of the log price (:mod:`app.validation.support.robust`):
  a price far from the others while they agree is reported on its own row.
* When no member stands out that way (two copies, or a group split into two prices), the
  difference cannot say which price is wrong: one finding highlights every price of the group,
  anchored on the position with the most money at stake.

A difference that is a power of ten (a misplaced decimal point) or two swapped adjacent digits
is named in the explanation; a digit swap is reported even below the tolerance. Every finding
is a ``suspected_anomaly`` whose financial impact (``reference_deviation``) is quantity × (unit
price − reference unit price) × the row's discount factor, the reference being the median of
the other members.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
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
from app.validation.support.robust import (
    exact_median,
    is_adjacent_digit_swap,
    power_of_ten,
    robust_scale,
)

RULE_ID = "identical_positions_price_differs"
ROWS_COMPARED = "rows_compared"
ROWS_WITHOUT_IDENTICAL = "rows_without_identical_positions"
ROWS_NOT_PRICED = "rows_not_priced"
_MEMBERS_SHOWN = 10


class RateConsistencyConfig(DetectorConfig):
    relative_tolerance: float = Field(
        default=0.01,
        ge=0,
        lt=1,
        description="Relative price difference below which identical positions agree.",
    )
    min_log_scale: float = Field(
        default=0.005,
        gt=0,
        description=(
            "Floor of the robust scale of the other members' log prices, so that a group of "
            "equal prices gives a finite score."
        ),
    )
    flag_score: float = Field(
        default=3.5,
        gt=0,
        description="|score| from which one member of a group of three or more stands out.",
    )
    medium_deviation: float = Field(
        default=0.2, gt=0, description="Relative difference from which severity is medium."
    )
    compare_items_not_in_totals: bool = Field(
        default=True,
        description=(
            "Also compare items that do not count toward the totals (a contingency repeating "
            "a position is normally priced like it); findings prefer counted items as anchor."
        ),
    )
    power_of_ten_tolerance: float = Field(
        default=0.02,
        ge=0,
        lt=0.5,
        description="Relative tolerance of a factor 10, 100 or 1,000 between two prices.",
    )


@dataclass(frozen=True, slots=True)
class _Finding:
    record: ItemRecord  # the anchor: the row reported
    members: tuple[ItemRecord, ...]  # the other members of its group
    reference: Decimal  # the reference unit price in the anchor's unit
    single: bool  # True: the anchor stands out; False: the group disagrees as a whole
    score: float | None


class RateConsistencyDetector(Detector[RateConsistencyConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="statistical.rate_consistency",
        name="Identical positions with different unit prices",
        version="1.0.0",
        category=DetectorCategory.STATISTICAL,
        description=(
            "Groups positions with the same text, unit and currency (and the same standard "
            "text key when they have one) and reports unit prices that differ within a group, "
            "with the amount at stake if the position were priced like the others."
        ),
        required_fields=("unit_price", "unit", "description"),
        optional_fields=("quantity", "currency", "standard_text_key", "discount_percent"),
        supported_data_types=(DataType.NUMBER, DataType.TEXT),
        applicability="Tables that map a unit price, a unit and a short text.",
        evidence_classes=(EvidenceClass.SUSPECTED_ANOMALY,),
        issue_categories=(IssueCategory.STATISTICAL_OUTLIER,),
        limitations=(
            "Only positions with the same short text are compared; reworded copies are not.",
            "Identical text can describe work priced differently on purpose (another "
            "building, access, timing); a reviewer decides.",
            "With two different prices the bill cannot tell which one is wrong; both are shown.",
            "A contingency priced differently on purpose from the position it repeats is "
            "reported too.",
        ),
        references=(
            "Iglewicz and Hoaglin (1993), How to Detect and Handle Outliers: modified z-score",
        ),
        cost="low",
    )
    config_model = RateConsistencyConfig

    def applicability(
        self, context: ValidationContext, config: RateConsistencyConfig
    ) -> Applicability:
        unit_field = context.unit_field_id()
        tables = [
            t.name
            for t in context.tables()
            if unit_field and context.has_fields(t, "unit_price", unit_field, "description")
        ]
        if not tables:
            return Applicability.no("No table maps a unit price, a unit and a short text.")
        return Applicability.yes(
            f"Unit prices, units and short texts are mapped in: {', '.join(tables)}."
        )

    def validate(self, context: ValidationContext, config: RateConsistencyConfig) -> DetectorResult:
        result = DetectorResult()
        records = [
            r
            for r in item_frame(context).records
            if config.compare_items_not_in_totals or r.counts_toward_totals is not False
        ]
        priced = [r for r in records if _comparable(r)]
        result.count(ROWS_NOT_PRICED, len(records) - len(priced))
        tables = {t.table_id: t for t in context.tables()}
        rows = {(t.table_id, row.row_id): row for t in tables.values() for row in context.rows(t)}
        currencies = [
            context.currency_evidence(
                tables[r.table_id], rows[(r.table_id, r.row_id)], ["unit_price", "line_total"]
            )
            for r in priced
        ]
        for group in _groups(priced, currencies):
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
        config: RateConsistencyConfig,
        table: Table,
        row: Row,
        finding: _Finding,
    ) -> ValidationIssue:
        record, reference = finding.record, finding.reference
        price = record.unit_price
        assert price is not None  # _comparable
        others = finding.members
        deviation = float(price) / float(reference) - 1
        power = power_of_ten(float(price) / float(reference), config.power_of_ten_tolerance)
        label = _slip_label(price, power, others)
        severity = (
            Severity.HIGH
            if power is not None
            else Severity.MEDIUM
            if abs(deviation) >= config.medium_deviation
            else Severity.LOW
        )
        code = record.item_code or "this position"
        listing = "; ".join(
            f"{m.item_code or '?'}: {fmt(m.unit_price)}" for m in others[:_MEMBERS_SHOWN]
        )
        if len(others) > _MEMBERS_SHOWN:
            listing += f" and {len(others) - _MEMBERS_SHOWN} more"
        slip = f" The difference is {label}." if label else ""
        if finding.single:
            title = f"Unit price {fmt(price)} differs from {len(others)} identical positions"
            explanation = (
                f"The unit price {fmt(price)} of {code} differs by {deviation:+.1%} from the "
                f"median {fmt(reference)} of {len(others)} positions with the same text and "
                f"unit, which agree with each other.{slip} Identical work normally has one "
                "price, so this is a signal for review, not a confirmed error."
            )
            action = (
                f"Is the unit price of {code} a slip, or is this work priced differently on "
                "purpose? Correct the price or record why it differs."
            )
            cells = [c for c in (record.cell("unit_price"),) if c is not None]
        else:
            title = f"Identical positions priced {fmt(price)} and {fmt(reference)}"
            if len(others) > 1:
                title = f"{len(others) + 1} identical positions have different unit prices"
            explanation = (
                f"{code} costs {fmt(price)}, while {len(others)} position(s) with the same text "
                f"and unit cost {listing}.{slip} The bill alone cannot tell which price is "
                "right; identical work normally has one price."
            )
            action = (
                "Which of these unit prices is right? Align the positions, or record why the "
                "same work is priced differently."
            )
            cells = [c for m in (record, *others[:_MEMBERS_SHOWN]) if (c := m.cell("unit_price"))]
        impact = None
        currency = context.currency_evidence(table, row, ["unit_price", "line_total"])
        if (
            currency
            and record.quantity is not None
            and record.discount_factor is not None
            and record.counts_toward_totals is not False
        ):
            amount = multiply(
                multiply(record.quantity, subtract(price, reference)), record.discount_factor
            )
            impact = money_impact(
                RoundingSpec().apply(amount),
                currency,
                f"quantity × (unit price − median of {len(others)} identical positions)",
                reported=price,
                recomputed=reference,
                kind="reference_deviation",
            )
        data: dict[str, str | int | float | bool | None] = {
            "identical_positions": len(others),
            "reference": fmt(reference),
            "relative_difference": round(deviation, 4),
        }
        if label:
            data["slip"] = label
        return context.issues.create(
            self.spec,
            rule_id=RULE_ID,
            category=IssueCategory.STATISTICAL_OUTLIER,
            severity=severity,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=title[:200],
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
                    cells=[c for m in others[:_MEMBERS_SHOWN] if (c := m.cell("unit_price"))],
                    data=data,
                ),
            ],
            suggested_action=action,
            financial_impact=impact,
            anomaly_score=AnomalyScore(
                value=round(finding.score if finding.score is not None else deviation, 2),
                method=(
                    "modified z-score of the log unit price against the other identical "
                    "positions (leave one out)"
                    if finding.single
                    else "relative difference from the median of the other identical positions"
                ),
                interpretation=(
                    "Robust scales between the log unit price and the median of the others' "
                    "log prices (positive = more expensive)."
                    if finding.single
                    else "Unit price / reference unit price − 1 (positive = more expensive)."
                ),
                threshold=config.flag_score if finding.single else config.relative_tolerance,
            ),
        )


def _comparable(record: ItemRecord) -> bool:
    price = record.unit_price_per_base_unit
    return (
        record.unit_id is not None
        and record.description_key is not None
        and price is not None
        and price > 0
    )


def _groups(
    records: Sequence[ItemRecord], currencies: Sequence[str | None]
) -> list[list[ItemRecord]]:
    """Records with the same text key, unit and currency; split by standard text key when the
    group names more than one (members without a key then form their own group)."""
    by_text: dict[tuple[str | None, str | None, str | None], list[ItemRecord]] = defaultdict(list)
    for record, currency in zip(records, currencies, strict=True):
        by_text[(record.description_key, record.unit_id, currency)].append(record)
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


def _per_base(record: ItemRecord) -> Decimal:
    price = record.unit_price_per_base_unit
    assert price is not None  # _comparable
    return price


def _reference(record: ItemRecord, others: Sequence[ItemRecord]) -> Decimal:
    """The median of the others' prices per base unit, in the record's unit."""
    median = exact_median([_per_base(o) for o in others])
    assert median is not None
    return multiply(median, record.multiplier or Decimal(1))


def _differs(
    price: Decimal, reference: Decimal, others: Sequence[ItemRecord], tolerance: float
) -> bool:
    if abs(float(price) / float(reference) - 1) > tolerance:
        return True
    return any(
        o.unit_price is not None and is_adjacent_digit_swap(price, o.unit_price) for o in others
    )


def _findings(group: Sequence[ItemRecord], config: RateConsistencyConfig) -> list[_Finding]:
    logs = np.array([math.log(float(_per_base(r))) for r in group])
    out: list[_Finding] = []
    if len(group) >= 3:
        for i, record in enumerate(group):
            others = tuple(r for j, r in enumerate(group) if j != i)
            other_logs = np.delete(logs, i)
            scale = max(robust_scale(other_logs.tolist()) or 0.0, config.min_log_scale)
            score = (logs[i] - float(np.median(other_logs))) / scale
            if abs(score) < config.flag_score:
                continue
            price = record.unit_price
            assert price is not None
            reference = _reference(record, others)
            if _differs(price, reference, others, config.relative_tolerance):
                out.append(_Finding(record, others, reference, True, float(score)))
    if out:
        return out
    # No member stands out: report the group once if its prices differ at all.
    candidates: list[tuple[tuple[bool, Decimal], _Finding]] = []
    disagree = False
    for i, record in enumerate(group):
        others = tuple(r for j, r in enumerate(group) if j != i)
        price = record.unit_price
        assert price is not None
        reference = _reference(record, others)
        disagree = disagree or _differs(price, reference, others, config.relative_tolerance)
        counted = record.counts_toward_totals is not False
        at_stake = abs((record.quantity or Decimal(0)) * (price - reference))
        candidates.append(((counted, at_stake), _Finding(record, others, reference, False, None)))
    if not disagree:
        return []
    # A counted item first, then the most money at stake; ties go to the later position.
    best = max(range(len(candidates)), key=lambda k: (candidates[k][0], k))
    return [candidates[best][1]]


def _slip_label(price: Decimal, k: int | None, others: Sequence[ItemRecord]) -> str | None:
    """The typing slip a difference fits: a power of ten ``10**k`` or a digit swap."""
    if k is not None:
        factor = f"{10 ** abs(k):,}" if k > 0 else f"1/{10 ** abs(k):,}"
        return f"a factor of {factor} (a misplaced decimal point?)"
    for other in others:
        if other.unit_price is not None and is_adjacent_digit_swap(price, other.unit_price):
            return f"two swapped adjacent digits ({fmt(price)} and {fmt(other.unit_price)})"
    return None
