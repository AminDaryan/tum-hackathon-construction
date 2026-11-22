"""Positions measured in another dimension than their most similar positions (plan check U1,
``semantic.unit_fit``).

For each item row with a text and a unit whose dimension is one of ``compared_dimensions``
(length, area and volume by default), the most similar positions of the bill with a known
unit are taken from the shared text index (:mod:`app.validation.support.similar`): at most
``max_neighbours`` positions whose text similarity reaches ``min_similarity``. The row is
reported when at least ``min_agreeing`` of them, and at least ``min_share`` of all of them, are
measured in one other compared dimension (area against length, volume against area), while at
most ``max_same_dimension`` share the row's own dimension. Pieces against metres (a pipe and
its bends), hire per week against pieces, or tonnes against cubic metres are measured
differently on purpose too often to be compared by default. A row measured
like any of its close neighbours is never reported, so each of several identical positions
that agree with one another is left alone.

Every finding is a ``semantic_warning``: similar wording does not prove the same work, and
the same work is sometimes measured in another unit for good reasons, so a reviewer decides.
No amount is stated: what the row would cost in the neighbours' unit needs a conversion (a
thickness, a width) that the bill does not give.
"""

from __future__ import annotations

from collections import Counter
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
from app.validation.deterministic._support import fmt
from app.validation.support.items import ItemRecord, item_frame
from app.validation.support.similar import text_index

RULE_ID = "unit_dimension_unlike_similar_positions"
ROWS_COMPARED = "rows_compared"
ROWS_WITHOUT_NEIGHBOURS = "rows_without_similar_positions"
ROWS_NOT_COMPARED = "rows_not_compared"  # no text, or a unit outside compared_dimensions


class UnitFitConfig(DetectorConfig):
    min_similarity: float = Field(
        default=0.6, gt=0, lt=1, description="Cosine text similarity a neighbour needs."
    )
    max_neighbours: int = Field(
        default=5, ge=2, le=50, description="Most similar positions compared with."
    )
    min_agreeing: int = Field(
        default=2,
        ge=1,
        le=50,
        description="Neighbours that must share the other dimension.",
    )
    min_share: float = Field(
        default=0.75,
        gt=0,
        le=1,
        description="Share of the neighbours that must share the other dimension.",
    )
    max_same_dimension: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Neighbours in the row's own dimension that still allow a finding.",
    )
    compared_dimensions: list[str] = Field(
        default_factory=lambda: ["length", "area", "volume"],
        description=(
            "Dimensions a finding may name, for the row and for its neighbours. Others (pieces "
            "against metres, hire per week against pieces, tonnes against cubic metres) are "
            "often measured differently on purpose; their rows still count as neighbours."
        ),
    )
    medium_similarity: float = Field(
        default=0.85,
        gt=0,
        le=1,
        description="Mean similarity of the agreeing neighbours for medium severity.",
    )


@dataclass(frozen=True, slots=True)
class _Misfit:
    record: ItemRecord
    neighbours: tuple[tuple[ItemRecord, float], ...]  # most similar first
    other_dimension: str
    agreeing: int
    same: int
    mean_similarity: float  # of the agreeing neighbours


class UnitFitDetector(Detector[UnitFitConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="semantic.unit_fit",
        name="Unit unlike similar positions",
        version="1.0.0",
        category=DetectorCategory.SEMANTIC,
        description=(
            "Compares the dimension of each position's unit (length, area, volume) "
            "with that of its most similar positions by text, and reports a position whose "
            "close neighbours agree on another dimension while none shares its own."
        ),
        required_fields=("unit",),
        optional_fields=("description", "long_description", "item_code", "quantity"),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map a unit and a description (bills of quantities).",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(IssueCategory.UNIT,),
        limitations=(
            "Compares positions within one bill only.",
            "Similar wording does not prove the same work; the same work can be measured in "
            "another unit for good reasons (a strip in m, a surface in m²).",
            "Units outside the profile's vocabulary have no dimension and are not compared.",
            "The score is uncalibrated: a mean text similarity, not a probability of error.",
        ),
        references=(
            "ADR 0010: U1, similar positions measured in another dimension (m² against m)",
        ),
        cost="medium",
    )
    config_model = UnitFitConfig

    def applicability(self, context: ValidationContext, config: UnitFitConfig) -> Applicability:
        unit_field = context.unit_field_id()
        tables = [
            t.name
            for t in context.tables()
            if unit_field
            and context.has_fields(t, "unit_price", unit_field)
            and context.has_fields(t, "description")
        ]
        if not tables:
            return Applicability.no("No priced table maps both a unit and a description.")
        return Applicability.yes(f"Units and descriptions are mapped in: {', '.join(tables)}.")

    def validate(self, context: ValidationContext, config: UnitFitConfig) -> DetectorResult:
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
        config: UnitFitConfig,
        table: Table,
        row: Row,
        misfit: _Misfit,
    ) -> ValidationIssue:
        record = misfit.record
        code = record.item_code or "this position"
        listed = "; ".join(
            f"{n.item_code or '?'} ({n.unit_id}, similarity {s:.2f}): {_short(n.description)}"
            for n, s in misfit.neighbours
        )
        unit_cells = [c for n, _ in misfit.neighbours if (c := n.cell("unit")) is not None]
        own = record.cell("unit")
        severity = (
            Severity.MEDIUM if misfit.mean_similarity >= config.medium_similarity else Severity.LOW
        )
        return context.issues.create(
            self.spec,
            rule_id=RULE_ID,
            category=IssueCategory.UNIT,
            severity=severity,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=(
                f"Unit {record.unit_id} ({record.dimension}) unlike similar positions measured "
                f"in {misfit.other_dimension}"
            )[:200],
            explanation=(
                f"{code} is measured in {record.unit_id} ({record.dimension}), but "
                f"{misfit.agreeing} of its {len(misfit.neighbours)} most similar positions "
                f"(mean text similarity {misfit.mean_similarity:.2f}) are measured in "
                f"{misfit.other_dimension} and {_none_or(misfit.same)} in "
                f"{record.dimension}. A unit of the wrong dimension makes the quantity and the "
                "line total meaningless; similar positions can also be measured differently "
                "for good reasons, so this is a signal for review, not a confirmed error."
            ),
            table=table,
            row=row,
            cells=[own] if own is not None else [],
            inputs=[
                cell
                for member in (record, *(n for n, _ in misfit.neighbours))
                for cell in member.cells.values()
            ],
            observed_value=record.unit_id,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"Compared with the {len(misfit.neighbours)} most similar positions",
                    detail=listed,
                    cells=unit_cells,
                    data={
                        "unit": record.unit_id,
                        "dimension": record.dimension,
                        "quantity": fmt(record.quantity),
                        "other_dimension": misfit.other_dimension,
                        "neighbours": len(misfit.neighbours),
                        "agreeing": misfit.agreeing,
                        "same_dimension": misfit.same,
                    },
                ),
            ],
            suggested_action=(
                "Check whether the unit fits the work described and the positions listed; if "
                "it is a slip, correct the unit and check the quantity measured in it."
            ),
            anomaly_score=AnomalyScore(
                value=round(misfit.mean_similarity, 2),
                method="mean cosine text similarity of the neighbours in the other dimension",
                interpretation=(
                    "How alike the texts of the positions measured in the other dimension are "
                    "(1 = identical wording)."
                ),
                threshold=config.min_similarity,
            ),
        )


def _misfits(
    records: Sequence[ItemRecord],
    similarity: np.ndarray,
    config: UnitFitConfig,
    result: DetectorResult,
) -> list[_Misfit]:
    compared = set(config.compared_dimensions)
    usable = np.array([r.dimension is not None and bool(r.description) for r in records])
    out: list[_Misfit] = []
    for i, record in enumerate(records):
        if not usable[i] or record.dimension not in compared:
            result.count(ROWS_NOT_COMPARED)
            continue
        candidates = np.flatnonzero(usable & (similarity[i] >= config.min_similarity))
        candidates = candidates[candidates != i]
        candidates = candidates[np.argsort(-similarity[i, candidates], kind="stable")]
        candidates = candidates[: config.max_neighbours]
        if len(candidates) < config.min_agreeing:
            result.count(ROWS_WITHOUT_NEIGHBOURS)
            continue
        result.count(ROWS_COMPARED)
        dimensions = Counter(records[c].dimension for c in candidates)
        same = dimensions.pop(record.dimension, 0)
        if not dimensions or same > config.max_same_dimension:
            continue
        other, agreeing = dimensions.most_common(1)[0]
        if other is None or other not in compared or agreeing < config.min_agreeing:
            continue
        if agreeing / len(candidates) < config.min_share:
            continue
        mean = float(
            np.mean([similarity[i, c] for c in candidates if records[c].dimension == other])
        )
        neighbours = tuple((records[c], float(similarity[i, c])) for c in candidates)
        out.append(_Misfit(record, neighbours, other, agreeing, same, mean))
    return out


def _short(text: str | None, limit: int = 60) -> str:
    if not text:
        return "(no text)"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _none_or(count: int) -> str:
    return "none" if count == 0 else str(count)
