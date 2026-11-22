"""deterministic.hierarchy: item and section codes that contradict the document's numbering."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.clock import FixedClock
from app.core.config import BUILTIN_PROFILE_DIR, IngestionLimits, Settings
from app.core.errors import DetectorConfigError
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.adapter import GaebAdapter
from app.models.dataset import Dataset, RowKind
from app.models.issue import EvidenceClass, EvidenceKind, Severity, ValidationIssue
from app.models.profile import DomainProfile
from app.normalization.builder import build_dataset
from app.profiles.loader import ProfileCatalog
from app.validation.deterministic.hierarchy import (
    CATEGORY_NUMBERING,
    RULE_ITEM,
    RULE_ORDER,
    RULE_SECTION,
    HierarchyConfig,
    HierarchyDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder
from tests.unit.normalization.raw_builders import normalize, sheet, workbook
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    by_rule,
    resolve,
    run,
    run_pipeline,
)

DETECTOR = HierarchyDetector
RowSpec = tuple[list[Any], dict[str, Any]]
GAEB_FIXTURES = Path(__file__).parents[3] / "fixtures" / "gaeb"


def item(code: Any, description: str = "Position") -> RowSpec:
    return [code, description, "1", "m3", "10.00", "10.00"], {}


def section(code: Any, level: int = 1) -> RowSpec:
    """A section row whose code is in the code column (``code`` may be a typed number)."""
    values = [code, f"Titel {code}", None, None, None, None]
    return values, {"kind": RowKind.SECTION, "level": level, "code": str(code)}


def uncoded_section(label: str = "Hinweise", level: int = 1) -> RowSpec:
    return [None, label, None, None, None, None], {"kind": RowKind.SECTION, "level": level}


def row(kind: RowKind, code: Any = None, text: str = "Text") -> RowSpec:
    return [code, text, None, None, None, "5.00" if kind is RowKind.ADJUSTMENT else None], {
        "kind": kind
    }


def build(profile: DomainProfile, *rows: RowSpec, name: str = "LV") -> Dataset:
    builder = DatasetBuilder(profile)
    table = builder.table(name, BOQ_COLUMNS)
    for values, options in rows:
        table.row(values, **options)
    return builder.build()


def source_row(dataset: Dataset, position: int) -> int:
    return dataset.tables[0].rows[position].source_row_number


def anchored_rows(dataset: Dataset, issue: ValidationIssue) -> list[int]:
    table = dataset.tables[0]
    return [table.row(cell.row_id).source_row_number for cell in issue.affected_cells]


# --------------------------------------------------------------------------- clean bills
def test_a_consistent_bill_has_no_findings(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        section("01.01", level=2),
        item("01.01.0010"),
        item("01.01.0020"),
        section("01.02", level=2),
        item("01.02.0010"),
        item("1.2.20"),  # leading zeros do not count
        item("01.02.0030"),
        section("02"),
        item("02.0010"),
        item("02.0010"),  # an equal code is not lower (uniqueness is another check's)
        item("02.0020"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["rows_checked"] == 10  # 8 items and the 2 sections inside "01"
    assert result.coverage["sections_without_coded_parent"] == 2  # "01" and "02"


def test_codes_with_fewer_or_as_many_levels_as_their_section_are_not_prefix_checked(
    boq_profile: DomainProfile,
) -> None:
    dataset = build(
        boq_profile,
        section("01.02"),
        item("01.03"),  # as many levels: not compared by prefix
        item("7"),  # fewer levels
        section("03"),
        section("04", level=2),  # as many levels as its parent
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert by_rule(result.issues, RULE_ITEM) == [] and by_rule(result.issues, RULE_SECTION) == []


# --------------------------------------------------------------------------- the three rules
def test_an_item_outside_its_section(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        section("01.02", level=2),
        item("01.02.0010"),
        item("01.03.0020"),  # Titel 01.03's prefix inside Titel 01.02
        item("01.02.0030"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = result.issues
    assert issue.rule_id == RULE_ITEM and issue.issue_category == CATEGORY_NUMBERING
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.title == "Item code 01.03.0020 is outside section 01.02"
    table = dataset.tables[0]
    code_column = table.column_for_field("item_code")
    assert code_column is not None
    assert anchored_rows(dataset, issue) == [source_row(dataset, 3)]
    assert [cell.column_id for cell in issue.affected_cells] == [code_column.column_id]
    assert [table.row(cell.row_id).source_row_number for cell in issue.input_cells] == [
        source_row(dataset, 1)
    ]
    assert issue.row_id == table.rows[3].row_id
    assert issue.observed_value == "01.03.0020"
    assert issue.expected_value == "a code that starts with 01.02"
    assert f"'LV' row {source_row(dataset, 1)}" in issue.explanation
    kinds = [item.kind for item in issue.evidence]
    assert kinds[:2] == [EvidenceKind.RULE, EvidenceKind.COMPARISON]
    assert issue.evidence[1].data["compared_with"] == "01.02"
    # The wrong code does not enter the order: 01.02.0030 follows 01.02.0010.
    assert by_rule(result.issues, RULE_ORDER) == []
    assert result.coverage["items_outside_section"] == 1
    assert_well_formed(result.issues)


def test_a_section_outside_its_parent(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        section("01.01", level=2),
        item("01.01.0010"),
        section("02.01", level=2),  # the heading of Titel 02 is missing
        item("02.01.0010"),
        item("02.01.0020"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = result.issues
    assert issue.rule_id == RULE_SECTION and issue.severity is Severity.MEDIUM
    assert issue.title == "Section code 02.01 is outside section 01"
    assert anchored_rows(dataset, issue) == [source_row(dataset, 3)]
    assert issue.row_id == dataset.tables[0].rows[3].row_id
    assert "heading of its own parent section is missing" in issue.explanation
    assert result.coverage["sections_outside_parent"] == 1  # its items fit their section


def test_an_item_code_lower_than_the_one_before_it(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010"),
        item("01.0030"),
        item("01.0020"),  # lower than 01.0030
        item("01.0040"),  # compared with 01.0020: fine
        item("01.0100"),
        item("01.0090"),  # lower again
    )
    result = run(DETECTOR, dataset, boq_profile)
    issues = by_rule(result.issues, RULE_ORDER)
    assert [anchored_rows(dataset, i) for i in issues] == [
        [source_row(dataset, 3)],
        [source_row(dataset, 6)],
    ]
    first = issues[0]
    assert first.severity is Severity.LOW
    assert first.title == "Item code 01.0020 is lower than the code before it (01.0030)"
    assert first.expected_value == "a code higher than 01.0030"
    assert "in section 01" in first.explanation
    table = dataset.tables[0]
    assert [table.row(c.row_id).source_row_number for c in first.input_cells] == [
        source_row(dataset, 2)
    ]
    assert result.coverage["codes_out_of_order"] == 2
    assert_well_formed(result.issues)


def test_numbers_are_ordered_by_value_not_as_text(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("1"),
        item("1.9"),
        item("1.10"),  # higher than 1.9 by value, lower as text
        item("1.10.1"),  # a deeper code after its own prefix
        item("1.11"),
    )
    assert run(DETECTOR, dataset, boq_profile).issues == []


def test_the_order_is_kept_per_section_and_page(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010"),
        item("01.0020"),
        section("02"),
        item("02.0010"),  # a new section starts its own order
        row(RowKind.CARRY_FORWARD, text="Übertrag"),
        item("02.0005"),  # a page break starts again, as unique_scope: section does
    )
    assert run(DETECTOR, dataset, boq_profile).issues == []


# --------------------------------------------------------------------------- what is not compared
def test_codes_with_letters_take_part_in_the_prefix_rules_only(
    boq_profile: DomainProfile,
) -> None:
    dataset = build(
        boq_profile,
        section("A"),
        item("A.2"),
        item("A.1"),  # letters: not ordered
        item("B.1"),  # but outside section A
    )
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = result.issues
    assert issue.rule_id == RULE_ITEM and issue.title == "Item code B.1 is outside section A"
    assert result.coverage["codes_with_letters_not_ordered"] == 2


def test_a_section_code_with_letters_is_not_quoted_next_to_an_order_finding(
    boq_profile: DomainProfile,
) -> None:
    dataset = build(boq_profile, section("TEL00010"), item("1"), item("3"), item("2"))
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.rule_id == RULE_ORDER
    assert "TEL00010" not in issue.explanation and "in section" not in issue.explanation


def test_codes_of_another_numbering_scheme_are_not_prefix_checked(
    boq_profile: DomainProfile,
) -> None:
    dataset = build(
        boq_profile,
        section("A"),
        item("1.1"),  # numbers under a lettered section: another scheme
        item("1.2"),
        section("TEL00009"),  # an anonymised code is not a numbering
        item("01.0010"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["codes_of_another_scheme_not_compared"] == 3


def test_sections_without_a_code_are_skipped(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        uncoded_section(),
        item("01.0020"),
        item("99.0010"),  # nothing to compare with, and no order without a section code
        item("01.0010"),
        section("01"),
        uncoded_section("Bedarfspositionen", level=2),
        item("05.0010"),  # its innermost section has no code
        section("05.01", level=3),  # inside a section without a code
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["items_without_coded_section"] == 4
    assert result.coverage["sections_without_code"] == 2
    assert result.coverage["sections_without_coded_parent"] == 2


def test_items_without_a_code_and_rows_that_are_not_items_are_skipped(
    boq_profile: DomainProfile,
) -> None:
    dataset = build(
        boq_profile,
        item("05.0010"),  # outside every section
        section("01"),
        item(None),
        row(RowKind.TEXT, "09.0010"),
        row(RowKind.ADJUSTMENT, "08.0010", "Nachlass"),
        item("01.0010"),
        row(RowKind.TEXT, None, "Langtext"),
        item("01.0020"),
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["items_without_code"] == 1
    assert result.coverage["items_without_coded_section"] == 1
    assert result.coverage["rows_checked"] == 2


def test_codes_typed_as_decimal_numbers(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("1"),
        item(Decimal("1.9")),
        item(Decimal("1.1")),  # 1.10 typed as a number: not ordered
        item(Decimal("2.1")),  # its whole-number part is exact: outside section 1
        item(10),  # a whole number keeps its value and is ordered
        item(9),
        section(Decimal("1.1"), level=2),  # section 1.10 typed as a number
        item("1.10.1"),  # not compared with the section's untrusted code
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert [(i.rule_id, i.observed_value) for i in result.issues] == [
        (RULE_ITEM, "2.1"),
        (RULE_ORDER, "9"),
    ]
    assert result.coverage["codes_typed_as_decimal_numbers_not_ordered"] == 2
    assert result.coverage["rows_in_sections_typed_as_decimal_numbers"] == 1


# --------------------------------------------------------------------------- grouping
def test_many_findings_of_one_rule_become_one_finding(boq_profile: DomainProfile) -> None:
    rows = [section("01"), *(item(f"02.{n:04d}") for n in range(10, 60, 10))]
    rows += [item("01.0020"), item("01.0010")]  # one order finding stays single
    dataset = build(boq_profile, *rows)
    result = run(DETECTOR, dataset, boq_profile, {"max_row_issues": 3})
    [group] = by_rule(result.issues, RULE_ITEM)
    assert group.row_id is None
    assert group.title == "5 item codes are outside their sections in 'LV'"
    assert len(group.affected_cells) == 3  # the first max_row_issues codes
    assert group.observed_value == "5 codes"
    assert "the first 3 codes are highlighted" in group.explanation
    assert "check the section's code" in group.explanation
    assert group.evidence[1].data == {"codes": 5, "codes_highlighted": 3}
    assert [i.rule_id for i in result.issues] == [RULE_ITEM, RULE_ORDER]
    assert result.coverage["items_outside_section"] == 5
    single = run(DETECTOR, dataset, boq_profile, {"max_row_issues": 5})
    assert len(by_rule(single.issues, RULE_ITEM)) == 5
    assert_well_formed(result.issues)


def test_grouping_counts_per_table(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    for name in ("Los 1", "Los 2"):
        table = builder.table(name, BOQ_COLUMNS)
        for values, options in (section("01"), item("02.0010"), item("02.0020")):
            table.row(values, **options)
    result = run(DETECTOR, builder.build(), boq_profile, {"max_row_issues": 2})
    assert [i.row_id is not None for i in result.issues] == [True, True, True, True]
    grouped = run(DETECTOR, builder.build(), boq_profile, {"max_row_issues": 1})
    assert [i.title for i in grouped.issues] == [
        "2 item codes are outside their sections in 'Los 1'",
        "2 item codes are outside their sections in 'Los 2'",
    ]
    assert_unique_fingerprints(grouped.issues)


def test_the_section_and_order_rules_are_grouped_too(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        section("02.01", level=2),  # outside section 01
        item("02.01.0020"),
        item("02.01.0010"),  # lower than 02.01.0020
        section("02.02", level=2),  # outside section 01
        item("02.02.0020"),
        item("02.02.0010"),  # lower than 02.02.0020
    )
    single = run(DETECTOR, dataset, boq_profile, {"max_row_issues": 2})
    assert [i.rule_id for i in single.issues] == [RULE_SECTION] * 2 + [RULE_ORDER] * 2
    result = run(DETECTOR, dataset, boq_profile, {"max_row_issues": 1})
    assert [(i.rule_id, i.title) for i in result.issues] == [
        (RULE_SECTION, "2 section codes are outside their parent sections in 'LV'"),
        (RULE_ORDER, "2 item codes are lower than the code before them in 'LV'"),
    ]
    for issue in result.issues:
        assert issue.observed_value == "2 codes" and len(issue.affected_cells) == 1
        assert issue.evidence[1].data == {"codes": 2, "codes_highlighted": 1}
        assert "check the section's code" not in issue.explanation  # the item rule's hint
    assert result.coverage["sections_outside_parent"] == 2
    assert result.coverage["codes_out_of_order"] == 2
    assert_well_formed(result.issues)
    assert_unique_fingerprints(result.issues)


def test_a_table_that_does_not_map_the_code_field_is_noted(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for values, options in (section("01"), item("01.0020"), item("01.0010")):
        table.row(values, **options)
    builder.table("Notes", [("Kurztext", "description"), ("Menge", "quantity")]).row(
        ["Hinweis", "1"]
    )
    result = run(DETECTOR, builder.build(), boq_profile)
    assert [i.rule_id for i in result.issues] == [RULE_ORDER]
    assert result.notes == ["Table 'Notes': Item code is not mapped; not checked."]


# --------------------------------------------------------------------------- recommendations
def test_recommendations_ask_the_author_instead_of_renumbering(
    boq_profile: DomainProfile,
) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0020"),
        item("01.0010"),
        item("02.0030"),
        section("03.01", level=2),
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert {i.rule_id for i in result.issues} == {RULE_ITEM, RULE_SECTION, RULE_ORDER}
    for issue in result.issues:
        action = issue.suggested_action or ""
        assert "ask its author which code is meant" in action
        assert "instead of renumbering it yourself" in action
        assert len([s for s in action.split(". ") if s]) <= 3


# --------------------------------------------------------------------------- real structure
def test_normalized_spreadsheet_bills(boq_profile: DomainProfile) -> None:
    """Sections nest as normalization nests them: by code prefix, else by code depth."""
    rows = [
        ["OZ", "Kurztext", "Menge", "ME", "EP", "GP"],
        ["01", "Erdarbeiten"],
        ["01.01", "Aushub"],
        ["01.01.0010", "Oberboden abtragen", "120", "m2", "4.20", "504.00"],
        ["01.02.0020", "Boden lösen", "80", "m3", "12.00", "960.00"],
        ["02.01", "Rohbau: Fundamente"],  # Titel 02 has no heading row
        ["02.01.0010", "Fundamentbeton", "12", "m3", "160.00", "1920.00"],
        ["02.01.0030", "Schalung", "40", "m2", "30.00", "1200.00"],
        ["02.01.0020", "Bewehrung", "2", "t", "1500.00", "3000.00"],
    ]
    dataset = normalize(workbook(sheet(rows)), boq_profile)
    result = run(DETECTOR, dataset, boq_profile)
    found = [(i.rule_id, i.observed_value) for i in result.issues]
    assert found == [
        (RULE_ITEM, "01.02.0020"),
        (RULE_SECTION, "02.01"),
        (RULE_ORDER, "02.01.0020"),
    ]


def test_a_gaeb_bill_is_clean(boq_profile: DomainProfile) -> None:
    raw = GaebAdapter("83").extract(GAEB_FIXTURES / "small.x83", IngestionLimits())
    profile = ProfileCatalog.from_directories([BUILTIN_PROFILE_DIR]).get("boq")
    dataset = build_dataset(
        raw, profile=profile, document_id="doc", ids=SequentialIdFactory(), clock=FixedClock()
    )
    result = run(DETECTOR, dataset, profile)
    assert result.issues == []
    assert result.coverage["rows_checked"] == 1  # the item in category 01
    assert result.coverage["sections_without_code"] == 1  # the bill itself


def test_the_pipeline_runs_it_in_the_baseline_plan(boq_profile: DomainProfile) -> None:
    dataset = build(boq_profile, section("01"), item("01.0020"), item("01.0010"))
    outcome = run_pipeline(DETECTOR, dataset, boq_profile)
    assert [(i.detector_id, i.rule_id) for i in outcome.issues] == [
        ("deterministic.hierarchy", RULE_ORDER)
    ]


# --------------------------------------------------------------------------- config, registry
def test_config_applicability_and_registry(boq_profile: DomainProfile) -> None:
    assert HierarchyConfig.plannable_parameters() == {"code_field", "max_row_issues"}
    config = resolve(DETECTOR, boq_profile)
    assert config.severity_item_outside_section is Severity.MEDIUM
    assert config.severity_section_outside_parent is Severity.MEDIUM
    assert config.severity_code_order is Severity.LOW
    assert DETECTOR().required_fields(config) == ("item_code",)
    with pytest.raises(DetectorConfigError):
        resolve(DETECTOR, boq_profile, {"max_row_issues": 0})

    flat = build(boq_profile, item("01.0010"), item("01.0020"))
    verdict = applicability(DETECTOR, flat, boq_profile)
    assert not verdict.applicable and "No table has a section with a code" in verdict.reasons[0]
    uncoded = build(boq_profile, uncoded_section(), item("01.0010"))
    assert not applicability(DETECTOR, uncoded, boq_profile).applicable
    no_codes = DatasetBuilder(boq_profile)
    no_codes.table("LV", [("Kurztext", "description"), ("Menge", "quantity")]).row(
        ["Titel 01", None], kind=RowKind.SECTION, code="01"
    )
    verdict = applicability(DETECTOR, no_codes.build(), boq_profile)
    assert not verdict.applicable and "No table maps" in verdict.reasons[0]
    assert applicability(DETECTOR, build(boq_profile, section("01")), boq_profile).applicable

    registry = DetectorRegistry.from_packages(Settings().detector_packages)
    assert registry.get("deterministic.hierarchy") is DETECTOR
    assert DETECTOR.spec.issue_categories == (CATEGORY_NUMBERING,)


def test_a_profile_sets_the_severities(boq_profile: DomainProfile) -> None:
    dataset = build(boq_profile, section("01"), item("01.0020"), item("01.0010"), item("02.0030"))
    result = run(
        DETECTOR,
        dataset,
        boq_profile,
        {"severity_code_order": "high", "severity_item_outside_section": "critical"},
    )
    assert {i.rule_id: i.severity for i in result.issues} == {
        RULE_ORDER: Severity.HIGH,
        RULE_ITEM: Severity.CRITICAL,
    }


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [section("01"), item("01.0020"), item("01.0010"), item("02.0030")]
    rows += [section("03.01", level=2)]
    first = run(DETECTOR, build(boq_profile, *rows), boq_profile).issues
    again = run(DETECTOR, build(boq_profile, *rows), boq_profile).issues
    assert len(first) == 3
    assert_unique_fingerprints(first)
    assert [i.fingerprint for i in first] == [i.fingerprint for i in again]
