"""semantic.unit_fit: positions measured in another dimension than their most similar ones."""

from __future__ import annotations

from decimal import Decimal

from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory
from app.validation.semantic.unit_fit import RULE_ID, UnitFitDetector
from tests.unit.validation.deterministic.references_fixtures import (
    assert_well_formed,
    boq_dataset,
    run,
)


def item(code, text, unit, qty="20", price="30.00"):
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total)]


SCREED = "Zementestrich CT-C25-F4 auf Trennlage, Dicke {} mm, liefern und einbauen"


def test_a_position_measured_in_m_among_similar_ones_in_m2_is_reported(boq_profile) -> None:
    rows = [item(f"01.{n}0", SCREED.format(d), "m2") for n, d in enumerate([40, 45, 50, 55], 1)]
    rows.append(item("01.50", SCREED.format(60), "m"))  # unit of another dimension
    found = run(UnitFitDetector, boq_dataset(boq_profile, rows), boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.issue_category == IssueCategory.UNIT
    assert issue.evidence_class == EvidenceClass.SEMANTIC_WARNING  # a signal, never confirmed
    assert issue.affected_cells[0].source.row_number == 6
    assert issue.estimated_financial_impact is None  # no conversion between the units given
    [comparison] = issue.evidence
    assert comparison.kind == EvidenceKind.COMPARISON
    assert comparison.data["other_dimension"] == "area" and comparison.data["agreeing"] == 4
    assert "01.10 (m2" in comparison.detail and len(comparison.cells) == 4  # the units shown
    assert issue.anomaly_score is not None and not issue.anomaly_score.calibrated
    assert_well_formed(found.issues)


def test_mixed_units_among_similar_positions_and_counted_fittings_raise_nothing(
    boq_profile,
) -> None:
    rows = [
        # Similar texts in both m and m2: no agreement against either.
        item("01.10", SCREED.format(40), "m2"),
        item("01.20", SCREED.format(45), "m2"),
        item("01.30", SCREED.format(50), "m"),
        item("01.40", SCREED.format(55), "m"),
        # A pipe in m beside its fittings in pieces: counts are not compared with lengths.
        item("02.10", "Druckrohr PE100 DN 150 liefern und verlegen", "m"),
        item("02.20", "Druckrohr PE100 DN 150, Bogen 45 Grad, liefern und verlegen", "St"),
        item("02.30", "Druckrohr PE100 DN 150, Bogen 30 Grad, liefern und verlegen", "St"),
        item("02.40", "Druckrohr PE100 DN 150, Bogen 15 Grad, liefern und verlegen", "St"),
    ]
    found = run(UnitFitDetector, boq_dataset(boq_profile, rows), boq_profile)
    assert found.issues == []
