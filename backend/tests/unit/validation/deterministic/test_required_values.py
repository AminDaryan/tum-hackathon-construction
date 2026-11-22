"""deterministic.required_values: empty required cells, exemptions, grouping, abstention."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.models.values import ValueMarker
from app.validation.deterministic.required_values import (
    RULE_REQUIRED,
    RequiredValuesDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, ambiguous_cell, marker_cell, unit_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    resolve,
    run,
)

DETECTOR = RequiredValuesDetector


def _dataset(profile: DomainProfile, rows: list[list[object]], **row_options: object):
    builder = DatasetBuilder(profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for values in rows:
        table.row(values, **row_options)  # type: ignore[arg-type]
    return builder.build()


def test_complete_items_produce_no_findings(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(
        boq_profile,
        [["01.0010", "Aushub", "12", unit_cell("m3", "m3"), "40.00", "480.00"]],
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["cells_checked"] > 0


def test_missing_unit_price_is_a_confirmed_violation(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(
        boq_profile,
        [
            ["01.0010", "Aushub", "12", unit_cell("m3", "m3"), "40.00", "480.00"],
            ["01.0020", "Verfüllen", "5", unit_cell("m3", "m3"), None, "100.00"],
        ],
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.rule_id == RULE_REQUIRED
    assert issue.issue_category == IssueCategory.MISSING_VALUE
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.HIGH  # monetary field
    assert "Unit price" in issue.title
    assert len(issue.affected_cells) == 1
    assert_well_formed(result.issues)


def test_markers_and_unusable_cells_are_not_missing(boq_profile: DomainProfile) -> None:
    included = marker_cell("Incl.", ValueMarker.INCLUDED_ELSEWHERE)
    rows = [
        ["01", "Pos", "1", unit_cell("m", "m"), included, "0"],
        ["02", "Pos", ambiguous_cell("1.234"), unit_cell("m", "m"), "1", "1"],
    ]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert result.issues == []


def test_exemptions_for_lump_sums_and_not_counted_items(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(["01", "Baustelleneinrichtung", None, unit_cell("psch", "ls"), None, "2500.00"])
    table.row(
        ["02", "Bodenaustausch nur EP", "50", unit_cell("m3", "m3"), "40.00", None], in_totals=False
    )
    table.row(["03", "Bedarfsposition", "1", unit_cell("St", "pcs"), "10.00", None], in_totals=None)
    table.row(["04", "Normal", "1", unit_cell("St", "pcs"), "10.00", None])
    dataset = builder.build()
    result = run(DETECTOR, dataset, boq_profile)
    table = dataset.tables[0]
    assert [table.row(i.row_id).classification.kind for i in result.issues] == [RowKind.ITEM]  # type: ignore[arg-type]
    assert [table.row(i.row_id).position for i in result.issues] == [3]  # type: ignore[arg-type]
    assert result.coverage["cells_exempt"] == 4


def test_an_item_with_quantity_zero_may_leave_its_unit_empty(boq_profile: DomainProfile) -> None:
    # Change-order items priced but not ordered: quantity 0, no unit, total 0.
    rows = [
        ["8.1.1", "Pumpe ohne FU", "0.000", None, "3279.20", "0.00"],
        ["8.1.2", "Mehrkosten", "0", None, None, "0.00"],
        ["8.1.3", "Zulage", "2", None, "10.00", "20.00"],
        ["8.1.4", "Pumpe mit FU", "1", unit_cell("St", "pcs"), "3500.00", "3500.00"],
    ]
    dataset = boq_dataset(boq_profile, rows)
    result = run(DETECTOR, dataset, boq_profile)
    table = dataset.tables[0]
    # Only the unit is exempt: the missing unit price of 8.1.2 and the unit of 8.1.3 (ordered).
    found = [(table.row(i.row_id).position, i.title.split(" in ")[0]) for i in result.issues]  # type: ignore[arg-type,union-attr]
    assert sorted(found) == [(1, "Missing Unit price"), (2, "Missing Unit")]


def test_many_missing_cells_are_grouped(boq_profile: DomainProfile) -> None:
    rows = [[f"{i:03d}", "Pos", "1", unit_cell("m", "m"), "2.00", None] for i in range(60)]
    rows[0][5] = "2.00"
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert len(result.issues) == 1
    group = result.issues[0]
    assert "59 rows" in group.title
    assert len(group.affected_cells) == 50


def test_an_unpriced_bill_gets_one_note(boq_profile: DomainProfile) -> None:
    rows = [[f"{i:03d}", "Pos", "1", unit_cell("m", "m"), None, None] for i in range(5)]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert result.issues == []
    assert result.coverage["columns_skipped_empty"] == 2
    assert any("unpriced" in note for note in result.notes)
    strict = run(
        DETECTOR, boq_dataset(boq_profile, rows), boq_profile, {"only_populated_columns": False}
    )
    assert len(strict.issues) == 10
    assert_unique_fingerprints(strict.issues)


def test_rows_of_other_kinds_are_not_checked(boq_profile: DomainProfile) -> None:
    dataset = _dataset(
        boq_profile, [[None, "Summe", None, None, None, "10.00"]], kind=RowKind.SUBTOTAL
    )
    assert run(DETECTOR, dataset, boq_profile).issues == []


def test_config_validation_and_profile_defaults(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)
    assert config.only_populated_columns is True
    assert [e.rule_id for e in config.exemptions] == [
        "lump_sum_without_quantity",
        "not_counted_without_total",
        "free_quantity",
        "not_offered",
        "not_offered_marker",
        "zero_quantity",
    ]
    with pytest.raises(DetectorConfigError):
        resolve(DETECTOR, boq_profile, {"unknown": 1})
    for bad in (
        {"rule_id": "x", "fields": ["quantity"]},  # no condition
        {"rule_id": "x", "fields": ["quantity"], "text_field": "item_type"},  # no pattern
        {"rule_id": "x", "fields": ["quantity"], "text_field": "item_type", "text_pattern": ".*"},
        {"rule_id": "x", "fields": ["line_total"], "marker_field": "unit_price"},  # no markers
        {"rule_id": "x", "fields": ["line_total"], "markers": ["not_offered"]},  # no field
        {
            "rule_id": "x",
            "fields": ["line_total"],
            "marker_field": "Unit price",
            "markers": ["nil"],
        },
        {"rule_id": "x", "fields": ["line_total"], "marker_field": "unit_price", "markers": ["x"]},
    ):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, {"exemptions": [bad]})
    assert (
        "deterministic.required_values"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_applicability(boq_profile: DomainProfile, generic_profile: DomainProfile) -> None:
    dataset = boq_dataset(boq_profile, [["01", "x", "1", unit_cell("m", "m"), "1", "1"]])
    assert applicability(DETECTOR, dataset, boq_profile).applicable
    generic = DatasetBuilder(generic_profile)
    generic.table("T", [("A", None)]).row(["x"])
    assert not applicability(DETECTOR, generic.build(), generic_profile).applicable


def test_fingerprints_are_stable(boq_profile: DomainProfile) -> None:
    rows = [
        ["01", "Pos", None, unit_cell("m", "m"), Decimal("2.00"), None],
        ["02", "Pos", "1", unit_cell("m", "m"), Decimal("2.00"), Decimal("2.00")],
    ]
    first = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    second = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert [i.fingerprint for i in first.issues] == [i.fingerprint for i in second.issues]
    assert len(first.issues) == 2


def test_a_free_quantity_item_may_leave_quantity_and_total_open(boq_profile: DomainProfile) -> None:
    # GAEB "Freie Menge" (QtyTBD): the item type column says the quantity is left open.
    columns = [*BOQ_COLUMNS, ("Positionsart", "item_type")]
    rows = [
        [
            "01",
            "Mehrstärke",
            None,
            unit_cell("m2", "m2"),
            "4.00",
            None,
            "Normalposition, Freie Menge",
        ],
        ["02", "Aushub", None, unit_cell("m3", "m3"), "9.00", "90.00", "Normalposition"],
        ["03", "Aushub", "10", unit_cell("m3", "m3"), "9.00", "90.00", "Normalposition"],
    ]
    result = run(DETECTOR, boq_dataset(boq_profile, rows, columns=columns), boq_profile)
    [issue] = result.issues
    assert issue.title == "Missing Quantity in 'LV' row 3"  # row 3 holds item 02
    assert result.coverage["cells_exempt"] == 2  # item 01: quantity and line total


def test_a_position_not_offered_is_left_to_the_bid_price_check(boq_profile: DomainProfile) -> None:
    # GAEB "nicht angeboten" (NotOffered): domain.boq_bid_prices reports the position once.
    columns = [*BOQ_COLUMNS, ("Positionsart", "item_type")]
    rows = [
        ["01", "Pflaster", "10", unit_cell("m2", "m2"), None, None, "nicht angeboten"],
        ["02", "Aushub", "10", unit_cell("m3", "m3"), None, None, "Normalposition"],
        ["03", "Aushub", "10", unit_cell("m3", "m3"), "9.00", "90.00", "Normalposition"],
    ]
    result = run(DETECTOR, boq_dataset(boq_profile, rows, columns=columns), boq_profile)
    assert sorted(i.title for i in result.issues) == [
        "Missing Line total in 'LV' row 3",
        "Missing Unit price in 'LV' row 3",
    ]
    assert result.coverage["cells_exempt"] == 2  # item 01: unit price and line total


def test_a_not_offered_marker_in_the_unit_price_exempts_the_total(
    boq_profile: DomainProfile,
) -> None:
    # A spreadsheet's "nicht angeboten" in the unit price (value marker not_offered): the empty
    # total is not reported again, as domain.boq_bid_prices reports the position (one finding).
    columns = [*BOQ_COLUMNS, ("Positionsart", "item_type")]
    not_offered = marker_cell("nicht angeboten", ValueMarker.NOT_OFFERED)
    included = marker_cell("enthalten", ValueMarker.INCLUDED_ELSEWHERE)
    rows = [
        ["01", "Pflaster", "10", unit_cell("m2", "m2"), not_offered, None, "Normalposition"],
        ["02", "Aushub", "10", unit_cell("m3", "m3"), included, None, "Normalposition"],
        ["03", "Aushub", "10", unit_cell("m3", "m3"), "9.00", "90.00", "Normalposition"],
    ]
    result = run(DETECTOR, boq_dataset(boq_profile, rows, columns=columns), boq_profile)
    # Another marker in the unit price is no exemption: item 02 still lacks its total.
    assert [i.title for i in result.issues] == ["Missing Line total in 'LV' row 3"]
    assert result.coverage["cells_exempt"] == 1  # item 01: line total
