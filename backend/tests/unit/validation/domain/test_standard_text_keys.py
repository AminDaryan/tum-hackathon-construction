"""domain.standard_text_keys: items that name the same STLB-Bau / StLB standard text.

The keys are synthetic (made up for these tests); real ones come from GAEB files."""

from __future__ import annotations

from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.standard_text_keys import (
    NOT_IN_CATALOGUE_NOTE,
    ROWS_PRICE_NOT_COMPARED,
    ROWS_UNIT_NOT_COMPARED,
    ROWS_WITH_KEY,
    RULE_PRICES,
    RULE_UNITS,
    RULE_VERSIONS,
    StandardTextKeysDetector,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    by_rule,
    run,
    run_pipeline,
)

DETECTOR = StandardTextKeysDetector
KEYS = [("Standardtext", "standard_text_key"), ("Katalog", "standard_text_catalog")]
COLUMNS = [*BOQ_COLUMNS, *KEYS]
KEY = "STLB-Bau 2021-04 LB 012 G 310: 100-0-1 200-0-3"
CATALOGUE = "STLB-Bau 2021-04"


def item(code, unit, price, key=KEY, catalogue=CATALOGUE):
    return [code, "Mauerwerk", "2", unit, price, None, key, catalogue]


def result(profile, rows, columns=COLUMNS):
    return run(DETECTOR, boq_dataset(profile, rows, columns=columns), profile)


def test_same_key_in_different_units_warns(boq_profile) -> None:
    spaced = KEY.replace(" G ", "  G ")  # keys are compared with whitespace collapsed
    found = result(boq_profile, [item("1.1", "m2", "10.00"), item("1.2", "m", "10.00", spaced)])
    [issue] = found.issues
    assert issue.rule_id == RULE_UNITS
    assert (issue.evidence_class, issue.severity) == (
        EvidenceClass.SEMANTIC_WARNING,
        Severity.MEDIUM,
    )
    assert "m2: 'LV' row 2" in issue.explanation and "m: 'LV' row 3" in issue.explanation
    assert {c.source.a1 for c in issue.affected_cells} == {"D2", "D3"}
    assert NOT_IN_CATALOGUE_NOTE in found.notes
    assert_well_formed(found.issues)


def test_same_key_and_unit_with_different_prices_is_a_signal(boq_profile) -> None:
    rows = [item("1.1", "m2", "10.00"), item("1.2", "m2", "12.50"), item("1.3", "m2", "10.00")]
    [issue] = result(boq_profile, rows).issues
    assert issue.rule_id == RULE_PRICES
    assert (issue.evidence_class, issue.severity) == (EvidenceClass.SUSPECTED_ANOMALY, Severity.LOW)
    assert issue.anomaly_score is None  # no probability is claimed
    assert "range from 10.00 to 12.50" in issue.explanation
    assert issue.affected_cells[0].source.a1 == "E3"  # the rarest price first


def test_consistent_keys_from_one_catalogue_report_nothing(boq_profile) -> None:
    found = result(boq_profile, [item("1.1", "m2", "10.00"), item("1.2", "qm", "10.0")])
    assert found.issues == []
    assert found.coverage[ROWS_WITH_KEY] == 2


def test_unknown_units_and_missing_prices_are_counted_not_compared(boq_profile) -> None:
    rows = [item("1.1", "xyz", "10.00"), item("1.2", "m2", None), item("1.3", "m2", "11.00")]
    found = result(boq_profile, rows)
    assert found.issues == []
    assert found.coverage[ROWS_UNIT_NOT_COMPARED] == 1
    assert found.coverage[ROWS_PRICE_NOT_COMPARED] == 1


def test_prices_in_different_currencies_are_not_compared(boq_profile) -> None:
    columns = [*COLUMNS, ("Währung", "currency")]
    rows = [[*item("1.1", "m2", "10.00"), "EUR"], [*item("1.2", "m2", "12.00"), "CHF"]]
    assert result(boq_profile, rows, columns).issues == []


def test_keys_from_several_catalogues_need_external_context(boq_profile) -> None:
    rows = [item("1.1", "m2", None), item("1.2", "m", None, "StLB 9300201123000202", "StLB")]
    [issue] = by_rule(result(boq_profile, rows).issues, RULE_VERSIONS)
    assert issue.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
    assert issue.severity is Severity.INFO
    assert "STLB-Bau 2021-04 (1 item row); StLB (1 item row)" in issue.explanation
    assert {c.source.a1 for c in issue.affected_cells} == {"H2", "H3"}


def test_not_applicable_without_a_key_column(boq_profile) -> None:
    dataset = boq_dataset(boq_profile, [["1.1", "Mauerwerk", "2", "m2", "10.00", "20.00"]])
    assert not applicability(DETECTOR, dataset, boq_profile).applicable


def test_findings_pass_the_pipeline_evidence_policy(boq_profile) -> None:
    rows = [
        item("1.1", "m2", "10.00"),
        item("1.2", "m", "10.00"),
        item("1.3", "m2", "12.00"),
        item("1.4", "m2", "10.00", "StLB 9300201123000202", "StLB"),
    ]
    outcome = run_pipeline(DETECTOR, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile)
    assert sorted(i.rule_id for i in outcome.issues) == sorted(
        [RULE_UNITS, RULE_PRICES, RULE_VERSIONS]
    )
    assert_unique_fingerprints(outcome.issues)
    assert_well_formed(outcome.issues)
