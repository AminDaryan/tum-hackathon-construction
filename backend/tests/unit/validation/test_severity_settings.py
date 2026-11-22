"""Severities that used to be fixed in detector code are profile-controlled settings now,
with the former values as defaults; a profile can change them, a plan cannot."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.core.errors import ProfileError
from app.models.issue import Severity
from app.models.profile import DomainProfile
from app.models.source import SourceKind
from app.validation.contracts.detector import Detector
from app.validation.deterministic.data_type_conformance import DataTypeConformanceDetector
from app.validation.deterministic.exact_duplicates import ExactDuplicatesDetector
from app.validation.deterministic.extraction_quality import ExtractionQualityDetector
from app.validation.deterministic.field_constraints import FieldConstraintsDetector
from app.validation.deterministic.formula_errors import FormulaErrorsDetector
from app.validation.deterministic.grand_total import GrandTotalDetector
from app.validation.deterministic.numeric_validity import NumericValidityDetector
from app.validation.deterministic.subtotal import SubtotalDetector
from app.validation.deterministic.unit_compatibility import (
    UnitCompatibilityDetector,
    UnitDescriptionRule,
)
from app.validation.profile_check import check_profiles, profile_problems
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import failed_number_cell, number_cell, unavailable_formula_cell
from tests.unit.validation.deterministic.references_fixtures import boq_dataset, run
from tests.unit.validation.deterministic.test_subtotal import build, item, section, subtotal

LOW, MEDIUM, HIGH, INFO = Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.INFO
FORMER_FIXED: list[tuple[type[Detector], dict[str, Severity]]] = [
    (
        DataTypeConformanceDetector,
        {
            "severity_invalid_value": MEDIUM,
            "severity_wrong_type": MEDIUM,
            "severity_ambiguous_value": MEDIUM,
            "severity_minority_type": LOW,
        },
    ),
    (ExactDuplicatesDetector, {"severity_exact_duplicate": MEDIUM}),
    (
        ExtractionQualityDetector,
        {
            "severity_low_confidence": LOW,
            "severity_very_low_confidence": MEDIUM,
            "severity_no_mapped_columns": MEDIUM,
            "severity_header_uncertain": MEDIUM,
            "severity_required_field_unmapped": MEDIUM,
            "severity_fuzzy_mapping": LOW,
            "severity_extraction_warning": MEDIUM,
        },
    ),
    (
        FieldConstraintsDetector,
        {"severity_pattern": LOW, "severity_allowed_values": MEDIUM, "severity_unique": MEDIUM},
    ),
    (
        NumericValidityDetector,
        {
            "severity_minimum": MEDIUM,
            "severity_maximum": MEDIUM,
            "severity_integer_only": LOW,
            "severity_max_decimal_places": LOW,
            "severity_zero": LOW,
        },
    ),
    (
        UnitCompatibilityDetector,
        {
            "severity_same_description_dimension": MEDIUM,
            "severity_fractional_count": LOW,
            "severity_lump_sum_quantity": LOW,
        },
    ),
    (
        FormulaErrorsDetector,
        {"severity_formula_result_unavailable": MEDIUM, "severity_external_reference": LOW},
    ),
    *[
        (
            detector,
            {
                "severity_undecided": MEDIUM,
                "severity_ambiguous_structure": MEDIUM,
                "severity_display_rounding": INFO,
            },
        )
        for detector in (SubtotalDetector, GrandTotalDetector)
    ],
]


@pytest.mark.parametrize(("detector", "defaults"), FORMER_FIXED)
def test_former_fixed_severities_are_profile_settings(
    detector: type[Detector], defaults: dict[str, Severity]
) -> None:
    config = detector.config_model()
    assert {name: getattr(config, name) for name in defaults} == defaults
    assert not set(defaults) & detector.config_model.plannable_parameters()


def test_only_plannable_severities_are_called_just_severity() -> None:
    """A profile entry ``severity`` means the same kind of setting in every check: the
    plannable one. Profile-only severities are named ``severity_<rule>``."""
    registry = DetectorRegistry.from_packages(Settings().detector_packages)
    plain, profile_only = [], []
    for detector_id in registry.ids():
        model = registry.get(detector_id).config_model
        for name, info in model.model_fields.items():
            if name == "severity":
                plain.append((detector_id, name in model.plannable_parameters()))
            elif info.annotation is Severity and name not in model.plannable_parameters():
                profile_only.append(name)
    assert plain and all(plannable for _, plannable in plain), plain
    assert profile_only and all(name.startswith("severity_") for name in profile_only)
    assert ExactDuplicatesDetector.config_model.plannable_parameters().isdisjoint(
        {"severity", "severity_exact_duplicate"}
    )


def test_a_profile_that_sets_the_former_duplicate_severity_name_is_rejected(
    boq_profile: DomainProfile,
) -> None:
    registry = DetectorRegistry.from_packages(Settings().detector_packages)
    exact = ExactDuplicatesDetector.spec.detector_id

    def with_duplicates(config: dict[str, Any]) -> DomainProfile:
        return boq_profile.evolve(
            detector_defaults={**boq_profile.detector_defaults, exact: config}
        )

    former = with_duplicates({"severity": "high"})
    assert profile_problems(former, registry) == [
        f"detector_defaults for {exact!r} are invalid (severity: Extra inputs are not permitted)"
    ]
    with pytest.raises(ProfileError, match="severity: Extra inputs are not permitted"):
        check_profiles([former], registry)
    renamed = with_duplicates({"severity_exact_duplicate": "high"})
    assert profile_problems(renamed, registry) == []
    check_profiles([renamed], registry)


def test_description_rules_carry_their_own_severity() -> None:
    rule = UnitDescriptionRule(
        rule_id="earthworks",
        description_pattern="aushub",
        allowed_dimensions=("volume",),
        rationale="Excavation is measured by volume.",
    )
    assert rule.severity is MEDIUM
    assert rule.evolve(severity=HIGH).severity is HIGH


ROW = ["01.0010", "Aushub Baugrube", "10", "m3", "12.50", "125.00"]


def _severities(
    detector: type[Detector],
    profile: DomainProfile,
    rows: list[list[Any]],
    setting: str,
    rule: str,
) -> tuple[set[Severity], set[Severity]]:
    dataset = boq_dataset(profile, rows)

    def found(overrides: dict[str, Any]) -> set[Severity]:
        issues = run(detector, dataset, profile, overrides).issues
        return {issue.severity for issue in issues if issue.rule_id == rule}

    return found({}), found({setting: "critical"})


@pytest.mark.parametrize(
    ("detector", "rows", "setting", "rule", "former"),
    [
        (
            ExactDuplicatesDetector,
            [ROW, ROW],
            "severity_exact_duplicate",
            "exact_duplicate",
            MEDIUM,
        ),
        (
            DataTypeConformanceDetector,
            [[*ROW[:2], failed_number_cell("viel"), *ROW[3:]]],
            "severity_invalid_value",
            "invalid_value",
            MEDIUM,
        ),
        (
            FieldConstraintsDetector,
            [ROW, ["01.0010", "Beton", "2", "m3", "3.00", "6.00"]],
            "severity_unique",
            "unique",
            MEDIUM,
        ),
        (
            UnitCompatibilityDetector,
            [["01.0010", "Baustelle einrichten und räumen", "2", "psch", "100", "200"]],
            "severity_lump_sum_quantity",
            "lump_sum_quantity",
            LOW,
        ),
        (
            FormulaErrorsDetector,
            [[*ROW[:5], unavailable_formula_cell()]],
            "severity_formula_result_unavailable",
            "formula_result_unavailable",
            MEDIUM,
        ),
        (
            ExtractionQualityDetector,
            [[*ROW[:2], number_cell("10", confidence=0.3), *ROW[3:]]],
            "severity_very_low_confidence",
            "low_confidence",
            MEDIUM,
        ),
        (
            ExtractionQualityDetector,
            [[*ROW[:2], number_cell("10", confidence=0.6), *ROW[3:]]],
            "severity_low_confidence",
            "low_confidence",
            LOW,
        ),
    ],
)
def test_a_profile_can_change_a_former_fixed_severity(
    boq_profile: DomainProfile,
    detector: type[Detector],
    rows: list[list[Any]],
    setting: str,
    rule: str,
    former: Severity,
) -> None:
    before, after = _severities(detector, boq_profile, rows, setting, rule)
    assert before == {former}
    assert after == {Severity.CRITICAL}


def test_numeric_constraint_severities(boq_profile: DomainProfile) -> None:
    rows = [[*ROW[:2], "-5", *ROW[3:]]]
    constraints = {"constraints": {"quantity": {"minimum": "0"}}}
    dataset = boq_dataset(boq_profile, rows)
    [before] = run(NumericValidityDetector, dataset, boq_profile, constraints).issues
    changed = {**constraints, "severity_minimum": "high"}
    [after] = run(NumericValidityDetector, dataset, boq_profile, changed).issues
    assert (before.rule_id, before.severity, after.severity) == ("minimum", MEDIUM, HIGH)
    assert before.fingerprint == after.fingerprint  # identity does not depend on severity


def test_totals_severities(boq_profile: DomainProfile) -> None:
    printed = [item(f"01.{i:04d}", "16.67") for i in range(6)]
    dataset = build(boq_profile, section("01"), *printed, subtotal("100.00", "01"))
    table = dataset.tables[0]
    csv = dataset.evolve(
        tables=[table.evolve(source=table.source.evolve(kind=SourceKind.DELIMITED_TEXT))]
    )
    for overrides, expected in (({}, INFO), ({"severity_display_rounding": "low"}, LOW)):
        [issue] = run(SubtotalDetector, csv, boq_profile, overrides).issues
        assert (issue.rule_id, issue.severity) == ("subtotal_display_rounding", expected)
