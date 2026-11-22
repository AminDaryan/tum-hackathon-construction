"""deterministic.field_constraints: patterns, allowed values and unique codes."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import Dataset, RowKind
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.validation.deterministic.field_constraints import (
    RULE_ALLOWED,
    RULE_PATTERN,
    RULE_UNIQUE,
    FieldConstraintsConfig,
    FieldConstraintsDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, error_cell, unit_cell
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

DETECTOR = FieldConstraintsDetector


def _item(code: object, description: str = "Aushub") -> list[object]:
    return [code, description, "1", unit_cell("m3", "m3"), "40.00", "40.00"]


def _section(code: str) -> list[object]:
    return [code, f"Titel {code}", None, None, None, None]


def _positions(dataset: Dataset, issue: Any) -> list[int]:
    table = dataset.tables[0]
    return [table.row(ref.row_id).position for ref in issue.affected_cells]


def test_unique_codes_produce_no_findings(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [_item("01.0010"), _item("01.0020")])
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["cells_checked"] == 2


def test_duplicate_codes_in_one_section(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(_section("01"), kind=RowKind.SECTION, code="01")
    for code in ("01.0010", "01.0020", "01.0010", " 01.0010. "):
        table.row(_item(code))
    dataset = builder.build()
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = result.issues
    assert issue.rule_id == RULE_UNIQUE
    assert issue.issue_category is IssueCategory.CONSTRAINT
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.MEDIUM
    assert issue.title == "Item code 01.0010 appears 3 times"
    assert "in section 01" in issue.explanation
    assert dataset.tables[0].row(issue.row_id).position == 3  # type: ignore[arg-type]
    assert _positions(dataset, issue) == [1, 3, 4]
    reference = issue.evidence[0]
    assert reference.kind is EvidenceKind.REFERENCE
    assert reference.data["rows"] == 3
    assert result.coverage["duplicate_groups"] == 1
    assert_well_formed(result.issues)


def test_section_scope_restarts_per_section_and_page(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(_section("1"), kind=RowKind.SECTION, code="1")
    table.row(_item("A"))
    table.row(_item("B"))
    table.row(_section("2"), kind=RowKind.SECTION, code="2")
    table.row(_item("A"))
    table.row([None, "Übertrag", None, None, None, "120.00"], kind=RowKind.CARRY_FORWARD)
    table.row(_item("A"))
    table.row(_item("A"))
    dataset = builder.build()
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.title == "Item code A appears 2 times"
    assert "in section 2" in issue.explanation
    assert _positions(dataset, issue) == [6, 7]

    whole_table = {"constraints": {"item_code": {"unique": True, "unique_scope": "table"}}}
    [issue] = run(DETECTOR, dataset, boq_profile, whole_table).issues
    assert issue.title == "Item code A appears 4 times"
    assert "in table 'LV'" in issue.explanation


def test_identifiers_ignore_case_and_spaces_not_leading_zeros(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [_item("1.10"), _item("01.10"), _item("a 1"), _item("A1")])
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert _positions(dataset, issue) == [2, 3]


def test_other_fields_compare_case_folded_text(boq_profile: DomainProfile) -> None:
    rows = [
        _item("01", "Aushub Boden"),
        _item("02", "aushub boden"),
        _item("03", "Aushub Boden"),
        _item("04", "Beton"),
    ]
    unique_text = {"constraints": {"description": {"unique": True}}}
    [issue] = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, unique_text).issues
    assert issue.title == "Description Aushub Boden appears 3 times"
    exact = {**unique_text, "case_sensitive_unique": True}
    [issue] = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, exact).issues
    assert issue.title == "Description Aushub Boden appears 2 times"


def test_pattern_and_allowed_values(boq_profile: DomainProfile) -> None:
    overrides = {
        "constraints": {
            "item_code": {"pattern": r"\d{2}\.\d{4}"},
            "description": {"allowed_values": ["Aushub", "Verfüllen"]},
        }
    }
    rows = [_item("01.0010"), _item("1-20", "AUSHUB"), _item("01.0030", "Beton")]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, overrides)
    [pattern] = by_rule(result.issues, RULE_PATTERN)
    assert pattern.title == "Item code '1-20' does not have the expected format"
    assert pattern.severity is Severity.LOW
    assert pattern.expected_value == r"matches \d{2}\.\d{4}"
    [allowed] = by_rule(result.issues, RULE_ALLOWED)
    assert allowed.title == "Description 'Beton' is not an allowed value"
    assert allowed.severity is Severity.MEDIUM
    assert allowed.expected_value == "one of: Aushub, Verfüllen"
    assert "settings for this detector" in allowed.explanation
    assert len(result.issues) == 2
    assert_well_formed(result.issues)
    assert_unique_fingerprints(result.issues)


def test_many_pattern_failures_are_grouped(boq_profile: DomainProfile) -> None:
    overrides = {"constraints": {"item_code": {"pattern": r"\d+"}}}
    rows = [_item(f"x{i}") for i in range(60)]
    [group] = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile, overrides).issues
    assert group.title == "60 values in Item code do not have the expected format"
    assert group.row_id is None
    assert len(group.affected_cells) == 50
    assert_well_formed([group])


def test_unusable_cells_and_other_rows_are_skipped(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(_item("01.0010"))
    table.row(_item(None))
    table.row(_item(error_cell("#REF!")))
    table.row(_item("01.0010"), excluded=True)
    table.row(["01.0010", "Summe", None, None, None, "40.00"], kind=RowKind.SUBTOTAL)
    result = run(DETECTOR, builder.build(), boq_profile)
    assert result.issues == []
    assert result.coverage["cells_checked"] == 1


def test_applicability(boq_profile: DomainProfile, generic_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [_item("01")])
    assert applicability(DETECTOR, dataset, boq_profile).applicable
    no_codes = boq_dataset(boq_profile, [_item("01")[1:]], columns=BOQ_COLUMNS[1:])
    assert not applicability(DETECTOR, no_codes, boq_profile).applicable
    generic = DatasetBuilder(generic_profile)
    generic.table("T", [("A", None)]).row(["x"])
    assert not applicability(DETECTOR, generic.build(), generic_profile).applicable


def test_config_validation_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)
    assert config.max_cells_per_issue == 50 and config.case_sensitive_unique is False
    assert FieldConstraintsConfig.plannable_parameters() == {"fields", "max_cells_per_issue"}
    for bad in (
        {"unknown": 1},
        {"fields": ["Not An Id"]},
        {"max_cells_per_issue": 0},
        {"constraints": {"item_code": {"pattern": "("}}},
    ):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    assert (
        "deterministic.field_constraints"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [_item("01"), _item("01"), _item("02"), _item("02"), _item("02")]
    first = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    second = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert len(first.issues) == 2
    assert_unique_fingerprints(first.issues)
    assert [i.fingerprint for i in first.issues] == [i.fingerprint for i in second.issues]
