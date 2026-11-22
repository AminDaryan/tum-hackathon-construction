"""Unit prices far from comparable positions (plan check S1, ``statistical.peer_price``).

Each priced item row is compared with the tightest group of comparable positions that has at
least ``min_peers`` members, tried in this order (only positions that count toward the total
are members, so a contingency position priced unlike its normal counterparts stands out, and
its own price never shifts a group):

1. ``text``: the most similar descriptions in the same unit (cosine similarity of TF-IDF
   weighted character n-grams of the short text and the start of the long text), kept within
   ``text_band`` of the most similar one (at least ``min_peers`` of the closest are kept), so
   that the row's own kind of work is not outvoted by looser matches (on the BoQ benchmark,
   seed 20261120, this cut the signals on unplanted rows from 327 to 106 and every planted
   error found before is still found);
2. ``section``: the same unit in the same top-level section (Titel) of the bill;
3. ``unit``: the same unit anywhere in the bill.

Only the first is tried by default (``peer_groups``): the same unit in a section or a bill is
mostly different work, and on the BoQ benchmark (seeds 20261120 and 7) these groups added no
planted price error the text group missed while tripling the signals on unplanted rows.

A row with no such group is counted as not compared (``rows_without_peers``), never passed
silently. The statistic is the leave-one-out modified z-score of the natural log of the unit
price per base unit (:mod:`app.validation.support.robust`), with a floor on the scale so that a
group of nearly equal prices does not turn a small difference into a large score. Logs make a
price ten times too high and one ten times too low equally far from the group.

Every finding is a ``suspected_anomaly``: comparable work can be priced differently for good
reasons, so a reviewer decides. Its severity grows with the score, and its financial impact
(``reference_deviation``) is what would change if the row were priced at the group's median:
quantity × (unit price − reference unit price) × the row's discount factor. The review lanes
of the interface order findings by these two fields.

Evaluated on the hackathon's three priced bills by planting price slips (×10, ÷10, 0.01) into
real positions; that spike measured planted slips only, not the errors a bill really holds.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar, Literal

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
from app.validation.contracts.decimal_math import (
    RoundingSpec,
    format_amount,
    format_decimal,
    multiply,
    subtract,
)
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
from app.validation.support.items import ItemRecord, item_frame, unit_price_applicability
from app.validation.support.robust import exact_median, robust_scale
from app.validation.support.similar import similarity_matrix

RULE_ID = "peer_price_outlier"
ROWS_COMPARED = "rows_compared"
ROWS_WITHOUT_PEERS = "rows_without_peers"
ROWS_NOT_PRICED = "rows_not_priced"
TIERS = ("text", "section", "unit")
TIER_LABELS = {
    "text": "positions with similar text in the same unit",
    "section": "positions in the same unit and the same section",
    "unit": "positions in the same unit",
}
_PEER_CELLS_SHOWN = 10


PeerGroup = Literal["text", "section", "unit"]


def _text_only() -> list[PeerGroup]:
    return ["text"]


class PeerPriceConfig(DetectorConfig):
    min_peers: int = Field(default=3, ge=2, le=50, description="Members a peer group needs.")
    text_similarity: float = Field(
        default=0.30, gt=0, lt=1, description="Cosine similarity a text peer needs."
    )
    max_text_peers: int = Field(
        default=10, ge=2, le=100, description="Most similar positions used as text peers."
    )
    text_band: float = Field(
        default=0.25,
        gt=0,
        le=1,
        description=(
            "Text peers are at most this much less similar than the most similar one (but at "
            "least min_peers are kept), so a group of the same work is not outvoted by looser "
            "matches (a pressure test by pipe laying, single doors by double doors)."
        ),
    )
    min_log_scale: float = Field(
        default=0.23,
        gt=0,
        description=(
            "Floor of the robust scale of log prices (0.23 ≈ ±26 %), so groups of nearly "
            "equal prices do not inflate scores."
        ),
    )
    flag_score: float = Field(
        default=3.0, gt=0, description="|score| from which a row is reported (low severity)."
    )
    medium_score: float = Field(default=3.5, gt=0, description="|score| for medium severity.")
    high_score: float = Field(default=6.0, gt=0, description="|score| for high severity.")
    min_ratio: float = Field(
        default=1.0,
        ge=1,
        description=(
            "Report a row that counts toward the total only when its unit price is at least "
            "this many times above or below the group's median (1 = any score from "
            "flag_score). Prices 2 to 4 times apart are common between comparable positions "
            "of a correct bill; contingency and alternative items are reported at any ratio."
        ),
    )
    peer_groups: list[PeerGroup] = Field(
        default_factory=_text_only,
        min_length=1,
        description=(
            "Peer groups tried in order. Only similar text by default: on the BoQ benchmark the "
            "section and unit groups found no planted price error the text group missed and "
            "tripled the signals on unplanted rows."
        ),
    )


@dataclass(frozen=True, slots=True)
class _Scored:
    record: ItemRecord
    tier: str
    peers: tuple[ItemRecord, ...]
    score: float


class PeerPriceDetector(Detector[PeerPriceConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="statistical.peer_price",
        name="Unit price far from comparable positions",
        version="1.1.0",
        category=DetectorCategory.STATISTICAL,
        description=(
            "Compares each unit price with comparable positions of the bill (similar text in "
            "the same unit, else the same unit and section, else the same unit) by a robust, "
            "leave-one-out z-score of the log price, and reports prices far from them with "
            "the amount at stake if the row were priced like them."
        ),
        required_fields=("unit_price", "unit"),
        optional_fields=("description", "long_description", "quantity", "currency"),
        supported_data_types=(DataType.NUMBER, DataType.TEXT),
        applicability="Tables that map a unit price and a unit (priced bills of quantities).",
        evidence_classes=(EvidenceClass.SUSPECTED_ANOMALY,),
        issue_categories=(IssueCategory.STATISTICAL_OUTLIER,),
        limitations=(
            "Compares positions within one bill only; no price history from other projects.",
            "Similar wording does not prove equivalent work; comparable work can be priced "
            "differently for good reasons (quantity, access, location).",
            "The score is uncalibrated: a distance in robust scales, not a probability of error.",
            "Rows without a group of comparable positions are counted, not checked.",
        ),
        references=(
            "Iglewicz and Hoaglin (1993), How to Detect and Handle Outliers: modified z-score",
        ),
        cost="medium",
    )
    config_model = PeerPriceConfig

    def applicability(self, context: ValidationContext, config: PeerPriceConfig) -> Applicability:
        return unit_price_applicability(context)

    def validate(self, context: ValidationContext, config: PeerPriceConfig) -> DetectorResult:
        result = DetectorResult()
        records = list(item_frame(context).records)
        priced = [r for r in records if _comparable(r)]
        result.count(ROWS_NOT_PRICED, len(records) - len(priced))
        similarity = similarity_matrix(priced)
        tables = {t.table_id: t for t in context.tables()}
        rows = {(t.table_id, row.row_id): row for t in tables.values() for row in context.rows(t)}
        currencies = [
            context.currency_evidence(
                tables[r.table_id], rows[(r.table_id, r.row_id)], ["unit_price", "line_total"]
            )
            for r in priced
        ]
        for scored in _score_all(priced, similarity, currencies, config, result):
            context.checkpoint()
            if abs(scored.score) < config.flag_score:
                continue
            # A contingency or alternative item priced unlike normal work is reported at any
            # ratio: speculative pricing of such items is a known tactic.
            counted = scored.record.counts_toward_totals is not False
            if counted and _ratio(scored) < config.min_ratio:
                continue
            table = tables[scored.record.table_id]
            row = rows[(scored.record.table_id, scored.record.row_id)]
            result.add(self._issue(context, config, table, row, scored))
        return result

    def _issue(
        self,
        context: ValidationContext,
        config: PeerPriceConfig,
        table: Table,
        row: Row,
        scored: _Scored,
    ) -> ValidationIssue:
        record = scored.record
        price = record.unit_price
        assert price is not None  # _comparable: every scored row has a positive price
        reference_per_base = exact_median(
            [p.unit_price_per_base_unit for p in scored.peers if p.unit_price_per_base_unit]
        )
        assert reference_per_base is not None
        reference = multiply(reference_per_base, record.multiplier or Decimal(1))
        direction = "above" if scored.score > 0 else "below"
        size = abs(scored.score)
        severity = (
            Severity.HIGH
            if size >= config.high_score
            else Severity.MEDIUM
            if size >= config.medium_score
            else Severity.LOW
        )
        peer_cells = [c for p in scored.peers if (c := p.cell("unit_price")) is not None]
        peer_list = "; ".join(
            f"{p.item_code or '?'}: {fmt(p.unit_price)}" for p in scored.peers[:_PEER_CELLS_SHOWN]
        )
        more = len(scored.peers) - _PEER_CELLS_SHOWN
        if more > 0:
            peer_list += f" and {more} more"
        group = TIER_LABELS[scored.tier]
        impact = None
        currency = context.currency_evidence(table, row, ["unit_price", "line_total"])
        if currency and record.quantity is not None and record.discount_factor is not None:
            amount = multiply(
                multiply(record.quantity, subtract(price, reference)), record.discount_factor
            )
            impact = money_impact(
                RoundingSpec().apply(amount),
                currency,
                f"quantity × (unit price − median of {len(scored.peers)} {group})",
                reported=price,
                recomputed=reference,
                kind="reference_deviation",
            )
        own = record.cell("unit_price")
        return context.issues.create(
            self.spec,
            rule_id=RULE_ID,
            category=IssueCategory.STATISTICAL_OUTLIER,
            severity=severity,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=(
                f"Unit price {format_amount(price)} far {direction} comparable positions "
                f"(median {format_amount(reference)})"
            )[:200],
            explanation=(
                f"The unit price {format_amount(price)} of {record.item_code or 'this position'} "
                f"is {_compared(price, reference)} ({format_amount(reference)}, the median) of "
                f"{len(scored.peers)} {group}. Comparable work can be priced differently for "
                "good reasons, so this is a signal for review, not a confirmed error."
            ),
            table=table,
            row=row,
            cells=[own] if own is not None else [],
            inputs=[cell for member in (record, *scored.peers) for cell in member.cells.values()],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"Compared with {len(scored.peers)} {group}",
                    detail=peer_list,
                    cells=peer_cells[:_PEER_CELLS_SHOWN],
                    data={
                        "peer_group": scored.tier,
                        "peers": len(scored.peers),
                        "median": fmt(reference),
                        "lowest": fmt(min(p.unit_price for p in scored.peers if p.unit_price)),
                        "highest": fmt(max(p.unit_price for p in scored.peers if p.unit_price)),
                    },
                ),
            ],
            suggested_action=(
                "Compare the position's text, unit and price with the positions listed; correct "
                "the price if it is a slip, otherwise record why it differs."
            ),
            financial_impact=impact,
            anomaly_score=AnomalyScore(
                value=round(scored.score, 2),
                method=f"modified z-score of log unit price, {scored.tier} peer group",
                interpretation=(
                    "Robust scales between the log unit price and the median of the peers' "
                    "log prices (positive = more expensive)."
                ),
                threshold=config.flag_score,
            ),
        )


def _compared(price: Decimal, reference: Decimal) -> str:
    """The price against the typical price in words an estimator reads at a glance: "about 10
    times", "about 40 % above", "about 30 % below" or "about 10 % of" the typical price. Only
    words: the score in robust scales decides what is found."""
    ratio = price / reference
    if ratio >= 2:
        times = ratio.quantize(Decimal(1) if ratio >= 10 else Decimal("0.1"), ROUND_HALF_UP)
        return f"about {format_decimal(times.normalize())} times the typical price"
    if ratio >= 1:
        return f"about {_percent(ratio - 1)} % above the typical price"
    if ratio > Decimal("0.5"):
        return f"about {_percent(1 - ratio)} % below the typical price"
    if ratio < Decimal("0.01"):
        return "less than 1 % of the typical price"
    return f"about {_percent(ratio)} % of the typical price"


def _percent(share: Decimal) -> str:
    return format_decimal((share * 100).quantize(Decimal(1), ROUND_HALF_UP))


def _comparable(record: ItemRecord) -> bool:
    price = record.unit_price_per_base_unit
    return record.unit_id is not None and price is not None and price > 0


def _score_all(
    priced: Sequence[ItemRecord],
    similarity: np.ndarray,
    currencies: Sequence[str | None],
    config: PeerPriceConfig,
    result: DetectorResult,
) -> list[_Scored]:
    logs = np.array([math.log(float(r.unit_price_per_base_unit or 1)) for r in priced])
    units = np.array([r.unit_id or "" for r in priced], dtype=object)
    # One key per row (a list, not an array: numpy would split tuples into columns).
    sections = [(r.table_id, r.section_path[0]) if r.section_path else None for r in priced]
    # Only positions that count toward the total are peers; a contingency or alternative
    # position (Bedarfs- or Wahlposition) is compared with them but never compared against.
    counted = np.array([r.counts_toward_totals is not False for r in priced])
    out: list[_Scored] = []
    for i, record in enumerate(priced):
        same_unit = units == units[i]
        same_unit &= np.array([currency == currencies[i] for currency in currencies])
        same_unit &= counted
        same_unit[i] = False
        candidates = np.flatnonzero(same_unit)
        text = candidates[similarity[i, candidates] >= config.text_similarity]
        text = text[np.argsort(-similarity[i, text], kind="stable")][: config.max_text_peers]
        if len(text):  # the band, but never fewer than min_peers of the closest matches
            close = int(
                np.count_nonzero(similarity[i, text] >= similarity[i, text[0]] - config.text_band)
            )
            text = text[: max(close, config.min_peers)]
        section = np.array(
            [c for c in candidates if sections[i] is not None and sections[c] == sections[i]],
            dtype=np.intp,
        )
        for tier, peers in zip(TIERS, (text, section, candidates), strict=True):
            if tier not in config.peer_groups or len(peers) < config.min_peers:
                continue
            values = logs[peers]
            scale = max(robust_scale(values.tolist()) or 0.0, config.min_log_scale)
            score = (logs[i] - float(np.median(values))) / scale
            out.append(_Scored(record, tier, tuple(priced[p] for p in peers), score))
            result.count(ROWS_COMPARED)
            result.count(f"rows_compared_by_{tier}")
            break
        else:
            result.count(ROWS_WITHOUT_PEERS)
    return out


def _ratio(scored: _Scored) -> float:
    """How many times the row's unit price is above or below its group's median (>= 1)."""
    price = scored.record.unit_price_per_base_unit
    median = exact_median(
        [p.unit_price_per_base_unit for p in scored.peers if p.unit_price_per_base_unit]
    )
    if not price or not median:
        return math.inf
    ratio = float(price / median)
    return max(ratio, 1 / ratio)
