"""statistical.rate_consistency: identical positions with different unit prices."""

from __future__ import annotations

from decimal import Decimal

from app.models.issue import EvidenceClass, Severity
from app.validation.statistical.rate_consistency import (
    ROWS_COMPARED,
    ROWS_WITHOUT_IDENTICAL,
    RULE_ID,
    RateConsistencyDetector,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    boq_dataset,
    run,
)

COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]
WALL = "Mauerwerk Kalksandstein 24 cm"


def item(code, text, qty, unit, price):
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total), "EUR"]


def test_the_one_copy_priced_unlike_the_others_is_reported_with_its_slip(boq_profile) -> None:
    rows = [item(f"{n}.1", WALL, "120", "m2", "45.80") for n in (1, 2, 3)]
    rows.append(item("4.1", WALL, "200", "m2", "54.80"))  # 45.80 with two digits swapped
    found = run(
        RateConsistencyDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    )
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.evidence_class == EvidenceClass.SUSPECTED_ANOMALY
    assert issue.severity == Severity.LOW  # +19.7 %
    assert [c.source.row_number for c in issue.affected_cells] == [5]  # only the odd one
    assert "two swapped adjacent digits" in issue.explanation
    assert issue.anomaly_score is not None and not issue.anomaly_score.calibrated
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.kind == "reference_deviation"
    assert (impact.amount, impact.recomputed) == (Decimal("1800.00"), Decimal("45.80"))  # 200 × 9
    assert_well_formed(found.issues)


def test_two_copies_are_reported_once_with_both_prices(boq_profile) -> None:
    rows = [
        item("1.1", WALL, "10", "m2", "45.80"),
        item("2.1", WALL, "300", "m2", "458.00"),  # a factor of 10, the larger amount at stake
    ]
    [issue] = run(
        RateConsistencyDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    ).issues
    assert issue.severity == Severity.HIGH
    assert sorted(c.source.row_number for c in issue.affected_cells) == [2, 3]
    assert "a factor of 10" in issue.explanation
    assert issue.estimated_financial_impact.amount == Decimal("123660.00")  # 300 × 412.20


def test_agreeing_prices_and_other_work_raise_nothing_but_are_counted(boq_profile) -> None:
    rows = [
        item("1.1", WALL, "120", "m2", "45.80"),
        item("2.1", WALL, "80", "m2", "46.00"),  # 0.4 %: within the tolerance
        item("3.1", "Mauerwerk Kalksandstein 36,5 cm", "50", "m2", "62.00"),  # other text
        item("4.1", WALL, "5", "m", "12.00"),  # other unit
    ]
    found = run(
        RateConsistencyDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    )
    assert found.issues == []
    assert found.coverage[ROWS_COMPARED] == 2
    assert found.coverage[ROWS_WITHOUT_IDENTICAL] == 2
