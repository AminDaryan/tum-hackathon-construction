"""The evidence policy for signals: a suspected anomaly or a finding that needs external context
computed from an unverified cell (a scored OCR/PDF value below the confidence threshold) is
extraction uncertainty with a downgrade note; other signals carry the caveats that confirmed
findings carry. Verbatim spreadsheet cells are verified, so nothing changes for them."""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.core.clock import FixedClock
from app.core.ids import SequentialIdFactory
from app.models.dataset import CellRef, Dataset
from app.models.issue import (
    AnomalyScore,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import DomainProfile
from app.models.source import SourceKind, SourceLocation
from app.models.values import ParseStatus
from app.validation.contracts.detector import DetectorCategory, DetectorSpec
from app.validation.contracts.issue_factory import SIGNAL_CLASSES, IssueFactory, is_verified
from tests.support.builders import DatasetBuilder, number_cell

EVIDENCE = [EvidenceItem(kind=EvidenceKind.NOTE, label="Test", detail="Test evidence.")]
SPEC = DetectorSpec(
    detector_id="test.signal",
    name="Signal",
    version="1.0.0",
    category=DetectorCategory.STATISTICAL,
    description="test detector",
    applicability="always",
    evidence_classes=(
        EvidenceClass.SUSPECTED_ANOMALY,
        EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
        EvidenceClass.EXTRACTION_UNCERTAINTY,
    ),
    issue_categories=(IssueCategory.STATISTICAL_OUTLIER,),
)
SIGNALS = [EvidenceClass.SUSPECTED_ANOMALY, EvidenceClass.NEEDS_EXTERNAL_CONTEXT]


def _dataset(profile: DomainProfile, price: object, quantity: object = "2") -> Dataset:
    builder = DatasetBuilder(profile)
    builder.table("Scan", [("Qty", "quantity"), ("Rate", "unit_price")]).row([quantity, price])
    return builder.build()


def _factory(dataset: Dataset, review: dict[str | None, list[str]] | None = None) -> IssueFactory:
    return IssueFactory(
        dataset=dataset,
        document_id="doc",
        run_id="run_1",
        ids=SequentialIdFactory(),
        clock=FixedClock(),
        low_confidence_threshold=0.9,
        review_tables=review,
    )


def _refs(dataset: Dataset) -> tuple[CellRef, CellRef]:
    factory = _factory(dataset)
    table = dataset.tables[0]
    row = table.rows[0]
    quantity = table.column_for_field("quantity")
    price = table.column_for_field("unit_price")
    assert quantity is not None and price is not None
    return factory.cell_ref(table, row, quantity.column_id), factory.cell_ref(
        table, row, price.column_id
    )


def _signal(
    factory: IssueFactory,
    dataset: Dataset,
    evidence_class: EvidenceClass,
    *,
    as_input: bool = False,
    score: AnomalyScore | None = None,
) -> ValidationIssue:
    quantity, price = _refs(dataset)
    table = dataset.tables[0]
    return factory.create(
        SPEC,
        rule_id="price_outlier",
        category=IssueCategory.STATISTICAL_OUTLIER,
        severity=Severity.MEDIUM,
        evidence_class=evidence_class,
        title="Unit price stands out",
        explanation="Test signal.",
        evidence=EVIDENCE,
        table=table,
        row=table.rows[0],
        cells=[quantity] if as_input else [price],
        inputs=[price] if as_input else [],
        anomaly_score=score,
    )


def _labels(issue: ValidationIssue) -> list[str]:
    return [item.label for item in issue.evidence]


def test_the_signal_classes() -> None:
    assert frozenset(SIGNALS) == SIGNAL_CLASSES


@pytest.mark.parametrize("evidence_class", SIGNALS)
def test_a_signal_on_a_cell_below_the_threshold_is_extraction_uncertainty(
    boq_profile: DomainProfile, evidence_class: EvidenceClass
) -> None:
    dataset = _dataset(boq_profile, number_cell("4580.00", confidence=0.55))
    score = AnomalyScore(
        value=8.2, method="robust z", interpretation="robust scales from the group median"
    )
    issue = _signal(_factory(dataset), dataset, evidence_class, score=score)
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert issue.extraction_confidence == 0.55
    assert issue.anomaly_score == score  # the signal's score is kept, as it was computed
    assert _labels(issue) == ["Test", "Evidence downgraded"]
    note = issue.evidence[-1]
    assert note.data == {
        "unverified_cells": 1,
        "min_extraction_confidence": 0.55,
        "threshold": 0.9,
    }
    assert note.detail == (
        "The check found an unusual value, but some of the values it used were not extracted "
        "reliably (sheet 'Scan' cell B2). Verify them in the source document first: the "
        "difference may come from the extraction."
    )


def test_input_cells_count_too(boq_profile: DomainProfile) -> None:
    dataset = _dataset(boq_profile, number_cell("4580.00", confidence=0.4))
    issue = _signal(_factory(dataset), dataset, EvidenceClass.SUSPECTED_ANOMALY, as_input=True)
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert issue.evidence[-1].data["unverified_cells"] == 1


def test_many_unverified_cells_are_summarized(boq_profile: DomainProfile) -> None:
    dataset = _dataset(
        boq_profile, number_cell("4580.00", confidence=0.4), number_cell("2", confidence=0.3)
    )
    issue = _signal(_factory(dataset), dataset, EvidenceClass.SUSPECTED_ANOMALY, as_input=True)
    note = issue.evidence[-1]
    assert note.data["unverified_cells"] == 2
    assert note.data["min_extraction_confidence"] == 0.3
    assert "(sheet 'Scan' cell A2, sheet 'Scan' cell B2)" in note.detail


@pytest.mark.parametrize("evidence_class", SIGNALS)
def test_a_signal_on_cells_at_or_above_the_threshold_keeps_its_class(
    boq_profile: DomainProfile, evidence_class: EvidenceClass
) -> None:
    dataset = _dataset(boq_profile, number_cell("4580.00", confidence=0.9))
    issue = _signal(_factory(dataset), dataset, evidence_class)
    assert issue.evidence_class is evidence_class
    assert issue.extraction_confidence == 0.9
    assert _labels(issue) == ["Test"]


@pytest.mark.parametrize("evidence_class", SIGNALS)
def test_verbatim_spreadsheet_cells_change_nothing(
    boq_profile: DomainProfile, evidence_class: EvidenceClass
) -> None:
    dataset = _dataset(boq_profile, "4580.00")
    issue = _signal(_factory(dataset), dataset, evidence_class)
    assert issue.evidence_class is evidence_class
    assert issue.extraction_confidence is None
    assert _labels(issue) == ["Test"]


def test_signals_carry_the_caveats(boq_profile: DomainProfile) -> None:
    inferred = number_cell(
        "4580.00",
        raw="4.580,00",
        status=ParseStatus.INFERRED,
        note="Decimal comma inferred from the other values in this column.",
    )
    dataset = _dataset(boq_profile, inferred)
    table_id = dataset.tables[0].table_id
    factory = _factory(dataset, review={table_id: ["header_uncertain"]})
    issue = _signal(factory, dataset, EvidenceClass.NEEDS_EXTERNAL_CONTEXT)
    assert issue.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
    assert _labels(issue) == ["Test", "Number format inferred", "Extraction needs review"]
    assert issue.evidence[1].detail == (
        "1 input value(s) were read using inferred formatting: "
        "Decimal comma inferred from the other values in this column."
    )
    assert "(header_uncertain)" in issue.evidence[2].detail


def test_a_downgraded_signal_gets_no_caveats(boq_profile: DomainProfile) -> None:
    low = number_cell("4580.00", confidence=0.5, status=ParseStatus.INFERRED, note="Inferred.")
    dataset = _dataset(boq_profile, low)
    factory = _factory(dataset, review={None: ["header_uncertain"]})
    issue = _signal(factory, dataset, EvidenceClass.SUSPECTED_ANOMALY)
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert _labels(issue) == ["Test", "Evidence downgraded"]  # as for confirmed violations


def test_extraction_uncertainty_itself_is_unchanged(boq_profile: DomainProfile) -> None:
    dataset = _dataset(boq_profile, number_cell("4580.00", confidence=0.5))
    issue = _signal(_factory(dataset), dataset, EvidenceClass.EXTRACTION_UNCERTAINTY)
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert _labels(issue) == ["Test"]


class TestIsVerified:
    SCAN: ClassVar[SourceLocation] = SourceLocation(kind=SourceKind.OCR, page_number=1)

    def test_verbatim_digital_cells(self) -> None:
        assert is_verified(number_cell("1"), 0.9)

    def test_scored_cells_need_the_threshold(self) -> None:
        assert is_verified(number_cell("1", confidence=0.9), 0.9)
        assert not is_verified(number_cell("1", confidence=0.89), 0.9)
        assert is_verified(number_cell("1", confidence=0.89), 0.5)

    def test_cells_of_scored_sources_without_a_score_are_unverified(self) -> None:
        unscored = number_cell("1").evolve(source=self.SCAN)
        assert not is_verified(unscored, 0.0)
        scored = number_cell("1", confidence=0.95).evolve(source=self.SCAN)
        assert is_verified(scored, 0.9)
        pdf_text = number_cell("1").evolve(source=SourceLocation(kind=SourceKind.PDF_TEXT))
        assert not is_verified(pdf_text, 0.9)
