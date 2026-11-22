"""deterministic.subtotal: how each scope outcome is reported (scopes: test_scopes.py)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import Dataset, RowKind
from app.models.finding_category import FindingCategory
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.models.source import SourceKind
from app.validation.deterministic.subtotal import SubtotalConfig, SubtotalDetector
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, ambiguous_cell, number_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    resolve,
    run,
)

DETECTOR = SubtotalDetector
RowSpec = tuple[list[Any], dict[str, Any]]


def item(code: str, amount: Any, **options: Any) -> RowSpec:
    return [code, "Position", None, None, None, amount], options


def section(code: str, level: int = 1) -> RowSpec:
    values = [code, f"Titel {code}", None, None, None, None]
    return values, {"kind": RowKind.SECTION, "level": level, "code": code}


def subtotal(amount: Any, code: str | None = None) -> RowSpec:
    values = [None, f"Summe {code or ''}", None, None, None, amount]
    return values, {"kind": RowKind.SUBTOTAL, "code": code}


def build(profile: DomainProfile, *rows: RowSpec) -> Dataset:
    builder = DatasetBuilder(profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for values, options in rows:
        table.row(values, **options)
    return builder.build()


def test_a_consistent_nested_bill(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        section("01.01", level=2),
        item("01.01.0010", "5252.10"),
        item("01.01.0020", "7030.00"),
        subtotal("12282.10", "01.01"),
        section("01.02", level=2),
        item("01.02.0010", "3840.00"),
        item("01.02.0020", "1500.00", in_totals=None),  # Bedarfsposition
        item("01.02.0030", None, in_totals=False),  # "nur EP"
        subtotal("3840.00", "01.02"),
        subtotal("16122.10", "01"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["totals_checked"] == 3 and result.coverage["totals_consistent"] == 3
    assert any("not counted in this total" in note for note in result.notes)


def test_a_mismatch_is_a_confirmed_violation(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100.00"),
        item("01.0020", "50.00"),
        subtotal("149.00", "01"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = result.issues
    assert issue.rule_id == "subtotal_mismatch"
    assert issue.issue_category is IssueCategory.SUBTOTAL
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.HIGH
    assert issue.title == "Subtotal 149.00 does not match the sum of its items (150.00)"
    calculation = issue.evidence[0].calculation
    assert calculation is not None and calculation.operation == "sum"
    assert calculation.terms == 2 and calculation.difference == Decimal("-1.00")
    assert issue.evidence[1].kind is EvidenceKind.REFERENCE
    assert len(issue.input_cells) == 2
    assert issue.estimated_financial_impact is None  # no explicit currency
    assert result.coverage["totals_inconsistent"] == 1
    assert_well_formed(result.issues)


def test_financial_impact_with_an_explicit_currency(boq_profile: DomainProfile) -> None:
    eur = {"currency": "EUR"}
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", number_cell("100.00", **eur)),
        subtotal(number_cell("90.00", **eur), "01"),
    )
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.amount == Decimal("-10.00") and impact.currency == "EUR"


def test_an_undecided_reading_is_reported_as_a_note(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100.00"),
        item("01.0020", "30.00", in_totals=None),
        subtotal("130.00", "01"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert any("with the undecided item in row" in note for note in result.notes)


def test_two_structural_readings_that_both_fail(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        item("01.0010", "100"),
        item("01.0020", "50"),
        item("02.0010", "30"),
        subtotal("999", "01"),
    )
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.rule_id == "subtotal_scope_ambiguous"
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert issue.finding_category is None  # about reading the file
    assert issue.severity is Severity.MEDIUM


def test_too_many_undecided_items_need_external_context(boq_profile: DomainProfile) -> None:
    undecided = [item(f"01.{i:04d}", str(2**i), in_totals=None) for i in range(13)]
    dataset = build(boq_profile, section("01"), *undecided, subtotal("3", "01"))
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = result.issues
    assert issue.rule_id == "subtotal_undecided"
    assert issue.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
    assert result.coverage["totals_undecided"] == 1


def test_display_rounding_in_delimited_text(boq_profile: DomainProfile) -> None:
    printed = [item(f"01.{i:04d}", "16.67") for i in range(6)]
    dataset = build(boq_profile, section("01"), *printed, subtotal("100.00", "01"))
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.rule_id == "subtotal_mismatch"  # a spreadsheet: no drift allowance
    assert issue.finding_category is FindingCategory.ERROR
    table = dataset.tables[0]
    csv = dataset.evolve(
        tables=[table.evolve(source=table.source.evolve(kind=SourceKind.DELIMITED_TEXT))]
    )
    [issue] = run(DETECTOR, csv, boq_profile).issues
    assert issue.rule_id == "subtotal_display_rounding"
    assert issue.finding_category is None  # about reading the file
    assert issue.severity is Severity.INFO
    assert "rounding of 6 printed values" in issue.explanation


def test_abstentions_are_counted_and_noted(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        subtotal("10.00"),  # nothing before it
        section("01"),
        item("01.0010", ambiguous_cell("1.234")),
        subtotal("1.23", "01"),
        section("02"),
        item("02.0010", "5.00"),
        subtotal(None, "02"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["totals_skipped_no_scope"] == 1
    assert result.coverage["totals_skipped_incomplete_scope"] == 1
    assert result.coverage["totals_skipped_missing_amount"] == 1
    assert any("could not be read" in note for note in result.notes)


def test_low_confidence_members_downgrade_the_finding(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", number_cell("100.00", confidence=0.5)),
        subtotal("90.00", "01"),
    )
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.effective_evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY


def test_config_applicability_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)  # the boq.yaml defaults validate
    assert config.tolerance.absolute == Decimal("0.01")
    assert SubtotalConfig.plannable_parameters() == {
        "total_field",
        "severity",
        "max_reference_cells",
    }
    for bad in ({"unknown": 1}, {"display_rounding_drift_per_term": "2"}):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    no_subtotals = build(boq_profile, item("01", "1.00"))
    assert not applicability(DETECTOR, no_subtotals, boq_profile).applicable
    assert (
        "deterministic.subtotal"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [
        section("01"),
        item("01.0010", "1.00"),
        subtotal("2.00", "01"),
        section("02"),
        item("02.0010", "1.00"),
        subtotal("3.00", "02"),
    ]
    first = run(DETECTOR, build(boq_profile, *rows), boq_profile).issues
    second = run(DETECTOR, build(boq_profile, *rows), boq_profile).issues
    assert len(first) == 2
    assert_unique_fingerprints(first)
    assert [i.fingerprint for i in first] == [i.fingerprint for i in second]
