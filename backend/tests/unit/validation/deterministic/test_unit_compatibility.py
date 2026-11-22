"""deterministic.unit_compatibility: advisory unit checks (description rules, whole-number
units, lump sums, identical descriptions in different dimensions)."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from app.core.errors import DetectorConfigError
from app.models.issue import EvidenceClass, EvidenceKind, Severity
from app.models.run import DetectorExecutionStatus
from app.models.values import ValueMarker
from app.validation.contracts.conditions import Coverage
from app.validation.deterministic.unit_compatibility import (
    UnitCompatibilityDetector,
    description_key,
    is_fractional,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, marker_cell, number_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    LARGE_ROWS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    by_rule,
    large_boq_dataset,
    resolve,
    run,
    run_pipeline,
)

DETECTOR = UnitCompatibilityDetector
HOURLY = "hourly_work_in_time_units"
SITE_SETUP = "site_setup_lump_sum_or_time"
# The description-rule tests switch the other checks off, so each test sees one rule.
ONLY_RULES = {"check_integer_quantities": False, "check_lump_sum_quantity": False,
              "check_same_description_dimension": False}  # fmt: skip
ONLY_QUANTITIES = {"description_rules": [], "check_same_description_dimension": False}


def row(description, unit, quantity="1", code="1"):
    return [code, description, quantity, unit, "10.00", "10.00"]


def warnings(profile, rows, overrides=None):
    return run(DETECTOR, boq_dataset(profile, rows), profile, overrides).issues


class TestDescriptionRules:
    def test_hourly_work_in_cubic_metres_warns(self, boq_profile) -> None:
        dataset = boq_dataset(boq_profile, [row("Stundenlohnarbeiten Facharbeiter", "m³", "8")])
        result = run(DETECTOR, dataset, boq_profile, ONLY_RULES)
        [issue] = result.issues
        assert issue.rule_id == HOURLY
        assert issue.evidence_class is EvidenceClass.SEMANTIC_WARNING
        assert issue.severity is Severity.MEDIUM
        assert issue.title == (
            "'Stundenlohnarbeiten' is usually measured in time, lump sum or ratio units, not "
            "in m³ (volume)"
        )
        assert "per unit of time" in issue.explanation  # the rule's rationale
        assert "'LV' row 2" in issue.explanation
        assert issue.affected_cells[0].source.a1 == "D2"
        assert issue.input_cells[0].source.a1 == "B2"
        assert issue.evidence[0].data["matched_text"] == "Stundenlohnarbeiten"
        assert_well_formed(result.issues)

    def test_site_setup_measured_by_area_warns(self, boq_profile) -> None:
        [issue] = warnings(boq_profile, [row("Baustelleneinrichtung", "qm")], ONLY_RULES)
        assert issue.rule_id == SITE_SETUP
        assert "not in qm (area)" in issue.title

    @pytest.mark.parametrize(
        ("description", "unit"),
        [
            ("Daywork labour", "h"),
            ("Stundenlohnarbeiten Helfer", "Std"),
            ("Regiestunden Polier", "psch"),
            ("Zuschlag auf Stundenlohnarbeiten", "%"),
            ("Baustelleneinrichtung", "psch"),
            ("Baustelleneinrichtung vorhalten", "Wo"),
            ("Baustelleneinrichtung, Bauzaun aufstellen und vorhalten", "m"),  # anchored rule
            ("Site set-up complete", "item"),
            ("Mauerwerk aus Kalksandstein", "m²"),
        ],
    )
    def test_compatible_or_unrelated_items_pass(self, boq_profile, description, unit) -> None:
        assert warnings(boq_profile, [row(description, unit)], ONLY_RULES) == []

    def test_exclude_pattern_stops_the_rule(self, boq_profile) -> None:
        rows = [row("Stoffe für Stundenlohnarbeiten", "kg", "12")]
        assert warnings(boq_profile, rows, ONLY_RULES) == []
        without_exclude = {
            **ONLY_RULES,
            "description_rules": [
                {
                    "rule_id": "hourly",
                    "description_pattern": r"\bstundenlohnarbeiten\b",
                    "allowed_dimensions": ["time"],
                    "rationale": "Hourly work is priced per hour.",
                }
            ],
        }
        [issue] = warnings(boq_profile, rows, without_exclude)
        assert issue.rule_id == "hourly"

    def test_english_daywork_in_square_metres_warns(self, boq_profile) -> None:
        [issue] = warnings(
            boq_profile, [row("Daywork: labour hours, bricklayer", "m2")], ONLY_RULES
        )
        assert issue.rule_id == HOURLY and "not in m2 (area)" in issue.title

    def test_long_descriptions_are_bounded(self, boq_profile) -> None:
        long_text = "Mauerwerk " * 20_000 + "Stundenlohnarbeiten"
        hostile = "Stundenlohnarbeiten" + " " + "x" * 100_000
        dataset = boq_dataset(boq_profile, [row(long_text, "m3"), row(hostile, "m3")])
        started = time.perf_counter()
        result = run(DETECTOR, dataset, boq_profile, ONLY_RULES)
        assert time.perf_counter() - started < 1.0
        assert [i.input_cells[0].source.row_number for i in result.issues] == [3]
        assert result.coverage["texts_truncated"] == 2
        assert any("pattern window" in note for note in result.notes)

    def test_rule_dimensions_unknown_to_the_profile_are_noted(self, boq_profile) -> None:
        overrides = {
            **ONLY_RULES,
            "description_rules": [
                {
                    "rule_id": "odd",
                    "description_pattern": r"\bmauerwerk\b",
                    "allowed_dimensions": ["area", "speed"],
                    "rationale": "Test.",
                }
            ],
        }
        result = run(DETECTOR, boq_dataset(boq_profile, [row("Mauerwerk", "m²")]), boq_profile,
                     overrides)  # fmt: skip
        assert result.issues == []
        assert any("speed" in note for note in result.notes)


class TestQuantities:
    def test_fractional_pieces_warn(self, boq_profile) -> None:
        rows = [row("Tür einbauen", "Stk.", "2.5"), row("Fenster", "pcs", "-1.5", code="2")]
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, ONLY_QUANTITIES)
        first, second = result.issues
        assert first.rule_id == "fractional_count"
        assert first.evidence_class is EvidenceClass.SEMANTIC_WARNING
        assert first.severity is Severity.LOW
        assert first.title == ("Fractional Quantity 2.5 in a unit counted in whole numbers (Stk.)")
        assert first.affected_cells[0].source.a1 == "C2"
        assert first.input_cells[0].source.a1 == "D2"
        assert second.observed_value == "-1.5"
        assert result.coverage["quantities_checked"] == 2
        assert_well_formed(result.issues)

    @pytest.mark.parametrize("quantity", ["3", "3.00", "0", "-2", "1E+3"])
    def test_whole_numbers_pass(self, boq_profile, quantity) -> None:
        assert warnings(boq_profile, [row("Tür", "St", quantity)], ONLY_QUANTITIES) == []

    def test_unit_multiplier_counts_single_pieces(self, boq_profile) -> None:
        rows = [row("Schrauben", "100 St", "2.5"), row("Dübel", "100 St", "2.555", code="2")]
        [issue] = warnings(boq_profile, rows, ONLY_QUANTITIES)
        assert issue.observed_value == "255.500"
        calculation = next(e for e in issue.evidence if e.kind is EvidenceKind.CALCULATION)
        assert calculation.calculation.exact_result == Decimal("255.500")
        assert [o.value for o in calculation.calculation.operands] == [
            Decimal("2.555"),
            Decimal(100),
        ]

    def test_markers_and_percentages_are_not_quantities(self, boq_profile) -> None:
        rows = [
            row("Tür", "Stk", marker_cell("psch", ValueMarker.LUMP_SUM)),
            row("Tür", "Stk", number_cell("0.5", percent=True), code="2"),
            row("Tür", "Stk", None, code="3"),
        ]
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, ONLY_QUANTITIES)
        assert result.issues == []
        assert result.coverage["quantities_skipped_marker"] == 1
        assert result.coverage["quantities_skipped_percent"] == 1
        assert result.coverage["quantities_skipped_missing"] == 1

    def test_lump_sum_with_a_quantity_other_than_one(self, boq_profile) -> None:
        rows = [
            row("Baustelleneinrichtung", "psch", "3"),
            row("Baustelle räumen", "psch", "1", code="2"),
            row("Gutschrift Baustrom", "pauschal", "-1", code="3"),
            row("Prüfung", "LS", "1.00", code="4"),
            row("Wasserhaltung", "psch", marker_cell("psch", ValueMarker.LUMP_SUM), code="5"),
        ]
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, ONLY_QUANTITIES)
        [issue] = result.issues
        assert issue.rule_id == "lump_sum_quantity"
        assert issue.title == "Lump-sum item (psch) with Quantity 3"
        assert issue.expected_value == "1"
        assert result.coverage["quantities_skipped_marker"] == 1

    def test_switches_turn_the_quantity_checks_off(self, boq_profile) -> None:
        rows = [row("Tür", "Stk", "2.5"), row("Baustelle", "psch", "3", code="2")]
        overrides = {**ONLY_QUANTITIES, "check_integer_quantities": False}
        assert [i.rule_id for i in warnings(boq_profile, rows, overrides)] == ["lump_sum_quantity"]
        overrides = {**ONLY_QUANTITIES, "check_lump_sum_quantity": False}
        assert [i.rule_id for i in warnings(boq_profile, rows, overrides)] == ["fractional_count"]


class TestSameDescription:
    def test_identical_descriptions_in_area_and_count_warn_once(self, boq_profile) -> None:
        rows = [
            row("Mauerwerk KS 24 cm", "m²", "10", code="1"),
            row("Mauerwerk  KS 24 cm ", "qm", "12", code="2"),
            row("MAUERWERK ks 24 cm", "Stk", "3", code="3"),
            row("Mauerwerk KS 24", "Stk", "3", code="4"),  # different text
        ]
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
        [issue] = by_rule(result.issues, "same_description_dimension")
        assert issue.evidence_class is EvidenceClass.SEMANTIC_WARNING
        assert issue.severity is Severity.MEDIUM
        assert issue.title == "Same Description measured in count and area: 'Mauerwerk KS 24 cm'"
        # the rarer dimension comes first
        assert [c.source.a1 for c in issue.affected_cells] == ["D4", "D2", "D3"]
        assert "count (Stk): 'LV' row 4; area (m², qm): 'LV' rows 2 and 3" in issue.explanation
        assert issue.evidence[0].data["rows_per_dimension"] == "count: 1; area: 2"
        assert result.coverage["description_groups_inconsistent"] == 1
        assert_well_formed(result.issues)

    def test_groups_span_tables(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("Los 1", BOQ_COLUMNS).row(row("Putz auf Mauerwerk", "m2", "9"))
        builder.table("Los 2", BOQ_COLUMNS).row(row("Putz auf Mauerwerk", "m", "9"))
        dataset = builder.build()
        [issue] = run(DETECTOR, dataset, boq_profile).issues
        tables = {t.table_id: t.name for t in dataset.tables}
        assert {tables[c.table_id] for c in issue.input_cells} == {"Los 1", "Los 2"}
        assert len({c.table_id for c in issue.affected_cells}) == 1

    def test_short_descriptions_and_one_dimension_do_not_warn(self, boq_profile) -> None:
        rows = [
            row("Tür", "Stk", "1", code="1"),
            row("Tür", "m²", "1", code="2"),  # one word: below min_description_words
            row("Fliesen im Bad", "m²", "4", code="3"),
            row("Fliesen im Bad", "qm", "5", code="4"),
        ]
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
        assert result.issues == []
        assert result.coverage["description_groups_compared"] == 1

    def test_relative_wording_can_be_excluded_by_the_profile(self, boq_profile) -> None:
        rows = [
            row("Mauerwerk 24 cm", "m²", "10", code="1"),
            row("wie vor, jedoch 30 cm", "m²", "10", code="2"),
            row("Sturz 24 cm", "Stk", "3", code="3"),
            row("wie vor, jedoch 30 cm", "Stk", "3", code="4"),
        ]
        # The BoQ profile excludes relative wording ...
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
        assert result.issues == []
        assert result.coverage["descriptions_not_grouped_excluded"] == 2
        # ... without the pattern the two "wie vor" rows are compared.
        defaults = dict(boq_profile.detector_defaults)
        defaults[DETECTOR.spec.detector_id] = {
            k: v
            for k, v in defaults[DETECTOR.spec.detector_id].items()
            if k != "same_description_exclude_pattern"
        }
        plain = boq_profile.evolve(detector_defaults=defaults)
        assert len(warnings(plain, rows)) == 1

    def test_description_key(self) -> None:
        assert description_key("  Mauerwerk KS  ２４ cm ") == "mauerwerk ks 24 cm"


class TestUnknownUnitsAndApplicability:
    def test_unknown_and_empty_units_are_ignored_by_every_rule(self, boq_profile) -> None:
        rows = [
            row("Stundenlohnarbeiten Facharbeiter", "VE", "2.5"),
            row("Stundenlohnarbeiten Facharbeiter", None, "2.5", code="2"),
            row("Stundenlohnarbeiten Facharbeiter", "m³", "2", code="3"),
        ]
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
        assert [i.rule_id for i in result.issues] == [HOURLY]
        assert result.coverage["rows_skipped_unknown_unit"] == 1
        assert result.coverage[Coverage.ROWS_SKIPPED_MISSING_INPUTS] == 1
        assert result.coverage[Coverage.ROWS_CHECKED] == 1

    def test_not_applicable_without_units_or_fields(self, boq_profile, generic_profile) -> None:
        builder = DatasetBuilder(generic_profile)
        builder.table("Data", [("Unit", None)]).row(["m"])
        verdict = applicability(DETECTOR, builder.build(), generic_profile)
        assert not verdict.applicable and "no unit vocabulary" in verdict.reasons[0]
        only_units = boq_dataset(boq_profile, [["1", "m"]], columns=[("Pos.", "item_code"),
                                                                     ("ME", "unit")])  # fmt: skip
        verdict = applicability(DETECTOR, only_units, boq_profile)
        assert not verdict.applicable and "description" in verdict.reasons[0]
        off = {
            "description_rules": [],
            "check_integer_quantities": False,
            "check_lump_sum_quantity": False,
            "check_same_description_dimension": False,
        }
        verdict = applicability(
            DETECTOR, boq_dataset(boq_profile, [row("a", "m")]), boq_profile, off
        )
        assert not verdict.applicable and "switched off" in verdict.reasons[0]

    def test_is_fractional(self) -> None:
        assert is_fractional(Decimal("2.5")) and is_fractional(Decimal("-0.001"))
        for whole in ("3", "3.000", "0", "0.000", "-0", "1E+3", "-12"):
            assert not is_fractional(Decimal(whole))


class TestConfig:
    def test_boq_defaults_are_accepted(self, boq_profile) -> None:
        registry = DetectorRegistry([DETECTOR])
        config = registry.resolve_config(
            DETECTOR.spec.detector_id,
            [boq_profile.detector_defaults.get(DETECTOR.spec.detector_id, {})],
        )
        assert [r.rule_id for r in config.description_rules] == [HOURLY, SITE_SETUP]
        assert config.description_rules[0].allowed_dimensions == ("time", "lump_sum", "ratio")
        assert registry.describe(DETECTOR.spec.detector_id).plannable_parameters == [
            "description_field",
            "max_cells_per_issue",
            "quantity_field",
            "unit_field",
        ]

    RULE = {"rule_id": "r", "description_pattern": r"\bx\b", "allowed_dimensions": ["time"],
            "rationale": "Because."}  # fmt: skip

    @pytest.mark.parametrize(
        "overrides",
        [
            {"unknown": 1},
            {"min_description_words": 0},
            {"unit_field": "Unit"},
            {"description_rules": [{**RULE, "allowed_dimensions": []}]},
            {"description_rules": [{**RULE, "allowed_dimensions": ["Time"]}]},
            {"description_rules": [{**RULE, "description_pattern": "(unclosed"}]},
            {"description_rules": [{**RULE, "exclude_pattern": "[z"}]},
            {"description_rules": [{**RULE, "description_pattern": ".*"}]},
            {"description_rules": [{**RULE, "rule_id": "fractional_count"}]},
            {"description_rules": [RULE, RULE]},
            {"description_rules": [{**RULE, "rationale": ""}]},
            {"description_rules": [{**RULE, "evidence_class": "confirmed_rule_violation"}]},
            {"same_description_exclude_pattern": "(open"},
            {"same_description_exclude_pattern": "x?"},
        ],
    )
    def test_invalid_parameters_are_rejected(self, boq_profile, overrides) -> None:
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, overrides)


class TestIdentityAndIntegration:
    def _dataset(self, profile, offset=0):
        builder = DatasetBuilder(profile)
        for _ in range(offset):
            builder.ids.new("row"), builder.ids.new("col"), builder.ids.new("tbl")
        table = builder.table("LV", BOQ_COLUMNS)
        table.row(row("Stundenlohnarbeiten Facharbeiter Rohbau", "m³", "2.5"))
        table.row(row("Stundenlohnarbeiten Facharbeiter Rohbau", "h", "2.5", code="2"))
        table.row(row("Tür einbauen komplett", "Stk", "2.5", code="3"))
        table.row(row("Baustelleneinrichtung", "psch", "2", code="4"))
        return builder.build()

    def test_fingerprints_are_stable_and_distinct(self, boq_profile) -> None:
        first = run(DETECTOR, self._dataset(boq_profile), boq_profile).issues
        shifted = run(DETECTOR, self._dataset(boq_profile, 4), boq_profile).issues
        assert sorted(i.rule_id for i in first) == [
            "fractional_count",
            HOURLY,
            "lump_sum_quantity",
            "same_description_dimension",
        ]
        assert [i.fingerprint for i in first] == [i.fingerprint for i in shifted]
        assert_unique_fingerprints(first)

    def test_discovered_in_the_deterministic_package(self) -> None:
        registry = DetectorRegistry.from_packages(["app.validation.deterministic"])
        assert DETECTOR.spec.detector_id in registry.ids()

    def test_baseline_pipeline_run(self, boq_profile) -> None:
        outcome = run_pipeline(DETECTOR, self._dataset(boq_profile), boq_profile)
        [report] = outcome.reports
        assert report.status is DetectorExecutionStatus.COMPLETED
        assert len(outcome.issues) == 4
        assert all(i.evidence_class is EvidenceClass.SEMANTIC_WARNING for i in outcome.issues)

    @pytest.mark.performance
    def test_twenty_thousand_rows_are_fast(self, boq_profile) -> None:
        dataset = large_boq_dataset(boq_profile)
        started = time.perf_counter()
        result = run(DETECTOR, dataset, boq_profile)
        assert time.perf_counter() - started < 5.0
        assert {i.rule_id for i in result.issues} == {"fractional_count"}
        assert len(result.issues) == LARGE_ROWS // 200
        assert result.coverage["description_groups_compared"] == 490
