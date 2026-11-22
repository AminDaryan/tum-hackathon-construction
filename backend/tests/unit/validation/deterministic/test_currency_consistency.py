"""deterministic.currency_consistency: explicit currency markers that disagree."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import Dataset
from app.models.issue import EvidenceClass, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.validation.contracts.detector import DetectorResult
from app.validation.deterministic.currency_consistency import (
    RULE_MINORITY,
    RULE_ROW_CONFLICT,
    RULE_UNEXPECTED,
    CurrencyConsistencyConfig,
    CurrencyConsistencyDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import make_context, number_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    resolve,
    run,
)

DETECTOR = CurrencyConsistencyDetector
WITH_CURRENCY = [*BOQ_COLUMNS, ("Währung", "currency")]


def item(code: str, price: Any, total: Any, *extra: Any) -> list[Any]:
    return [code, "Position", "1", None, price, total, *extra]


def money(value: str, currency: str | None, **options: Any) -> Any:
    return number_cell(value, currency=currency, **options)


def header_currency(dataset: Dataset, field_id: str, code: str) -> Dataset:
    table = dataset.tables[0]
    columns = [
        column.evolve(header_currency=code) if column.mapped_semantic_field == field_id else column
        for column in table.columns
    ]
    return dataset.evolve(tables=[table.evolve(columns=columns)])


def check(
    profile: DomainProfile, rows: list[list[Any]], overrides: Any = None, **options: Any
) -> DetectorResult:
    return run(DETECTOR, boq_dataset(profile, rows, **options), profile, overrides)


def test_unmarked_amounts_produce_nothing(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [item("01", "10.00", "10.00"), item("02", "5.00", "5.00")])
    assert not applicability(DETECTOR, dataset, boq_profile).applicable
    config = resolve(DETECTOR, boq_profile, {"expected_currency": "EUR"})
    result = DETECTOR().validate(make_context(dataset, boq_profile), config)
    assert result.issues == []
    assert result.coverage["cells_without_currency"] == 4


def test_a_row_whose_amounts_disagree(boq_profile: DomainProfile) -> None:
    rows = [item("01", money("10.00", "EUR"), money("10.00", "USD"))]
    result = check(boq_profile, rows)
    [issue] = result.issues
    assert issue.rule_id == RULE_ROW_CONFLICT
    assert issue.issue_category is IssueCategory.CURRENCY
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.MEDIUM
    assert issue.title == "Amounts in row 2 are marked EUR and USD"
    assert len(issue.affected_cells) == 2
    assert issue.evidence[0].data["currencies"] == "EUR, USD"
    assert result.coverage["cells_with_explicit_currency"] == 2
    assert_well_formed([issue])


def test_a_cell_against_its_header_or_currency_column(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [item("01", "10.00", money("10.00", "CHF"))])
    [issue] = run(DETECTOR, header_currency(dataset, "line_total", "EUR"), boq_profile).issues
    assert issue.rule_id == RULE_ROW_CONFLICT and "header 'GP'" in issue.explanation
    rows = [item("01", money("10.00", "EUR"), "10.00", "USD")]
    [issue] = check(boq_profile, rows, columns=WITH_CURRENCY).issues
    assert issue.rule_id == RULE_ROW_CONFLICT and "currency column" in issue.explanation


def test_markers_other_than_the_expected_currency(boq_profile: DomainProfile) -> None:
    rows = [
        item("01", "10.00", money("10.00", "EUR")),
        item("02", "10.00", money("10.00", "USD")),
        item("03", "10.00", money("20.00", "USD")),
    ]
    [issue] = check(boq_profile, rows, {"expected_currency": "EUR"}).issues
    assert issue.rule_id == RULE_UNEXPECTED
    assert issue.title == "2 Line total values are marked USD, not EUR"
    assert issue.row_id is None and len(issue.affected_cells) == 2
    assert check(boq_profile, rows[:1], {"expected_currency": "EUR"}).issues == []
    # A header marker: one finding for the column.
    dataset = header_currency(boq_dataset(boq_profile, rows[:1] * 1), "unit_price", "GBP")
    found = run(DETECTOR, dataset, boq_profile, {"expected_currency": "EUR"}).issues
    assert [i.rule_id for i in found] == [RULE_ROW_CONFLICT, RULE_UNEXPECTED]
    assert found[1].evidence[0].data["marked_by"] == "header"


def test_a_minority_currency_needs_context(boq_profile: DomainProfile) -> None:
    rows = [item(f"0{i}", money("10.00", "EUR"), money("10.00", "EUR")) for i in range(1, 4)]
    rows.append(item("04", money("10.00", "USD"), money("10.00", "USD")))
    [issue] = check(boq_profile, rows).issues
    assert issue.rule_id == RULE_MINORITY
    assert issue.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
    assert issue.title == "2 amounts are marked USD; the rest of the table is in EUR"
    assert issue.evidence[0].data["majority"] == "EUR"
    # A tie goes to the currency seen first.
    tie = [rows[0], rows[3]]
    [issue] = check(boq_profile, tie).issues
    assert issue.title.endswith("in EUR")


def test_conflicts_are_not_repeated_as_minorities(boq_profile: DomainProfile) -> None:
    rows = [
        item("01", money("10.00", "EUR"), money("10.00", "EUR")),
        item("02", money("10.00", "EUR"), money("10.00", "USD")),
    ]
    assert [i.rule_id for i in check(boq_profile, rows).issues] == [RULE_ROW_CONFLICT]


def test_a_currency_column_makes_mixed_rows_legitimate(boq_profile: DomainProfile) -> None:
    rows = [
        item("01", money("10.00", "EUR"), "10.00", "EUR"),
        item("02", money("10.00", "USD"), "10.00", "USD"),
        item("03", "10.00", "10.00", "Euronen"),
    ]
    result = check(boq_profile, rows, columns=WITH_CURRENCY)
    assert result.issues == []
    assert result.coverage["currency_cells_unreadable"] == 1
    assert result.coverage["cells_with_explicit_currency"] == 4


def test_low_confidence_cells_downgrade_the_conflict(boq_profile: DomainProfile) -> None:
    rows = [item("01", money("10.00", "EUR"), money("10.00", "USD", confidence=0.5))]
    [issue] = check(boq_profile, rows).issues
    assert issue.effective_evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY


def test_config_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)
    assert config.expected_currency is None and config.severity is Severity.MEDIUM
    assert CurrencyConsistencyConfig.plannable_parameters() == {
        "fields",
        "currency_field",
        "severity",
        "max_cells_per_issue",
    }
    for bad in ({"unknown": 1}, {"expected_currency": "eur"}, {"expected_currency": "EURO"}):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    assert (
        "deterministic.currency_consistency"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [
        item("01", money("10.00", "EUR"), money("10.00", "USD")),
        item("02", money("10.00", "CHF"), money("10.00", "CHF")),
    ]
    first = check(boq_profile, rows, {"expected_currency": "EUR"}).issues
    second = check(boq_profile, rows, {"expected_currency": "EUR"}).issues
    # The conflict; then per column and currency: USD in GP, CHF in EP, CHF in GP.
    assert sorted(i.rule_id for i in first) == [RULE_ROW_CONFLICT] + [RULE_UNEXPECTED] * 3
    assert_unique_fingerprints(first)
    assert [i.fingerprint for i in first] == [i.fingerprint for i in second]
