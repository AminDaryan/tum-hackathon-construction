"""deterministic.reference_integrity: references in text and in reference fields."""

from __future__ import annotations

import time

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, Severity
from app.models.profile import FieldRole, SemanticField
from app.models.run import DetectorExecutionStatus
from app.models.values import DataType
from app.validation.contracts.conditions import Coverage
from app.validation.deterministic.reference_integrity import ReferenceIntegrityDetector
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, error_cell
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

DETECTOR = ReferenceIntegrityDetector


def row(code, description, unit="m2"):
    return [code, description, "10", unit, "5.00", "50.00"]


@pytest.fixture
def reference_profile(boq_profile):
    """The BoQ profile plus a reference field (a "related item" column) for field rules."""
    related = SemanticField(
        field_id="related_item",
        label="Related item",
        data_type=DataType.TEXT,
        role=FieldRole.REFERENCE,
    )
    return boq_profile.evolve(fields=[*boq_profile.fields, related])


FIELD_RULE = {
    "rule_id": "related_item",
    "source_field": "related_item",
    "target_field": "item_code",
}
RELATED_COLUMNS = [*BOQ_COLUMNS, ("Bezug", "related_item")]


class TestTextReferences:
    def test_german_references_resolve_with_leading_zeros(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile,
            [
                row("1.2.30", "Mauerwerk KS 24 cm"),
                row("01.02.0040", "Zulage wie Pos. 01.02.0030, jedoch 30 cm"),
                row("01.02.0050", "Ausführung siehe OZ 01.2.30"),
            ],
        )
        result = run(DETECTOR, dataset, boq_profile)
        assert result.issues == []
        assert result.coverage["references_checked"] == 2
        assert result.coverage["references_resolved"] == 2
        assert "references_unresolved" not in result.coverage

    def test_unresolved_german_reference_needs_external_context(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile,
            [row("01.0010", "Aushub"), row("01.0020", "Verfüllung, siehe OZ 3.1.20")],
        )
        result = run(DETECTOR, dataset, boq_profile)
        [issue] = result.issues
        assert issue.rule_id == "german_position_reference"
        assert issue.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
        assert issue.severity is Severity.LOW
        assert issue.title == "Description refers to 3.1.20, which is not in this document"
        assert issue.observed_value == "3.1.20"
        assert "'LV' row 3" in issue.explanation and "another document or lot" in issue.explanation
        assert issue.affected_cells[0].source.a1 == "B3"
        assert issue.evidence[0].data["matched_text"] == "siehe OZ 3.1.20"
        assert result.coverage["references_unresolved"] == 1
        assert_well_formed(result.issues)

    def test_spaced_segments_resolve_to_the_position(self, boq_profile) -> None:
        # Some bills write the segments of a position number with spaces after the dots.
        dataset = boq_dataset(
            boq_profile,
            [
                row("03.05.0001", "Facharbeiter", unit="h"),
                row("03.05.0002", "Wie Position 3. 5. 1., jedoch Bauwerker/-in", unit="h"),
                row("03.05.0003", "wie Pos. 3. 5. 1. jedoch Helfer", unit="h"),
            ],
        )
        result = run(DETECTOR, dataset, boq_profile)
        assert result.issues == []
        assert result.coverage["references_resolved"] == 2

    def test_spaced_segments_outside_the_bill_need_external_context(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile,
            [
                row("05.04.0016", "Oberboden andecken"),
                row("05.04.0018", "Wie Position 5. 4. 17., jedoch 30 cm"),
            ],
        )
        result = run(DETECTOR, dataset, boq_profile)
        [issue] = result.issues
        assert issue.rule_id == "german_position_reference"
        assert issue.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
        assert issue.observed_value == "5. 4. 17"
        assert issue.evidence[0].data["matched_text"] == "Wie Position 5. 4. 17"
        assert issue.affected_cells[0].source.a1 == "B3"

    def test_english_references(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile,
            [
                row("2.1.4", "Brickwork in cement mortar"),
                row("2.1.5", "Brickwork as item 2.1.4 but 215 mm thick"),
                row("2.1.6", "Pointing, see item 7.7.7"),
            ],
        )
        [issue] = run(DETECTOR, dataset, boq_profile).issues
        assert issue.rule_id == "english_item_reference"
        assert issue.observed_value == "7.7.7"

    def test_several_references_in_one_text(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile,
            [
                row("01.0010", "Schalung"),
                row(
                    "01.0020",
                    "wie Pos. 01.0010, Bewehrung siehe Pos. 09.0090, Beton vgl. Pos. 09.0091",
                ),
            ],
        )
        result = run(DETECTOR, dataset, boq_profile)
        assert sorted(i.observed_value for i in result.issues) == ["09.0090", "09.0091"]
        assert result.coverage["references_resolved"] == 1
        assert_unique_fingerprints(result.issues)

    def test_the_same_code_twice_in_one_text_is_one_reference(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile, [row("1.1", "x"), row("1.2", "wie Pos. 9.9, siehe Pos. 09.09")]
        )
        result = run(DETECTOR, dataset, boq_profile)
        assert len(result.issues) == 1 and result.coverage["references_checked"] == 1

    def test_self_references_are_ignored(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", BOQ_COLUMNS)
        table.row(row("01.0010", "Aushub wie Pos. 1.10"))
        table.row(
            [None, "Ausführung siehe Pos. 01.0010", None, None, None, None],
            kind=RowKind.TEXT,
            belongs_to=0,
        )
        result = run(DETECTOR, builder.build(), boq_profile)
        assert result.issues == []
        assert result.coverage["references_self_ignored"] == 2
        assert "references_checked" not in result.coverage

    def test_references_span_tables(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("Los 1", BOQ_COLUMNS).row(row("01.02.0030", "Mauerwerk"))
        builder.table("Los 2", BOQ_COLUMNS).row(row("02.01.0010", "wie Pos. 1.2.30")).row(
            row("02.01.0020", "wie Pos. 3.3.3")
        )
        result = run(DETECTOR, builder.build(), boq_profile)
        [issue] = result.issues
        assert issue.observed_value == "3.3.3"
        assert "'Los 2' row 3" in issue.explanation
        assert "2 table(s)" in issue.evidence[1].detail

    def test_section_codes_are_identifiers(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", BOQ_COLUMNS)
        table.row(["01.02", "Mauerarbeiten", None, None, None, None], kind=RowKind.SECTION)
        # A section whose code normalization took from its label ("Untertitel 03.01 Putz").
        table.row(
            [None, "Untertitel 03.01 Putz", None, None, None, None],
            kind=RowKind.SECTION,
            code="03.01",
        )
        table.row(row("01.02.0010", "Leistungen wie Pos. 01.02, Putz siehe Pos. 3.1"))
        table.row(row("01.02.0020", "siehe Pos. 03.0002"))
        result = run(DETECTOR, builder.build(), boq_profile)
        assert [i.observed_value for i in result.issues] == ["03.0002"]
        assert result.coverage["references_resolved"] == 2

    def test_unmatched_wording_is_not_a_reference(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile,
            [row("1.1", "Fliesen 30.60 cm, Fuge 2.5 mm, DIN 18352"), row("1.2", "wie oben")],
        )
        result = run(DETECTOR, dataset, boq_profile)
        assert result.issues == []
        assert result.coverage[Coverage.ROWS_CHECKED] == 4  # two rows, each rule

    def test_unreadable_descriptions_are_counted(self, boq_profile) -> None:
        dataset = boq_dataset(boq_profile, [row("1.1", error_cell("#REF!")), row("1.2", None)])
        result = run(DETECTOR, dataset, boq_profile)
        assert result.issues == []
        # one row per text rule: the error cell is reported by formula_errors
        assert result.coverage[Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS] == 2

    def test_long_descriptions_are_bounded_and_fast(self, boq_profile) -> None:
        long_text = "Mauerwerk " + "sehr lang " * 10_000 + "wie Pos. 9.9.9"
        hostile = "wie Pos. " + "1." * 50_000 + "x"
        dataset = boq_dataset(
            boq_profile, [row("1.1", long_text), row("1.2", hostile), row("1.3", "a" * 100_000)]
        )
        started = time.perf_counter()
        result = run(DETECTOR, dataset, boq_profile)
        assert time.perf_counter() - started < 1.0
        assert result.issues == []  # the reference lies beyond the pattern window
        assert result.coverage["texts_truncated"] == 6  # three texts, two rules
        assert any("pattern window" in note for note in result.notes)


class TestFieldRules:
    def _dataset(self, profile, related_values, *, codes=("01.0010", "01.0020")):
        builder = DatasetBuilder(profile)
        table = builder.table("LV", RELATED_COLUMNS)
        for code, related in zip(codes, related_values, strict=True):
            table.row([*row(code, "Aushub"), related])
        return builder.build()

    def test_unresolved_reference_is_a_confirmed_violation(self, reference_profile) -> None:
        dataset = self._dataset(reference_profile, ["1.20", "01.0099"])
        result = run(DETECTOR, dataset, reference_profile, {"rules": [FIELD_RULE]})
        [issue] = result.issues
        assert issue.rule_id == "related_item"
        assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
        assert issue.severity is Severity.MEDIUM
        assert issue.title == "Related item 01.0099 does not match any Item code"
        assert issue.affected_cells[0].source.a1 == "G3"
        assert result.coverage["references_resolved"] == 1
        assert_well_formed(result.issues)

    def test_separator_splits_several_references(self, reference_profile) -> None:
        dataset = self._dataset(reference_profile, ["01.0020, 7.7; 1.10", None])
        rule = {**FIELD_RULE, "separator": ","}
        result = run(DETECTOR, dataset, reference_profile, {"rules": [rule]})
        [issue] = result.issues  # "7.7; 1.10" is one part and does not resolve
        assert issue.observed_value == "7.7; 1.10"
        assert result.coverage["references_checked"] == 2

    def test_values_that_are_not_codes_are_counted(self, reference_profile) -> None:
        dataset = self._dataset(reference_profile, ["x" * 300, "1.10"])
        result = run(DETECTOR, dataset, reference_profile, {"rules": [FIELD_RULE]})
        assert result.issues == []
        assert result.coverage["references_unparseable"] == 1

    def test_unreadable_identifiers_make_the_finding_uncertain(self, reference_profile) -> None:
        dataset = self._dataset(
            reference_profile, ["9.9", None], codes=("01.0010", error_cell("#REF!"))
        )
        result = run(DETECTOR, dataset, reference_profile, {"rules": [FIELD_RULE]})
        [issue] = result.issues
        assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
        assert any(e.label == "Some identifiers could not be read" for e in issue.evidence)
        assert any("could not be read" in note for note in result.notes)

    def test_rule_without_identifiers_is_not_checked(self, reference_profile) -> None:
        dataset = self._dataset(reference_profile, ["9.9", "9.8"], codes=(None, None))
        result = run(DETECTOR, dataset, reference_profile, {"rules": [FIELD_RULE]})
        assert result.issues == []
        assert any("no Item code values were found" in note for note in result.notes)


class TestApplicabilityAndConfig:
    def test_not_applicable_without_rules(self, generic_profile) -> None:
        builder = DatasetBuilder(generic_profile)
        builder.table("Data", [("A", None)]).row(["1"])
        verdict = applicability(DETECTOR, builder.build(), generic_profile)
        assert not verdict.applicable
        assert "No reference rules" in verdict.reasons[0]

    def test_not_applicable_when_fields_are_unmapped(self, boq_profile) -> None:
        dataset = boq_dataset(
            boq_profile, [["1.1", "10"]], columns=[("Pos.", "item_code"), ("Menge", "quantity")]
        )
        verdict = applicability(DETECTOR, dataset, boq_profile)
        assert not verdict.applicable
        assert "description" in verdict.reasons[0]

    def test_boq_defaults_are_accepted(self, boq_profile) -> None:
        registry = DetectorRegistry([DETECTOR])
        config = registry.resolve_config(
            DETECTOR.spec.detector_id,
            [boq_profile.detector_defaults.get(DETECTOR.spec.detector_id, {})],
        )
        assert [r.rule_id for r in config.text_references] == [
            "german_position_reference",
            "english_item_reference",
        ]
        assert config.rules == ()
        assert registry.describe(DETECTOR.spec.detector_id).plannable_parameters == [
            "severity_field_rule",
            "severity_text_rule",
        ]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"unknown": 1},
            {
                "text_references": [
                    {
                        "rule_id": "r",
                        "text_field": "description",
                        "pattern": r"pos\.? \d+",
                        "target_field": "item_code",
                    }
                ]
            },
            {
                "text_references": [
                    {
                        "rule_id": "r",
                        "text_field": "description",
                        "pattern": r"(pos)\.? (\d+)",
                        "target_field": "item_code",
                    }
                ]
            },
            {
                "text_references": [
                    {
                        "rule_id": "r",
                        "text_field": "description",
                        "pattern": r"(\d+",
                        "target_field": "item_code",
                    }
                ]
            },
            {
                "text_references": [
                    {
                        "rule_id": "r",
                        "text_field": "description",
                        "pattern": r"(\d*)",
                        "target_field": "item_code",
                    }
                ]
            },
            {
                "text_references": [
                    {
                        "rule_id": "r",
                        "text_field": "Description",
                        "pattern": r"(\d+)",
                        "target_field": "item_code",
                    }
                ]
            },
            {"rules": [FIELD_RULE, FIELD_RULE]},
            {"rules": [{**FIELD_RULE, "separator": ""}]},
            {"rules": [{**FIELD_RULE, "extra": True}]},
            {"severity_text_rule": "loud"},
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
        table.row(row("1.1", "wie Pos. 8.8 und siehe Pos. 9.9"))
        table.row(row("1.2", "as item 9.9"))
        return builder.build()

    def test_fingerprints_are_stable_and_distinct(self, boq_profile) -> None:
        first = run(DETECTOR, self._dataset(boq_profile), boq_profile).issues
        shifted = run(DETECTOR, self._dataset(boq_profile, 5), boq_profile).issues
        assert len(first) == 3
        assert [i.fingerprint for i in first] == [i.fingerprint for i in shifted]
        assert_unique_fingerprints(first)

    def test_discovered_in_the_deterministic_package(self) -> None:
        registry = DetectorRegistry.from_packages(["app.validation.deterministic"])
        assert DETECTOR.spec.detector_id in registry.ids()

    def test_baseline_pipeline_run_uses_the_profile_rules(self, boq_profile) -> None:
        outcome = run_pipeline(DETECTOR, self._dataset(boq_profile), boq_profile)
        [report] = outcome.reports
        assert report.status is DetectorExecutionStatus.COMPLETED
        assert len(outcome.issues) == 3
        assert report.coverage["references_unresolved"] == 3

    @pytest.mark.performance
    def test_twenty_thousand_rows_are_fast(self, boq_profile) -> None:
        dataset = large_boq_dataset(boq_profile)
        started = time.perf_counter()
        result = run(DETECTOR, dataset, boq_profile)
        assert time.perf_counter() - started < 5.0
        assert result.issues == []
        assert result.coverage["references_resolved"] == LARGE_ROWS // 100
        assert result.coverage[Coverage.ROWS_CHECKED] == 2 * LARGE_ROWS
