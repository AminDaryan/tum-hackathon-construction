"""domain.boq_numbering: missing item numbers, misplaced items and empty sections."""

from __future__ import annotations

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, Severity
from app.validation.deterministic.hierarchy import RULE_ITEM, HierarchyDetector
from app.validation.domain.boq._tender import code_parts
from app.validation.domain.boq.numbering import (
    GROUPS_JUDGED,
    ITEMS_NUMBERED,
    LEFT_TO_HIERARCHY,
    RULE_EMPTY,
    RULE_GAP,
    RULE_MISPLACED,
    BoqNumberingDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    by_rule,
    run,
)

DETECTOR = BoqNumberingDetector


def item(code, text="Mauerwerk"):
    return [code, text, "2", "m2", "10.00", None]


def dataset(profile, rows, *, coded=False):
    """``rows``: item codes, or ``("section", code, level)`` / ``("text", note)`` tuples.
    ``coded``: sections carry their code as normalization records it."""
    builder = DatasetBuilder(profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for spec in rows:
        if isinstance(spec, str):
            table.row(item(spec))
        elif spec[0] == "section":
            table.row(
                [spec[1], f"Titel {spec[1]}", None, None, None, None],
                kind=RowKind.SECTION,
                level=spec[2],
                code=spec[1] if coded else None,
            )
        else:
            table.row([None, spec[1], None, None, None, None], kind=RowKind.TEXT)
    return builder.build()


def bill(profile, rows):
    return run(DETECTOR, dataset(profile, rows), profile)


def test_code_parts_ignore_leading_zeros_and_trailing_dots() -> None:
    assert code_parts("01.02.0030.") == ("1", "2", "30")
    assert code_parts("1.2..7") == ("1", "2", "7")
    assert code_parts("") == () and code_parts(None) == ()


def test_a_number_skipped_in_a_regular_sequence_is_a_missing_item(boq_profile) -> None:
    rows = [item(c) for c in ("1.10", "1.20", "1.30", "1.50", "1.60")]
    found = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE_GAP and issue.issue_category == "missing_item"
    assert (issue.evidence_class, issue.severity) == (
        EvidenceClass.SUSPECTED_ANOMALY,
        Severity.LOW,
    )
    assert issue.title == "Item number 1.40 missing between 1.30 and 1.50"
    assert {c.source.a1 for c in issue.affected_cells} == {"A4", "A5"}
    assert found.coverage[ITEMS_NUMBERED] == 5 and found.coverage[GROUPS_JUDGED] == 1
    assert_well_formed(found.issues)


def test_several_missing_numbers_are_one_finding(boq_profile) -> None:
    codes = ("2.1.10", "2.1.20", "2.1.30", "2.1.40", "2.1.70", "2.1.80", "2.1.90")
    [issue] = run(DETECTOR, boq_dataset(boq_profile, [item(c) for c in codes]), boq_profile).issues
    assert issue.title == "Item numbers 2.1.50, 2.1.60 missing between 2.1.40 and 2.1.70"


def test_large_jumps_and_irregular_groups_are_not_gaps(boq_profile) -> None:
    jump = ("1.10", "1.20", "1.30", "1.40", "1.100")  # a new block on purpose
    irregular = ("2.1", "2.2", "2.5", "2.9", "2.14")  # no common step
    few = ("3.1", "3.3", "3.4")  # too few to judge
    rows = [item(c) for c in (*jump, *irregular, *few)]
    found = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert found.issues == []
    assert found.coverage[GROUPS_JUDGED] == 1


def test_an_item_numbered_for_another_section_is_misplaced(boq_profile) -> None:
    found = bill(boq_profile, [("section", "2", 1), "2.1", "3.1", "2.3"])
    [issue] = found.issues
    assert issue.rule_id == RULE_MISPLACED
    assert issue.severity is Severity.MEDIUM
    assert issue.title == "Item 3.1 is in section 2"
    assert issue.affected_cells[0].source.a1 == "A4"
    assert_well_formed(found.issues)


def test_a_misplaced_item_the_hierarchy_check_reports_is_left_to_it(boq_profile) -> None:
    # deterministic.hierarchy (step B2) reports 3.1 in section 2 as an error. TEL00009 in
    # section 08.01 it does not compare (fewer parts, letters against digits): it stays here.
    rows = [
        ("section", "2", 1),
        *("2.1", "3.1", "2.3"),
        ("section", "08.01", 1),
        *("08.01.0001", "TEL00009"),
    ]
    data = dataset(boq_profile, rows, coded=True)
    found = run(DETECTOR, data, boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE_MISPLACED
    assert issue.title == "Item TEL00009 is in section 08.01"
    assert found.coverage[LEFT_TO_HIERARCHY] == 1
    hierarchy = run(HierarchyDetector, data, boq_profile)
    [outside] = hierarchy.issues
    assert outside.rule_id == RULE_ITEM and "3.1" in outside.title


def test_a_section_without_items_is_reported_innermost_only(boq_profile) -> None:
    rows = [
        ("section", "1", 1),
        "1.1",
        ("section", "2", 1),  # holds only the empty 2.1: not reported itself
        ("section", "2.1", 2),
        ("section", "3", 1),
        ("text", "Vorbemerkungen: es gelten die ZTV"),  # notes only: not empty
        ("section", "4", 1),
        "4.1",
    ]
    found = bill(boq_profile, rows)
    [issue] = by_rule(found.issues, RULE_EMPTY)
    assert issue.title == "Section 2.1 has no items: Titel 2.1"
    assert issue.severity is Severity.MEDIUM and issue.issue_category == "missing_item"
    assert len(found.issues) == 1
    assert_unique_fingerprints(found.issues)
    assert_well_formed(found.issues)


def test_a_complete_bill_reports_nothing(boq_profile) -> None:
    rows = [
        ("section", "01", 1),
        "01.0010",
        "01.0020",
        "01.0030",
        "01.0040",
        ("section", "02", 1),
        "02.0010",
        "02.0020",
    ]
    assert bill(boq_profile, rows).issues == []
