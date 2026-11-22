"""deterministic.exact_duplicates: identical item rows and the amount they may count twice."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.clock import FixedClock
from app.core.config import IngestionLimits
from app.core.errors import DetectorConfigError
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.adapter import GaebAdapter
from app.models.dataset import Dataset, RowKind
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.normalization.builder import build_dataset
from app.validation.deterministic.exact_duplicates import (
    RULE_DUPLICATE,
    ExactDuplicatesConfig,
    ExactDuplicatesDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, number_cell, unit_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    resolve,
    run,
)

DETECTOR = ExactDuplicatesDetector


def _item(
    code: str = "01",
    description: str = "Aushub",
    quantity: object = "12",
    unit: object = None,
    total: object = "480.00",
) -> list[object]:
    return [code, description, quantity, unit or unit_cell("m3", "m3"), "40.00", total]


def _source_rows(dataset: Dataset, positions: list[int]) -> list[int]:
    table = dataset.tables[0]
    return [table.rows[p].source_row_number for p in positions]


@pytest.fixture
def code_defaults(boq_profile: DomainProfile) -> DomainProfile:
    """The BoQ profile without its settings for this check: the tests up to the BoQ section
    below pin the code defaults (compare whole tables, every column)."""
    defaults = dict(boq_profile.detector_defaults)
    del defaults[DETECTOR.spec.detector_id]
    return boq_profile.evolve(detector_defaults=defaults)


def test_distinct_rows_produce_no_findings(code_defaults: DomainProfile) -> None:
    dataset = boq_dataset(code_defaults, [_item("01"), _item("02")])
    result = run(DETECTOR, dataset, code_defaults)
    assert result.issues == []
    assert result.coverage["rows_checked"] == 2


def test_identical_rows_form_one_group(code_defaults: DomainProfile) -> None:
    rows = [
        _item(),
        _item("02", "Verfüllen"),
        _item(quantity="12.00", description="AUSHUB"),
        _item(unit=unit_cell("m³", "m3")),
    ]
    dataset = boq_dataset(code_defaults, rows)
    result = run(DETECTOR, dataset, code_defaults)
    [issue] = result.issues
    first, second, third = _source_rows(dataset, [0, 2, 3])
    assert issue.title == f"Rows {first}, {second} and {third} are identical"
    assert issue.rule_id == RULE_DUPLICATE
    assert issue.issue_category is IssueCategory.DUPLICATE
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.MEDIUM
    assert issue.row_id == dataset.tables[0].rows[2].row_id
    assert len(issue.affected_cells) == 18
    assert issue.estimated_financial_impact is None  # no explicit currency
    reference = issue.evidence[0]
    assert reference.kind is EvidenceKind.REFERENCE
    assert reference.data["rows"] == 3
    assert result.coverage["rows_duplicated"] == 2
    assert_well_formed(result.issues)


def test_rows_differing_only_in_code_are_not_duplicates(code_defaults: DomainProfile) -> None:
    dataset = boq_dataset(code_defaults, [_item("01"), _item("02")])
    assert run(DETECTOR, dataset, code_defaults).issues == []
    [issue] = run(DETECTOR, dataset, code_defaults, {"ignore_fields": ["item_code"]}).issues
    assert "(1 left out)" in issue.explanation
    by_header = run(DETECTOR, dataset, code_defaults, {"ignore_columns": [" POS. "]}).issues
    assert len(by_header) == 1


def test_case_sensitive_comparison(code_defaults: DomainProfile) -> None:
    dataset = boq_dataset(code_defaults, [_item(description="Aushub"), _item(description="aushub")])
    assert len(run(DETECTOR, dataset, code_defaults).issues) == 1
    assert run(DETECTOR, dataset, code_defaults, {"case_sensitive": True}).issues == []


def test_potential_double_count_in_an_explicit_currency(code_defaults: DomainProfile) -> None:
    builder = DatasetBuilder(code_defaults)
    table = builder.table("LV", BOQ_COLUMNS)
    total = number_cell("480.00", currency="EUR")
    table.row(_item(total=total))
    table.row(_item(total=total), in_totals=False)  # "nur EP": never counted
    table.row(_item(total=total))
    table.row(_item(total=total))
    result = run(DETECTOR, builder.build(), code_defaults)
    [issue] = result.issues
    impact = issue.estimated_financial_impact
    assert impact is not None
    assert impact.kind == "potential_double_count"
    assert impact.amount == Decimal("960.00") and impact.currency == "EUR"
    assert impact.basis == "potential double counting of 2 duplicated rows"
    assert "count it more than once" in issue.explanation


def test_sparse_rows_are_skipped(code_defaults: DomainProfile) -> None:
    rows = [[None, "Hinweis", None, None, None, None]] * 2
    result = run(DETECTOR, boq_dataset(code_defaults, rows), code_defaults)
    assert result.issues == []
    assert result.coverage["rows_skipped_too_few_values"] == 2
    loose = run(
        DETECTOR, boq_dataset(code_defaults, rows), code_defaults, {"min_non_empty_cells": 1}
    )
    assert len(loose.issues) == 1


def test_only_included_item_rows_are_compared(code_defaults: DomainProfile) -> None:
    builder = DatasetBuilder(code_defaults)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(_item())
    table.row(_item(), excluded=True)
    table.row([None, "Summe", None, None, None, "480.00"], kind=RowKind.SUBTOTAL)
    table.row([None, "Summe", None, None, None, "480.00"], kind=RowKind.SUBTOTAL)
    assert run(DETECTOR, builder.build(), code_defaults).issues == []


def test_config_applicability_and_registry(code_defaults: DomainProfile) -> None:
    config = resolve(DETECTOR, code_defaults)
    assert config.min_non_empty_cells == 2 and config.total_field == "line_total"
    assert ExactDuplicatesConfig.plannable_parameters() == {
        "ignore_fields",
        "ignore_columns",
        "max_cells_per_issue",
        "total_field",
    }
    for bad in ({"unknown": 1}, {"min_non_empty_cells": 0}, {"total_field": "Not An Id"}):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, code_defaults, bad)
    dataset = boq_dataset(code_defaults, [_item()])
    assert applicability(DETECTOR, dataset, code_defaults).applicable
    every_field = {"ignore_fields": [field for _, field in BOQ_COLUMNS if field]}
    assert not applicability(DETECTOR, dataset, code_defaults, every_field).applicable
    assert (
        "deterministic.exact_duplicates"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(code_defaults: DomainProfile) -> None:
    rows = [_item("01"), _item("01"), _item("02"), _item("02")]
    first = run(DETECTOR, boq_dataset(code_defaults, rows), code_defaults)
    second = run(DETECTOR, boq_dataset(code_defaults, rows), code_defaults)
    assert len(first.issues) == 2
    assert_unique_fingerprints(first.issues)
    assert [i.fingerprint for i in first.issues] == [i.fingerprint for i in second.issues]


# --------------------------------------------------------------------------- the BoQ settings
# Positions within one Titel (plan B2.7): the OZ and the GAEB element id are not compared, rows
# without a short text are not compared, and relative wording is read with its position.
LV_COLUMNS: list[tuple[str | None, str | None]] = [
    *BOQ_COLUMNS,
    ("Langtext", "long_description"),
    ("GAEB-ID", None),
]
GAEB_FIXTURES = Path(__file__).parents[3] / "fixtures" / "gaeb"
ZULAGE = "Zulage zu vorbeschriebener Position für Ecken"
Spec = list[Any] | tuple[list[Any], dict[str, Any]]


def _position(
    code: str,
    description: str | None = "Mauerwerk 24 cm",
    *,
    quantity: str = "12",
    long: str | None = None,
    element: str | None = None,
) -> list[Any]:
    total = number_cell(str(Decimal(quantity) * 40), currency="EUR")
    return [code, description, quantity, unit_cell("m3", "m3"), "40.00", total, long, element]


def _titel(code: str, level: int = 1) -> tuple[list[Any], dict[str, Any]]:
    values = [code, f"Titel {code}", None, None, None, None, None, None]
    return values, {"kind": RowKind.SECTION, "level": level, "code": code}


def _lv(profile: DomainProfile, *rows: Spec) -> Dataset:
    builder = DatasetBuilder(profile)
    table = builder.table("LV", LV_COLUMNS)
    for spec in rows:
        values, options = spec if isinstance(spec, tuple) else (spec, {})
        table.row(values, **options)
    return builder.build()


def _rows_of(dataset: Dataset, issue_rows: list[int]) -> list[int]:
    return [dataset.tables[0].rows[p].source_row_number for p in issue_rows]


def test_the_boq_profile_settings(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)
    assert config.ignore_fields == ["item_code"] and config.ignore_columns == ["GAEB-ID"]
    assert config.scope == "section" and config.required_fields == ["description"]
    assert config.relative_wording_fields == ["description", "long_description"]
    assert config.relative_wording_pattern is not None
    code = resolve(DETECTOR, boq_profile, {"ignore_fields": []})
    assert code.ignore_fields == []  # a plan may still compare the OZ


def test_a_position_repeated_under_a_new_oz_in_its_titel(boq_profile: DomainProfile) -> None:
    dataset = _lv(
        boq_profile,
        _titel("01"),
        _position("01.0010", element="ID_1"),
        _position("01.0020", "Verfüllen", element="ID_2"),
        _position("01.0030", element="ID_3"),  # 01.0010 again, under a new OZ and element id
        _titel("02"),
        _position("02.0010", element="ID_4"),  # the same text in another Titel
    )
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = result.issues
    table = dataset.tables[0]
    first, copy = _rows_of(dataset, [1, 3])
    assert issue.title == f"Rows {first} and {copy} are identical"
    assert issue.row_id == table.rows[3].row_id
    assert {table.row(c.row_id).source_row_number for c in issue.affected_cells} == {first, copy}
    compared = {c.column_id for c in issue.affected_cells}
    for header in ("Pos.", "GAEB-ID", "Langtext"):  # not compared, or empty
        column = next(col for col in table.columns if col.original_header == header)
        assert column.column_id not in compared
    assert f"'LV' rows {first} and {copy}, all in section 01, hold the same value" in (
        issue.explanation
    )
    assert "(2 left out)" in issue.explanation
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.kind == "potential_double_count"
    assert impact.amount == Decimal("480") and impact.currency == "EUR"
    assert issue.evidence[0].data["scope"] == "section"
    assert issue.evidence[0].data["relative_wording"] is False
    assert issue.suggested_action == (
        "Check whether the same item was entered twice by mistake or is meant to be repeated. "
        "If the document comes from someone else, ask its author which rows are meant instead "
        "of deleting one yourself."
    )
    assert_well_formed(result.issues)


def test_the_same_position_in_two_buildings_is_not_a_duplicate(
    boq_profile: DomainProfile,
) -> None:
    rows: list[Spec] = [
        _titel("01"),  # Los 01 Haus A
        _titel("01.01", level=2),
        _position("01.01.0010"),
        _titel("02"),  # Los 02 Haus B
        _titel("02.01", level=2),
        _position("02.01.0010"),
    ]
    dataset = _lv(boq_profile, *rows)
    assert run(DETECTOR, dataset, boq_profile).issues == []
    whole_table = run(DETECTOR, dataset, boq_profile, {"scope": "table"}).issues
    assert len(whole_table) == 1 and "all in section" not in whole_table[0].explanation


def test_a_section_code_with_letters_is_not_quoted(boq_profile: DomainProfile) -> None:
    dataset = _lv(boq_profile, _titel("PER89"), _position("1"), _position("2"))
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert ", all in one section, hold the same value" in issue.explanation
    assert "PER89" not in issue.explanation


def test_a_page_break_does_not_end_the_titel(boq_profile: DomainProfile) -> None:
    carried = [None, "Übertrag", None, None, None, number_cell("480.00"), None, None]
    dataset = _lv(
        boq_profile,
        _titel("01"),
        _position("01.0010"),
        (carried, {"kind": RowKind.CARRY_FORWARD}),
        _position("01.0020"),  # the same position on the next page
    )
    assert len(run(DETECTOR, dataset, boq_profile).issues) == 1


def test_rows_without_a_short_text_are_not_compared(boq_profile: DomainProfile) -> None:
    dataset = _lv(boq_profile, _titel("01"), _position("01.0010", None), _position("01.0020", None))
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["rows_skipped_required_value_empty"] == 2
    assert len(run(DETECTOR, dataset, boq_profile, {"required_fields": []}).issues) == 1


def test_a_table_without_short_texts_is_not_compared(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    columns = [column for column in BOQ_COLUMNS if column[1] != "description"]
    table = builder.table("Angebot", columns)
    for code in ("01.0010", "01.0020"):
        table.row([code, "12", unit_cell("m3", "m3"), "40.00", "480.00"])
    result = run(DETECTOR, builder.build(), boq_profile)
    assert result.issues == []
    assert result.coverage["tables_skipped_required_field_unmapped"] == 1
    assert any("'Angebot'" in note and "not mapped" in note for note in result.notes)


def test_relative_wording_is_read_with_the_position_it_refers_to(
    boq_profile: DomainProfile,
) -> None:
    rows: list[Spec] = [
        _titel("01"),
        _position("01.0010", "Mauerwerk 24 cm"),
        _position("01.0020", ZULAGE, quantity="4"),  # Ecken of 01.0010
        _position("01.0030", "Mauerwerk 36,5 cm"),
        _position("01.0040", ZULAGE, quantity="4"),  # Ecken of 01.0030: other work
    ]
    result = run(DETECTOR, _lv(boq_profile, *rows), boq_profile)
    assert result.issues == []
    assert result.coverage["rows_with_relative_wording"] == 2
    # Compared without the setting, the two Zulagen are copies of each other.
    loose = run(DETECTOR, _lv(boq_profile, *rows), boq_profile, {"relative_wording_pattern": None})
    assert len(loose.issues) == 1

    copied = _lv(boq_profile, *rows, _position("01.0050", ZULAGE, quantity="4"))
    [issue] = run(DETECTOR, copied, boq_profile).issues  # the Zulage entered twice
    assert issue.row_id == copied.tables[0].rows[5].row_id
    assert "refers to the row before them, and those rows are identical too" in (issue.explanation)
    assert issue.evidence[0].data["relative_wording"] is True


def test_a_copied_block_with_relative_wording_is_found_twice(boq_profile: DomainProfile) -> None:
    dataset = _lv(
        boq_profile,
        _titel("01"),
        _position("01.0010"),
        _position("01.0020", ZULAGE, quantity="4"),
        _position("01.0030", "Mauerwerk 36,5 cm"),
        _position("01.0040"),  # the block of 01.0010 and 01.0020 entered again
        _position("01.0050", ZULAGE, quantity="4"),
    )
    issues = run(DETECTOR, dataset, boq_profile).issues
    table = dataset.tables[0]
    assert [table.row(i.row_id).source_row_number for i in issues if i.row_id] == _rows_of(
        dataset, [4, 5]
    )


def test_relative_wording_in_the_long_text(boq_profile: DomainProfile) -> None:
    rows: list[Spec] = [
        _titel("01"),
        _position("01.0010", "Mauerwerk 24 cm"),
        _position("01.0020", "Zulage Ecken", quantity="4", long="wie vor, jedoch Ecken"),
        _position("01.0030", "Mauerwerk 36,5 cm"),
        _position("01.0040", "Zulage Ecken", quantity="4", long="wie vor, jedoch Ecken"),
    ]
    assert run(DETECTOR, _lv(boq_profile, *rows), boq_profile).issues == []
    short_only = {"relative_wording_fields": ["description"]}
    assert len(run(DETECTOR, _lv(boq_profile, *rows), boq_profile, short_only).issues) == 1


def test_relative_wording_at_the_start_of_a_titel(boq_profile: DomainProfile) -> None:
    dataset = _lv(
        boq_profile,
        _position("00.0010"),  # before the Titel: another scope
        _titel("01"),
        _position("01.0010", ZULAGE, quantity="4"),
        _position("01.0020", ZULAGE, quantity="4"),
    )
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert "refers to a row before them, but none comes before them in their section" in (
        issue.explanation
    )


def test_a_gaeb_call_for_bids_with_a_repeated_position(
    tmp_path: Path, boq_profile: DomainProfile
) -> None:
    text = (GAEB_FIXTURES / "small.x83").read_text(encoding="utf-8")
    start, end = text.index('<Item ID="I1"'), text.index("</Item>") + len("</Item>")
    again = text[start:end].replace('ID="I1" RNoPart="0010"', 'ID="I2" RNoPart="0020"')
    path = tmp_path / "bill.x83"
    path.write_text(text[:end] + again + text[end:], encoding="utf-8")
    dataset = _gaeb(path, "83", boq_profile)
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    oz = dataset.tables[0].column_for_field("item_code")
    assert oz is not None and oz.column_id not in {c.column_id for c in issue.affected_cells}
    assert "all in section 01," in issue.explanation


def test_a_gaeb_bid_without_texts_is_not_compared(
    tmp_path: Path, boq_profile: DomainProfile
) -> None:
    text = (GAEB_FIXTURES / "small.x84").read_text(encoding="utf-8")
    start, end = text.index('<Item ID="I1"'), text.index("</Item>") + len("</Item>")
    again = text[start:end].replace('ID="I1" RNoPart="0010"', 'ID="I2" RNoPart="0020"')
    path = tmp_path / "bid.x84"
    path.write_text(text[:end] + again + text[end:], encoding="utf-8")
    dataset = _gaeb(path, "84", boq_profile)
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["rows_skipped_required_value_empty"] == 2
    assert len(run(DETECTOR, dataset, boq_profile, {"required_fields": []}).issues) == 1


def _gaeb(path: Path, phase: str, profile: DomainProfile) -> Dataset:
    raw = GaebAdapter(phase).extract(path, IngestionLimits())
    return build_dataset(
        raw, profile=profile, document_id="doc", ids=SequentialIdFactory(), clock=FixedClock()
    )


def test_new_settings_are_validated(code_defaults: DomainProfile) -> None:
    config = resolve(DETECTOR, code_defaults)
    assert config.scope == "table" and config.required_fields == []
    assert config.relative_wording_pattern is None
    assert config.relative_wording_fields == ["description"]
    for bad in (
        {"scope": "page"},
        {"required_fields": ["Not An Id"]},
        {"relative_wording_pattern": "(wie"},
        {"relative_wording_pattern": "(wie vor)?"},  # matches every text
        {"relative_wording_fields": ["Not An Id"]},
    ):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, code_defaults, bad)
