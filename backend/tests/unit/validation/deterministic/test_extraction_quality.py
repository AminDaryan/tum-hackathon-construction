"""deterministic.extraction_quality: low confidence, header and mapping doubts, warnings."""

from __future__ import annotations

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import (
    ColumnMapping,
    Dataset,
    ExtractionWarning,
    HeaderDetection,
    HeaderMethod,
    MappingMethod,
)
from app.models.issue import EvidenceClass, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.validation.deterministic.extraction_quality import (
    RULE_FUZZY,
    RULE_HEADER,
    RULE_LOW_CONFIDENCE,
    RULE_NO_MAPPED_COLUMNS,
    RULE_UNMAPPED,
    RULE_WARNING,
    ExtractionQualityConfig,
    ExtractionQualityDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import (
    DatasetBuilder,
    ambiguous_cell,
    make_context,
    number_cell,
    unit_cell,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    by_rule,
    resolve,
    run,
)

DETECTOR = ExtractionQualityDetector


def _item(quantity: object = "12", code: str = "01") -> list[object]:
    return [code, "Aushub", quantity, unit_cell("m3", "m3"), "40.00", "480.00"]


def _with_table(dataset: Dataset, **changes: object) -> Dataset:
    return dataset.evolve(tables=[dataset.tables[0].evolve(**changes)])


def test_a_clean_spreadsheet_has_no_findings(boq_profile: DomainProfile) -> None:
    result = run(DETECTOR, boq_dataset(boq_profile, [_item()]), boq_profile)
    assert result.issues == []
    assert "cells_checked" not in result.coverage  # verbatim cells carry no confidence
    assert result.coverage["tables_checked"] == 1


def test_low_confidence_cells(boq_profile: DomainProfile) -> None:
    rows = [
        _item(number_cell("12", confidence=0.85), code="01"),
        _item(number_cell("13", confidence=0.3), code="02"),
        _item(number_cell("14", confidence=0.95), code="03"),
        _item(ambiguous_cell("1.234").evolve(extraction_confidence=0.2), code="04"),
    ]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert [(i.rule_id, i.severity) for i in result.issues] == [
        (RULE_LOW_CONFIDENCE, Severity.MEDIUM),  # 0.3 < half the threshold
        (RULE_LOW_CONFIDENCE, Severity.LOW),
    ]
    low = result.issues[1]
    assert low.title == "Quantity read with low confidence: '12'"
    assert low.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert low.issue_category is IssueCategory.EXTRACTION
    assert low.evidence[0].data == {"confidence": 0.85, "threshold": 0.9}
    assert result.coverage["cells_checked"] == 3  # the ambiguous cell has another owner
    assert_well_formed(result.issues)


def test_the_threshold_comes_from_the_run_limits(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [_item(number_cell("12", confidence=0.85))])
    context = make_context(dataset, boq_profile, low_confidence_threshold=0.8)
    assert run(DETECTOR, dataset, boq_profile, context=context).issues == []


def test_many_low_confidence_cells_are_grouped(boq_profile: DomainProfile) -> None:
    rows = [_item(number_cell(str(i), confidence=0.6), code=f"{i:02d}") for i in range(5)]
    result = run(
        DETECTOR, boq_dataset(boq_profile, rows), boq_profile, {"max_issues_per_column": 3}
    )
    [group] = result.issues
    assert group.title == "5 values in Quantity were read with low confidence"
    assert group.row_id is None and len(group.affected_cells) == 5
    only_prices = run(
        DETECTOR, boq_dataset(boq_profile, rows), boq_profile, {"fields": ["unit_price"]}
    )
    assert only_prices.issues == []


def test_uncertain_header(boq_profile: DomainProfile) -> None:
    dataset = _with_table(
        boq_dataset(boq_profile, [_item()]),
        header=HeaderDetection(header_row_numbers=[1], method=HeaderMethod.FIRST_ROW),
    )
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.rule_id == RULE_HEADER
    assert issue.title == "Header row of table 'LV' was not recognized"
    assert "first non-empty row" in issue.explanation
    off = run(DETECTOR, dataset, boq_profile, {"report_header_uncertainty": False})
    assert off.issues == []


def test_required_field_without_a_column(boq_profile: DomainProfile) -> None:
    columns = [column for column in BOQ_COLUMNS if column[1] != "unit_price"]
    row = ["01", "Aushub", "12", unit_cell("m3", "m3"), "480.00"]
    dataset = boq_dataset(boq_profile, [row], columns=columns)
    [issue] = by_rule(run(DETECTOR, dataset, boq_profile).issues, RULE_UNMAPPED)
    assert issue.title == "Required column 'Unit price' not found in table 'LV'"
    assert issue.severity is Severity.MEDIUM
    off = run(DETECTOR, dataset, boq_profile, {"report_unmapped_fields": False})
    assert by_rule(off.issues, RULE_UNMAPPED) == []


def test_a_table_without_mapped_columns_gets_one_finding(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    builder.table("Deckblatt", [("Projekt", None), ("Datum", None)]).row(["Schule", "2026"])
    [issue] = run(DETECTOR, builder.build(), boq_profile).issues
    assert issue.rule_id == RULE_NO_MAPPED_COLUMNS
    assert issue.title == "No column of table 'Deckblatt' matches the profile"
    assert "'Projekt', 'Datum'" in issue.evidence[0].detail


def test_fuzzy_mapping(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [_item()])
    table = dataset.tables[0]
    fuzzy = ColumnMapping(
        field_id="unit_price",
        method=MappingMethod.HEADER_FUZZY,
        matched_synonym="Einheitspreis",
        similarity=0.86,
    )
    columns = [
        column.evolve(mapping=fuzzy, original_header="Einhietspreis")
        if column.mapped_semantic_field == "unit_price"
        else column
        for column in table.columns
    ]
    dataset = _with_table(dataset, columns=columns)
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.rule_id == RULE_FUZZY and issue.severity is Severity.LOW
    assert issue.title == "Column 'Einhietspreis' was matched to Unit price by approximate spelling"
    assert "0.86" in issue.explanation and "not a probability" in issue.explanation


def test_extraction_warnings_not_owned_elsewhere(boq_profile: DomainProfile) -> None:
    warnings = [
        ExtractionWarning(
            code="column_mapping_ambiguous",
            message="Columns 'EP' and 'Preis' both match Unit price; neither was mapped.",
        ),
        ExtractionWarning(code="number_format_ambiguous", message="3 values left unparsed."),
        ExtractionWarning(code="formula_without_cached_result", message="2 formulas."),
        ExtractionWarning(code="hidden_rows_present", message="Hidden rows.", needs_review=False),
    ]
    builder = DatasetBuilder(boq_profile, warnings=warnings)
    builder.table("LV", BOQ_COLUMNS).row(_item())
    result = run(DETECTOR, builder.build(), boq_profile)
    [issue] = result.issues
    assert issue.rule_id == RULE_WARNING
    assert issue.title.startswith("Columns 'EP' and 'Preis' both match Unit price")
    assert issue.evidence[0].data["code"] == "column_mapping_ambiguous"
    off = run(DETECTOR, builder.build(), boq_profile, {"report_extraction_warnings": False})
    assert off.issues == []


def test_profiles_without_fields_get_no_structure_findings(
    generic_profile: DomainProfile,
) -> None:
    builder = DatasetBuilder(generic_profile)
    builder.table("T", [("A", None), ("B", None)]).row(["x", "1"])
    assert run(DETECTOR, builder.build(), generic_profile).issues == []


def test_config_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)
    assert config.max_issues_per_column == 200 and config.report_fuzzy_mappings is True
    assert ExtractionQualityConfig.plannable_parameters() == {"fields", "max_issues_per_column"}
    for bad in ({"unknown": 1}, {"confidence_threshold": 0.5}, {"max_issues_per_column": 0}):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    assert (
        "deterministic.extraction_quality"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    def build() -> Dataset:
        warnings = [
            ExtractionWarning(code="unclassified_amount_row", message="Row 9 has an amount.")
        ]
        builder = DatasetBuilder(boq_profile, warnings=warnings)
        table = builder.table("LV", [column for column in BOQ_COLUMNS if column[1] != "unit"])
        table.row(["01", "Aushub", number_cell("12", confidence=0.5), "40.00", "480.00"])
        table.row(["02", "Aushub", number_cell("13", confidence=0.5), "40.00", "520.00"])
        return _with_table(
            builder.build(),
            header=HeaderDetection(header_row_numbers=[1], method=HeaderMethod.STRUCTURAL),
        )

    first = run(DETECTOR, build(), boq_profile)
    second = run(DETECTOR, build(), boq_profile)
    assert {i.rule_id for i in first.issues} == {
        RULE_LOW_CONFIDENCE,
        RULE_HEADER,
        RULE_UNMAPPED,
        RULE_WARNING,
    }
    assert_unique_fingerprints(first.issues)
    assert [i.fingerprint for i in first.issues] == [i.fingerprint for i in second.issues]
    assert_well_formed(by_rule(first.issues, RULE_LOW_CONFIDENCE))  # the rest are table-level
    for issue in first.issues:
        assert issue.explanation and issue.suggested_action  # the warning has no table
