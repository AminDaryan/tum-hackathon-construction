"""deterministic.unit_vocabulary: units the profile does not know."""

from __future__ import annotations

import time

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, Severity
from app.models.run import DetectorExecutionStatus
from app.validation.contracts.conditions import Coverage
from app.validation.deterministic.unit_vocabulary import UnitVocabularyDetector
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, error_cell, text_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    LARGE_ROWS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    large_boq_dataset,
    resolve,
    run,
    run_pipeline,
)

DETECTOR = UnitVocabularyDetector


def row(code, unit, description="Mauerwerk"):
    return [code, description, "10", unit, "5.00", "50.00"]


class TestUnknownUnits:
    def test_unknown_units_are_grouped_by_their_key(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile,
            [
                row("1", "VE"),
                row("2", "m²"),
                row("3", "ve"),
                row("4", "V.E."),
                row("5", "VE"),
                row("6", "Bund"),
            ],
        )
        result = run(DETECTOR, dataset, boq_profile)
        ve, bund = result.issues
        assert ve.title == "Unit 'VE' is not in the profile's unit vocabulary (4 rows)"
        assert ve.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
        assert ve.severity is Severity.LOW
        assert [c.source.a1 for c in ve.affected_cells] == ["D2", "D4", "D5", "D6"]
        assert ve.evidence[0].data["spellings"] == "VE, ve, V.E."
        assert ve.evidence[0].data["rows"] == 4
        assert "'LV' rows 2, 4, 5 and 6 use the Unit 'VE'" in ve.explanation
        assert "unit aliases" in ve.suggested_action
        assert bund.title == "Unit 'Bund' is not in the profile's unit vocabulary (1 row)"
        assert "'LV' row 7 uses" in bund.explanation
        assert bund.row_id == dataset.tables[0].rows[5].row_id
        assert result.coverage[Coverage.ROWS_CHECKED] == 6
        assert result.coverage[Coverage.ROWS_CONSISTENT] == 1
        assert result.coverage[Coverage.ROWS_INCONSISTENT] == 5
        assert result.coverage["unknown_units"] == 2
        assert_unique_fingerprints(result.issues)
        assert_well_formed(result.issues)

    def test_known_spellings_multipliers_and_reviewer_aliases(self, boq_profile) -> None:
        units = ["m²", "qm", "Stk.", "psch", "100 St", "lfd. m", "m2 x Wo", "Std", "%"]
        rows = [row(str(n), unit) for n, unit in enumerate(units)]
        rows.append(row("99", text_cell("VE", normalized="pcs")))  # a reviewer's unit alias
        result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
        assert result.issues == []
        assert result.coverage[Coverage.ROWS_CONSISTENT] == len(rows)

    def test_empty_and_unreadable_units_are_left_to_their_owners(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile, [row("1", None), row("2", "  "), row("3", error_cell("#REF!"))]
        )
        result = run(DETECTOR, dataset, boq_profile)
        assert result.issues == []
        assert result.coverage[Coverage.ROWS_SKIPPED_MISSING_INPUTS] == 2
        assert result.coverage[Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS] == 1

    def test_a_number_in_the_unit_column_is_not_a_unit(self, boq_profile) -> None:
        [issue] = run(DETECTOR, boq_dataset(boq_profile, [row("1", 100)]), boq_profile).issues
        assert issue.title == "Unit '100' is not in the profile's unit vocabulary (1 row)"

    def test_only_item_rows_are_checked(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", BOQ_COLUMNS)
        table.row(["01", "Titel", None, "Abschnitt", None, None], kind=RowKind.SECTION)
        table.row(row("1", "VE"), excluded=True)
        table.row(row("2", "m"))
        result = run(DETECTOR, builder.build(), boq_profile)
        assert result.issues == [] and result.coverage[Coverage.ROWS_CHECKED] == 1

    def test_cells_are_capped_and_the_count_kept(self, boq_profile) -> None:
        rows = [row(str(n), "VE") for n in range(5)]
        result = run(
            DETECTOR, boq_dataset(boq_profile, rows), boq_profile, {"max_cells_per_issue": 2}
        )
        [issue] = result.issues
        assert len(issue.affected_cells) == 2 and issue.row_id is None
        assert issue.evidence[0].data == {
            "unit_key": "ve",
            "rows": 5,
            "cells_highlighted": 2,
            "spellings": "VE",
        }
        assert "The first 2 cells are highlighted." in issue.explanation

    def test_one_finding_per_table(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("Los 1", BOQ_COLUMNS).row(row("1", "VE"))
        builder.table("Los 2", BOQ_COLUMNS).row(row("1", "VE"))
        issues = run(DETECTOR, builder.build(), boq_profile).issues
        assert len(issues) == 2 and issues[0].table_id != issues[1].table_id
        assert_unique_fingerprints(issues)

    def test_very_long_unit_text_is_bounded(self, boq_profile) -> None:
        dataset = boq_dataset(boq_profile, [row("1", "Einheit " * 15_000)])
        started = time.perf_counter()
        [issue] = run(DETECTOR, dataset, boq_profile).issues
        assert time.perf_counter() - started < 1.0
        assert len(issue.title) <= 200 and len(issue.evidence[0].data["spellings"]) <= 80


class TestApplicabilityAndConfig:
    def test_not_applicable_without_a_unit_vocabulary(self, generic_profile) -> None:
        builder = DatasetBuilder(generic_profile)
        builder.table("Data", [("Unit", None)]).row(["m"])
        verdict = applicability(DETECTOR, builder.build(), generic_profile)
        assert not verdict.applicable and "no unit vocabulary" in verdict.reasons[0]

    def test_not_applicable_when_the_unit_field_is_unmapped(self, boq_profile) -> None:
        dataset = boq_dataset(boq_profile, [["1", "x"]], columns=BOQ_COLUMNS[:2])
        verdict = applicability(DETECTOR, dataset, boq_profile)
        assert not verdict.applicable and "unit" in verdict.reasons[0]

    def test_the_unit_field_must_be_a_unit_field(self, boq_profile) -> None:
        dataset = boq_dataset(boq_profile, [row("1", "m")])
        verdict = applicability(DETECTOR, dataset, boq_profile, {"unit_field": "description"})
        assert not verdict.applicable and "not a unit field" in verdict.reasons[0]

    def test_defaults_and_plannable_parameters(self, boq_profile) -> None:
        registry = DetectorRegistry([DETECTOR])
        config = registry.resolve_config(
            DETECTOR.spec.detector_id,
            [boq_profile.detector_defaults.get(DETECTOR.spec.detector_id, {})],
        )
        assert (config.unit_field, config.severity, config.max_cells_per_issue) == (
            "unit",
            Severity.LOW,
            200,
        )
        assert registry.describe(DETECTOR.spec.detector_id).plannable_parameters == [
            "max_cells_per_issue",
            "severity",
            "unit_field",
        ]

    @pytest.mark.parametrize(
        "overrides",
        [{"unknown": 1}, {"unit_field": "Unit"}, {"max_cells_per_issue": 0}, {"severity": "x"}],
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
        for n, unit in enumerate(["VE", "Bund", "ve", "m"]):
            table.row(row(str(n), unit))
        return builder.build()

    def test_fingerprints_are_stable_and_distinct(self, boq_profile) -> None:
        first = run(DETECTOR, self._dataset(boq_profile), boq_profile).issues
        shifted = run(DETECTOR, self._dataset(boq_profile, 3), boq_profile).issues
        assert len(first) == 2
        assert [i.fingerprint for i in first] == [i.fingerprint for i in shifted]
        assert_unique_fingerprints(first)

    def test_discovered_in_the_deterministic_package(self) -> None:
        registry = DetectorRegistry.from_packages(["app.validation.deterministic"])
        assert DETECTOR.spec.detector_id in registry.ids()

    def test_baseline_pipeline_run(self, boq_profile) -> None:
        outcome = run_pipeline(DETECTOR, self._dataset(boq_profile), boq_profile)
        [report] = outcome.reports
        assert report.status is DetectorExecutionStatus.COMPLETED
        assert len(outcome.issues) == 2 and report.coverage["unknown_units"] == 2

    @pytest.mark.performance
    def test_twenty_thousand_rows_are_fast(self, boq_profile) -> None:
        dataset = large_boq_dataset(boq_profile)
        started = time.perf_counter()
        result = run(DETECTOR, dataset, boq_profile)
        assert time.perf_counter() - started < 5.0
        [issue] = result.issues
        assert issue.evidence[0].data["rows"] == LARGE_ROWS // 50
        assert len(issue.affected_cells) == 200
