"""statistical.open_price_reference: unit prices below a published material value."""

from __future__ import annotations

from decimal import Decimal

from app.models.issue import EvidenceClass, Severity
from app.validation.statistical.open_price_reference import (
    ROWS_AMBIGUOUS,
    ROWS_COMPARED,
    ROWS_CURRENCY,
    ROWS_SCOPE_EXCLUDED,
    ROWS_UNIT_MISMATCH,
    ROWS_WITHOUT_REFERENCE,
    RULE_ID,
    OpenPriceReferenceDetector,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    boq_dataset,
    run,
)

COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]


def item(code, text, qty, unit, price, currency="EUR"):
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total), currency]


def _run(boq_profile, rows):
    dataset = boq_dataset(boq_profile, rows, columns=COLUMNS)
    return run(OpenPriceReferenceDetector, dataset, boq_profile)


def test_a_tonne_price_below_the_german_rebar_value_is_context_not_an_error(
    boq_profile,
) -> None:
    # 300 EUR/t = 0.300 EUR/kg; DE 2025: 896,914,000 EUR / 1,892,501,000 kg = 0.474 EUR/kg.
    # 600 EUR/t = 0.600 EUR/kg is above it and raises nothing.
    found = _run(
        boq_profile,
        [
            item("1.1", "Betonstahl B500B liefern und verlegen", "12", "t", "300.00"),
            item("1.2", "Betonstahl B500B liefern und verlegen", "12", "t", "600.00"),
        ],
    )
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.evidence_class == EvidenceClass.NEEDS_EXTERNAL_CONTEXT
    assert issue.severity == Severity.LOW
    assert issue.estimated_financial_impact is None  # no amount at stake from an average
    assert issue.evidence[0].data["reference_value"] == "0.474"
    assert issue.evidence[0].data["position_value"] == "0.300"
    assert issue.evidence[0].data["area"] == "DE"
    assert "not what this position should cost" in issue.explanation
    assert found.coverage[ROWS_COMPARED] == 2
    assert_well_formed(found.issues)


def test_a_confidential_german_value_falls_back_to_the_labelled_eu_average(
    boq_profile,
) -> None:
    # I-sections: German figures confidential; EU-27 1.2e9 EUR / 2.1e9 kg = 0.571 EUR/kg.
    [issue] = _run(boq_profile, [item("2.1", "Träger IPE 200 S235", "500", "kg", "0.50")]).issues
    assert issue.evidence[0].data["area"] == "EU27_2020"
    assert issue.evidence[0].data["reference_value"] == "0.571"
    assert "EU-27" in issue.title and "not adjusted to Germany" in issue.explanation


def test_rows_that_cannot_be_compared_are_counted_by_reason(boq_profile) -> None:
    found = _run(
        boq_profile,
        [
            item("3.1", "Betonstahl ausbauen und entsorgen", "2", "t", "50.00"),  # scope
            item("3.2", "Isolierglas 2-fach", "10", "pcs", "20.00"),  # unit: piece, not m2
            item("3.3", "Gipskartonplatte 12,5 mm", "100", "m2", "1.00", currency="USD"),
            item("3.4", "VSG und ESG Verglasung", "10", "m2", "1.00"),  # two materials
            item("3.5", "Oberboden abtragen", "50", "m3", "1.00"),  # no material named
        ],
    )
    assert found.issues == []
    for key in (
        ROWS_SCOPE_EXCLUDED,
        ROWS_UNIT_MISMATCH,
        ROWS_CURRENCY,
        ROWS_AMBIGUOUS,
        ROWS_WITHOUT_REFERENCE,
    ):
        assert found.coverage[key] == 1, key
