"""statistical.quantity_factor: a quantity a power of ten off its identical positions."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.issue import EvidenceClass, Severity
from app.validation.statistical.quantity_factor import (
    ROWS_COMPARED,
    ROWS_WITHOUT_IDENTICAL,
    RULE_ID,
    QuantityFactorDetector,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    boq_dataset,
    run,
)

COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]
PIPE = "Grundleitung PVC-U DN 200 liefern und verlegen"


def item(code, text, qty, unit, price):
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total), "EUR"]


def test_a_length_entered_in_centimetres_is_found_and_named(boq_profile) -> None:
    rows = [
        item("1.1", PIPE, "12.40", "m", "39.55"),
        item("2.1", PIPE, "13.10", "m", "39.55"),
        item("3.1", PIPE, "1180", "m", "39.55"),  # 11.80 m entered in cm
    ]
    found = run(
        QuantityFactorDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    )
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.evidence_class == EvidenceClass.SUSPECTED_ANOMALY
    assert issue.severity == Severity.HIGH
    assert [c.source.row_number for c in issue.affected_cells] == [4]
    assert "entered in cm" in issue.explanation
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.kind == "reference_deviation"
    # (1180 − median 12.75 of the others) × 39.55
    assert (impact.amount, impact.recomputed) == (Decimal("46164.74"), Decimal("12.75"))
    assert found.coverage[ROWS_COMPARED] == 3
    assert_well_formed(found.issues)


def test_ordinary_differences_and_small_counts_raise_nothing(boq_profile) -> None:
    rows = [
        item("1.1", PIPE, "12.40", "m", "39.55"),
        item("2.1", PIPE, "52.00", "m", "39.55"),  # 4.2 times: legitimately larger
        item("3.1", "Feuerschutztür T30", "1", "Stk.", "1600.00"),
        item("4.1", "Feuerschutztür T30", "10", "Stk.", "1600.00"),  # 1 and 10 doors
        item("5.1", "Baustelleneinrichtung", "1", "psch", "9000.00"),
    ]
    found = run(
        QuantityFactorDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    )
    assert found.issues == []
    assert found.coverage[ROWS_COMPARED] == 4
    assert found.coverage[ROWS_WITHOUT_IDENTICAL] == 1


@pytest.mark.parametrize("quantities", [("2", "20"), ("2", "2", "20")])
@pytest.mark.parametrize("unit", ["m", "m2", "m3", "kg", "h"])
def test_small_whole_measures_are_not_exempt_as_piece_counts(boq_profile, quantities, unit) -> None:
    rows = [item(f"1.{i}", PIPE, qty, unit, "39.55") for i, qty in enumerate(quantities)]
    found = run(
        QuantityFactorDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    )
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.evidence[0].data["reference_quantity"] == "2"
    assert "Quantity 20" in issue.title
    assert [c.source.row_number for c in issue.affected_cells] == (
        [3, 2] if len(quantities) == 2 else [4]
    )


@pytest.mark.parametrize("quantities", [("2", "20"), ("2", "2", "20")])
def test_small_piece_counts_still_abstain(boq_profile, quantities) -> None:
    rows = [
        item(f"1.{i}", "Feuerschutztür T30", qty, "Stk.", "1600")
        for i, qty in enumerate(quantities)
    ]
    found = run(
        QuantityFactorDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    )
    assert found.issues == []
