"""deterministic.numeric_validity: bounds, whole numbers, decimal places and zero."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.models.values import ValueMarker
from app.validation.deterministic.numeric_validity import (
    NumericValidityConfig,
    NumericValidityDetector,
    decimal_places,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, ambiguous_cell, marker_cell, unit_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    by_rule,
    resolve,
    run,
)

DETECTOR = NumericValidityDetector
STRICT_QUANTITY: dict[str, Any] = {
    "constraints": {
        "quantity": {
            "minimum": "0",
            "maximum": "1000",
            "integer_only": True,
            "max_decimal_places": 2,
            "allow_zero": False,
        }
    }
}


def _item(quantity: object, unit_price: object = "40.00", code: str = "01") -> list[object]:
    return [code, "Aushub", quantity, unit_cell("m3", "m3"), unit_price, "480.00"]


def test_the_boq_profile_sets_no_numeric_rules(boq_profile: DomainProfile) -> None:
    """Negative quantities and prices (credits, deductions) are not errors in a BoQ."""
    dataset = boq_dataset(boq_profile, [_item("-3", "-40.00")])
    verdict = applicability(DETECTOR, dataset, boq_profile)
    assert not verdict.applicable
    assert "constraints" in verdict.reasons[0]


def test_clean_values_pass(boq_profile: DomainProfile) -> None:
    result = run(DETECTOR, boq_dataset(boq_profile, [_item("12")]), boq_profile, STRICT_QUANTITY)
    assert result.issues == []
    assert result.coverage["cells_checked"] == 1
    assert result.coverage["rows_consistent"] == 1


def test_each_failed_constraint_is_one_finding(boq_profile: DomainProfile) -> None:
    rows = [
        _item("-3", code="01"),
        _item("1500", code="02"),
        _item("2.5", code="03"),
        _item("1.234", code="04"),
        _item("0", code="05"),
    ]
    dataset = boq_dataset(boq_profile, rows)
    result = run(DETECTOR, dataset, boq_profile, STRICT_QUANTITY)
    table = dataset.tables[0]
    found = [
        (table.row(i.row_id).position, i.rule_id, i.severity)  # type: ignore[union-attr]
        for i in result.issues
    ]
    assert found == [
        (0, "minimum", Severity.MEDIUM),
        (1, "maximum", Severity.MEDIUM),
        (2, "integer_only", Severity.LOW),
        (3, "integer_only", Severity.LOW),
        (3, "max_decimal_places", Severity.LOW),
        (4, "zero", Severity.LOW),
    ]
    assert result.coverage["rows_inconsistent"] == 5
    for issue in result.issues:
        assert issue.issue_category is IssueCategory.NUMERIC_VALUE
        assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
        assert len(issue.affected_cells) == 1
    assert_well_formed(result.issues)
    assert_unique_fingerprints(result.issues)

    [minimum] = by_rule(result.issues, "minimum")
    assert minimum.title == "Quantity -3 must be at least 0"
    assert minimum.observed_value == "-3"
    assert minimum.expected_value == ">= 0"
    assert "settings for this detector" in minimum.explanation
    rule = minimum.evidence[0]
    assert rule.kind is EvidenceKind.RULE
    assert rule.data["constraint"] == "minimum"


def test_exclusive_bounds_reject_the_boundary(boq_profile: DomainProfile) -> None:
    bounds = {"minimum": "0", "maximum": "100"}
    rows = [_item("1", "0", code="01"), _item("1", "100", code="02"), _item("1", "50", code="03")]
    inclusive = run(
        DETECTOR,
        boq_dataset(boq_profile, rows),
        boq_profile,
        {"constraints": {"unit_price": bounds}},
    )
    assert inclusive.issues == []
    exclusive = {**bounds, "exclusive_minimum": True, "exclusive_maximum": True}
    result = run(
        DETECTOR,
        boq_dataset(boq_profile, rows),
        boq_profile,
        {"constraints": {"unit_price": exclusive}},
    )
    assert [(i.rule_id, i.expected_value) for i in result.issues] == [
        ("minimum", "> 0"),
        ("maximum", "< 100"),
    ]
    assert result.issues[0].title == "Unit price 0 must be greater than 0"


def test_decimal_places_use_the_normalized_value(boq_profile: DomainProfile) -> None:
    assert decimal_places(Decimal("12.50")) == 1
    assert decimal_places(Decimal("12.505")) == 3
    assert decimal_places(Decimal("100")) == 0
    assert decimal_places(Decimal("1E+3")) == 0
    assert decimal_places(Decimal("-0.010")) == 2
    rows = [_item("1", "12.50", code="01"), _item("1", "12.505", code="02")]
    result = run(
        DETECTOR,
        boq_dataset(boq_profile, rows),
        boq_profile,
        {"constraints": {"unit_price": {"max_decimal_places": 1}}},
    )
    [issue] = result.issues
    assert issue.observed_value == "12.505"
    assert issue.title == "Unit price 12.505 must have at most 1 decimal place"


def test_empty_marker_and_unusable_cells_are_skipped(boq_profile: DomainProfile) -> None:
    rows = [
        _item(None, code="01"),
        _item(marker_cell("entfällt", ValueMarker.NOT_APPLICABLE), code="02"),
        _item(ambiguous_cell("1.234"), code="03"),
    ]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, STRICT_QUANTITY)
    assert result.issues == []
    assert result.coverage["rows_skipped_missing_inputs"] == 1
    assert result.coverage["rows_skipped_marker"] == 1
    assert result.coverage["rows_skipped_unusable_inputs"] == 1
    assert "cells_checked" not in result.coverage


def test_only_included_item_rows_are_checked(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(_item("-3", code="01"), excluded=True)
    table.row([None, "Summe Titel 01", "-3", None, None, "10.00"], kind=RowKind.SUBTOTAL)
    table.row(_item("5", code="02"))
    result = run(DETECTOR, builder.build(), boq_profile, STRICT_QUANTITY)
    assert result.issues == []
    assert result.coverage["cells_checked"] == 1


def test_fields_limit_the_check(boq_profile: DomainProfile) -> None:
    overrides = {
        "fields": ["unit_price"],
        "constraints": {
            "quantity": {"minimum": "0"},
            "unit_price": {"minimum": "0"},
        },
    }
    rows = [_item("-3", "-40.00")]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, overrides)
    assert [i.title for i in result.issues] == ["Unit price -40.00 must be at least 0"]


def test_constraints_on_a_text_field_are_ignored(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [_item("1")])
    overrides = {"constraints": {"description": {"minimum": "0"}}}
    assert not applicability(DETECTOR, dataset, boq_profile, overrides).applicable


def test_config_validation_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)
    assert config.fields is None and config.constraints == {}
    assert NumericValidityConfig.plannable_parameters() == {"fields"}
    for bad in (
        {"unknown": 1},
        {"fields": ["Not An Id"]},
        {"constraints": {"Not An Id": {"minimum": "0"}}},
        {"constraints": {"quantity": {"minimum": "zero"}}},
        {"constraints": {"quantity": {"max_decimal_places": -1}}},
    ):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    assert (
        "deterministic.numeric_validity"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_stable(boq_profile: DomainProfile) -> None:
    rows = [_item("-3", code="01"), _item("1.234", code="02")]
    first = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, STRICT_QUANTITY)
    second = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, STRICT_QUANTITY)
    assert len(first.issues) == 3
    assert [i.fingerprint for i in first.issues] == [i.fingerprint for i in second.issues]
