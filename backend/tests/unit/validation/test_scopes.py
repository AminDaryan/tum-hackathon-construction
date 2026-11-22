"""Total scopes: bases, readings and the outcome table (validation-engine.md, "Total scopes")."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models.dataset import Dataset, Row, RowKind, Table
from app.models.profile import DomainProfile
from app.models.values import ValueMarker
from app.validation.contracts import scopes
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import RoundingSpec, TolerancePolicy
from app.validation.contracts.scopes import BasisKind, Outcome
from tests.support.builders import (
    DatasetBuilder,
    ambiguous_cell,
    make_context,
    marker_cell,
    number_cell,
)

COLUMNS: list[tuple[str | None, str | None]] = [
    ("Pos.", "item_code"),
    ("Kurztext", "description"),
    ("GP", "line_total"),
]
RowSpec = tuple[list[Any], dict[str, Any]]


def item(code: str | None, amount: Any, **options: Any) -> RowSpec:
    return [code, "Position", amount], options


def section(code: str, level: int = 1) -> RowSpec:
    return [code, f"Titel {code}", None], {"kind": RowKind.SECTION, "level": level, "code": code}


def subtotal(amount: Any, code: str | None = None, **options: Any) -> RowSpec:
    return [None, f"Summe {code or ''}", amount], {
        "kind": RowKind.SUBTOTAL,
        "code": code,
        **options,
    }


def total(amount: Any, kind: RowKind = RowKind.GRAND_TOTAL) -> RowSpec:
    return [None, "Gesamtsumme", amount], {"kind": kind}


def adjustment(amount: Any) -> RowSpec:
    return [None, "Nachlass", amount], {"kind": RowKind.ADJUSTMENT}


def summary(amount: Any) -> RowSpec:
    return [None, "Titel", amount], {"kind": RowKind.SUMMARY_LINE}


def build(profile: DomainProfile, *rows: RowSpec) -> Dataset:
    builder = DatasetBuilder(profile)
    table = builder.table("LV", COLUMNS)
    for values, options in rows:
        table.row(values, **options)
    return builder.build()


def totals(dataset: Dataset) -> list[Row]:
    kinds = {RowKind.SUBTOTAL, RowKind.GRAND_TOTAL}
    return [row for row in dataset.tables[0].rows if row.kind in kinds]


def verdict(dataset: Dataset, row: Row, profile: DomainProfile, **options: Any) -> scopes.Verdict:
    context = make_context(dataset, profile)
    table = dataset.tables[0]
    bases = context.rows_in_scope(table, row, "line_total")
    reported = context.number(table, row, "line_total")
    assert reported is not None
    return scopes.judge(
        reported, bases, rounding=RoundingSpec(), tolerance=TolerancePolicy(), **options
    )


def bases_of(dataset: Dataset, row: Row, profile: DomainProfile) -> list[scopes.Basis]:
    context: ValidationContext = make_context(dataset, profile)
    table: Table = dataset.tables[0]
    return context.rows_in_scope(table, row, "line_total")


def test_the_section_basis_is_the_only_one(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", "50"),
        subtotal("150", "01"),
    )
    [row] = totals(dataset)
    [basis] = bases_of(dataset, row, boq_profile)
    assert basis.kind is BasisKind.SECTION and len(basis.terms) == 2
    assert basis.description == "the items of section 01"
    result = verdict(dataset, row, boq_profile)
    assert result.outcome is Outcome.CONSISTENT
    assert result.reading is not None and result.reading.choices == ()


def test_nested_sections(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        section("01.01", level=2),
        item("01.01.0010", "100"),
        subtotal("100", "01.01"),
        section("01.02", level=2),
        item("01.02.0010", "40"),
        subtotal("40", "01.02"),
        subtotal("140", "01"),
    )
    rows = totals(dataset)
    assert [verdict(dataset, row, boq_profile).outcome for row in rows] == [Outcome.CONSISTENT] * 3
    assert len(bases_of(dataset, rows[2], boq_profile)[0].terms) == 2  # items, not subtotals


def test_code_and_block_bases_without_a_section(boq_profile: DomainProfile) -> None:
    rows = [item("01.0010", "100"), item("01.0020", "50"), item("02.0010", "30")]
    for reported, outcome in (
        ("150", Outcome.CONSISTENT),  # the code basis: items 01.x
        ("180", Outcome.CONSISTENT),  # the block basis: every item since the table start
        ("999", Outcome.AMBIGUOUS_STRUCTURE),  # two readings of the structure, neither fits
    ):
        dataset = build(boq_profile, *rows, subtotal(reported, "01"))
        [row] = totals(dataset)
        assert [b.kind for b in bases_of(dataset, row, boq_profile)] == [
            BasisKind.CODE,
            BasisKind.BLOCK,
        ]
        assert verdict(dataset, row, boq_profile).outcome is outcome


def test_one_basis_that_does_not_match_is_a_violation(boq_profile: DomainProfile) -> None:
    for reported, outcome in (
        ("150.01", Outcome.CONSISTENT),  # exactly at the allowed difference
        ("150.02", Outcome.VIOLATION),
        ("149", Outcome.VIOLATION),
    ):
        dataset = build(
            boq_profile,
            section("01"),
            item("01.0010", "100"),
            item("01.0020", "50"),
            subtotal(reported, "01"),
        )
        [row] = totals(dataset)
        result = verdict(dataset, row, boq_profile)
        assert result.outcome is outcome, reported
    assert result.reconciliation is not None
    assert result.reconciliation.expected == Decimal("150.00")
    assert result.reconciliation.difference == Decimal("-1.00")


def test_not_counted_and_undecided_items(boq_profile: DomainProfile) -> None:
    rows = [
        section("01"),
        item("01.0010", "100"),
        item("01.0020", "50", in_totals=False),
        item("01.0030", "30", in_totals=None),
    ]
    plain = build(boq_profile, *rows, subtotal("100", "01"))
    [row] = totals(plain)
    [basis] = bases_of(plain, row, boq_profile)
    assert [r.position for r in basis.left_out] == [2]
    assert verdict(plain, row, boq_profile).reading == scopes.Reading(Decimal("100"), ())
    with_optional = build(boq_profile, *rows, subtotal("130", "01"))
    [row] = totals(with_optional)
    result = verdict(with_optional, row, boq_profile)
    assert result.outcome is Outcome.CONSISTENT
    assert result.reading is not None
    assert result.reading.choices == ("with the undecided item in row 5",)


def test_not_counted_above_a_section(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", "50", in_totals=False),
        subtotal("150", "01"),
        total("100"),
    )
    table = dataset.tables[0]
    section_id = table.rows[0].row_id
    rows = [
        row.evolve(
            classification=row.classification.evolve(not_counted_above_section_id=section_id)
        )
        if row.position == 2
        else row
        for row in table.rows
    ]
    dataset = dataset.evolve(tables=[table.evolve(rows=rows)])
    sub, grand = totals(dataset)
    assert verdict(dataset, sub, boq_profile).outcome is Outcome.CONSISTENT  # counts in 01
    assert verdict(dataset, grand, boq_profile).outcome is Outcome.CONSISTENT  # not above it


def test_adjustments_with_either_sign(boq_profile: DomainProfile) -> None:
    for reported, choices in (("1500", ()), ("500", ("with the sign of row 4 reversed",))):
        dataset = build(
            boq_profile,
            section("01"),
            item("01.0010", "1000"),
            adjustment("500"),
            subtotal(reported, "01"),
        )
        [row] = totals(dataset)
        result = verdict(dataset, row, boq_profile)
        assert result.outcome is Outcome.CONSISTENT
        assert result.reading is not None and result.reading.choices == choices


def test_hidden_rows_all_in_or_all_out(boq_profile: DomainProfile) -> None:
    rows = [
        section("01"),
        item("01.0010", "100"),
        item("01.0020", "50", hidden=True),
        item("01.0030", "20", hidden=True),
    ]
    for reported, outcome in (
        ("170", Outcome.CONSISTENT),
        ("100", Outcome.CONSISTENT),
        ("150", Outcome.VIOLATION),  # some hidden rows in, some out: not admissible
    ):
        dataset = build(boq_profile, *rows, subtotal(reported, "01"))
        [row] = totals(dataset)
        assert verdict(dataset, row, boq_profile).outcome is outcome, reported


def test_markers_unusable_amounts_and_currencies(boq_profile: DomainProfile) -> None:
    included = marker_cell("Incl.", ValueMarker.INCLUDED_ELSEWHERE)
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", included),
        item("01.0030", None, in_totals=None),
        subtotal("100", "01"),
    )
    [row] = totals(dataset)
    [basis] = bases_of(dataset, row, boq_profile)
    assert basis.complete and [r.position for r in basis.without_amount] == [3]
    assert verdict(dataset, row, boq_profile).outcome is Outcome.CONSISTENT

    unreadable = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", ambiguous_cell("1.234")),
        subtotal("100", "01"),
    )
    [row] = totals(unreadable)
    result = verdict(unreadable, row, boq_profile)
    assert result.outcome is Outcome.INCOMPLETE
    assert [r.position for r in result.bases[0].unusable] == [2]

    mixed = build(
        boq_profile,
        section("01"),
        item("01.0010", number_cell("100", currency="EUR")),
        item("01.0020", number_cell("50", currency="USD")),
        subtotal("150", "01"),
    )
    [row] = totals(mixed)
    assert verdict(mixed, row, boq_profile).outcome is Outcome.INCOMPLETE


def test_excluded_rows_and_no_scope(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", "999", excluded=True),
        subtotal("100", "01"),
    )
    [row] = totals(dataset)
    assert verdict(dataset, row, boq_profile).outcome is Outcome.CONSISTENT
    empty = build(boq_profile, subtotal("100"))
    [row] = totals(empty)
    assert verdict(empty, row, boq_profile).outcome is Outcome.NO_SCOPE
    item_row = dataset.tables[0].rows[1]
    assert bases_of(dataset, item_row, boq_profile) == []


def test_summary_block(boq_profile: DomainProfile) -> None:
    dataset = build(boq_profile, summary("100"), summary("50"), subtotal("150"))
    [row] = totals(dataset)
    [basis] = bases_of(dataset, row, boq_profile)
    assert basis.kind is BasisKind.SUMMARY_BLOCK
    assert verdict(dataset, row, boq_profile).outcome is Outcome.CONSISTENT


def test_a_truncated_enumeration_is_undecided(boq_profile: DomainProfile) -> None:
    undecided = [item(f"01.{i:04d}", str(2**i), in_totals=None) for i in range(13)]
    dataset = build(boq_profile, section("01"), *undecided, subtotal("3", "01"))
    [row] = totals(dataset)
    [basis] = bases_of(dataset, row, boq_profile)
    found = scopes.readings(basis)
    assert found.truncated and len(found.readings) == 2  # all out, all in
    assert verdict(dataset, row, boq_profile).outcome is Outcome.UNDECIDED


def test_display_rounding_drift(boq_profile: DomainProfile) -> None:
    printed = [item(f"01.{i:04d}", "16.67") for i in range(6)]  # 6 x 16.67 = 100.02
    dataset = build(boq_profile, section("01"), *printed, subtotal("100.00", "01"))
    [row] = totals(dataset)
    assert verdict(dataset, row, boq_profile).outcome is Outcome.VIOLATION
    drift = verdict(dataset, row, boq_profile, drift_per_term=Decimal("0.005"))
    assert drift.outcome is Outcome.DISPLAY_ROUNDING


def test_grand_total_bases(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", "50"),
        subtotal("150", "01"),
        total("150"),
        adjustment("-30"),
        total("120"),
    )
    _, first, second = totals(dataset)
    [span] = bases_of(dataset, first, boq_profile)
    assert span.kind is BasisKind.SPAN and len(span.terms) == 2  # subtotals are not members
    assert verdict(dataset, first, boq_profile).outcome is Outcome.CONSISTENT
    [after] = bases_of(dataset, second, boq_profile)
    assert after.kind is BasisKind.AFTER_ADJUSTMENT
    assert verdict(dataset, second, boq_profile).outcome is Outcome.CONSISTENT


def test_grand_total_of_summary_lines(boq_profile: DomainProfile) -> None:
    dataset = build(boq_profile, summary("100"), summary("50"), total("150"))
    [row] = totals(dataset)
    [basis] = bases_of(dataset, row, boq_profile)
    assert basis.kind is BasisKind.SPAN_SUMMARY
    assert verdict(dataset, row, boq_profile).outcome is Outcome.CONSISTENT


def test_the_profile_decides_which_markers_count_as_zero(boq_profile: DomainProfile) -> None:
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", marker_cell("bauseits", ValueMarker.BY_OTHERS)),
        subtotal("100", "01"),
    )
    [row] = totals(dataset)
    assert verdict(dataset, row, boq_profile).outcome is Outcome.CONSISTENT
    strict = boq_profile.evolve(zero_contribution_markers=[ValueMarker.NIL])
    result = verdict(dataset, row, strict)
    assert result.outcome is Outcome.INCOMPLETE  # "by others" no longer counts as zero
    assert [r.position for r in result.bases[0].unusable] == [2]


def test_a_position_not_offered_adds_nothing_to_the_total(boq_profile: DomainProfile) -> None:
    """B2.1: the boq profile's not_offered marker ("nicht angeboten") contributes zero, so the
    totals of a bid with such a position can still be checked."""
    assert ValueMarker.NOT_OFFERED in boq_profile.zero_contribution_markers
    dataset = build(
        boq_profile,
        section("01"),
        item("01.0010", "100"),
        item("01.0020", marker_cell("nicht angeboten", ValueMarker.NOT_OFFERED)),
        subtotal("100", "01"),
    )
    [row] = totals(dataset)
    assert verdict(dataset, row, boq_profile).outcome is Outcome.CONSISTENT
