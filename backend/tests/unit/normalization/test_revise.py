"""Manual cell corrections create the next revision of a dataset (ADR 0001)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.errors import InvalidInputError, NotFoundError
from app.models.dataset import Dataset, Table
from app.models.profile import DomainProfile
from app.models.values import DataType, NumberValue, ParseStatus
from app.normalization.revise import CellCorrection, revise
from tests.unit.normalization.raw_builders import (
    GERMAN_LV,
    by_source_row,
    normalize,
    sheet,
    workbook,
)

LATER = datetime(2026, 2, 1, tzinfo=UTC)


@pytest.fixture
def dataset(boq_profile: DomainProfile) -> Dataset:
    return normalize(workbook(sheet(GERMAN_LV)), boq_profile)


def _fix(table: Table, row: int, field_id: str, text: str) -> CellCorrection:
    column = table.column_for_field(field_id)
    assert column is not None
    return CellCorrection(table.table_id, by_source_row(table)[row].row_id, column.column_id, text)


def _cell(dataset: Dataset, row: int, field_id: str):  # type: ignore[no-untyped-def]
    table = dataset.tables[0]
    column = table.column_for_field(field_id)
    assert column is not None
    return by_source_row(table)[row].cells[column.column_id]


def test_a_number_is_read_like_an_upload_and_becomes_the_next_revision(
    dataset: Dataset, boq_profile: DomainProfile
) -> None:
    table = dataset.tables[0]
    revised, applied = revise(
        dataset, [_fix(table, 7, "quantity", "1.300,25")], profile=boq_profile, created_at=LATER
    )
    assert (revised.revision, revised.parent_revision) == (2, 1)
    assert revised.dataset_id == dataset.dataset_id and revised.created_at == LATER
    cell = _cell(revised, 7, "quantity")
    assert cell.raw_value == "1.300,25" and cell.data_type is DataType.NUMBER
    assert isinstance(cell.parsed_value, NumberValue)
    assert cell.parsed_value.value == Decimal("1300.25")
    assert cell.source == _cell(dataset, 7, "quantity").source
    [change] = applied
    assert change.before.raw_value == "1.250,50" and change.after == cell
    assert change.reference == "C7" and change.table_name == table.name
    # ids and every other cell stay the same; the old revision is untouched
    old_rows, new_rows = by_source_row(table), by_source_row(revised.tables[0])
    assert old_rows.keys() == new_rows.keys()
    for number, row in old_rows.items():
        assert new_rows[number].row_id == row.row_id
        for column_id, old in row.cells.items():
            if (number, column_id) != (7, table.column_for_field("quantity").column_id):  # type: ignore[union-attr]
                assert new_rows[number].cells[column_id] == old
    assert _cell(dataset, 7, "quantity").raw_value == "1.250,50"
    assert revised.tables[0].rows[0].classification == table.rows[0].classification


def test_an_ambiguous_number_takes_the_columns_decimal_separator(
    dataset: Dataset, boq_profile: DomainProfile
) -> None:
    table = dataset.tables[0]
    column = table.column_for_field("quantity")
    assert column is not None and column.decimal_separator == ","
    revised, _ = revise(
        dataset, [_fix(table, 9, "quantity", "1,500")], profile=boq_profile, created_at=LATER
    )
    cell = _cell(revised, 9, "quantity")
    assert cell.parse_status is ParseStatus.INFERRED
    assert isinstance(cell.parsed_value, NumberValue)
    assert cell.parsed_value.value == Decimal("1.5")
    assert cell.parse_note == "Decimal separator ',' as used in this column."


def test_text_that_is_not_a_number_is_kept_as_failed(
    dataset: Dataset, boq_profile: DomainProfile
) -> None:
    table = dataset.tables[0]
    revised, _ = revise(
        dataset, [_fix(table, 9, "quantity", "abc")], profile=boq_profile, created_at=LATER
    )
    cell = _cell(revised, 9, "quantity")
    assert cell.raw_value == "abc" and cell.parse_status is ParseStatus.FAILED


def test_units_text_and_empty_cells(dataset: Dataset, boq_profile: DomainProfile) -> None:
    table = dataset.tables[0]
    revised, applied = revise(
        dataset,
        [
            _fix(table, 7, "unit", "m3"),
            _fix(table, 7, "description", "Oberboden abtragen und lagern"),
            _fix(table, 9, "unit_price", ""),
        ],
        profile=boq_profile,
        created_at=LATER,
    )
    assert len(applied) == 3
    unit = _cell(revised, 7, "unit")
    assert unit.raw_value == "m3" and unit.normalized_value is not None
    assert _cell(revised, 7, "description").raw_value == "Oberboden abtragen und lagern"
    assert _cell(revised, 9, "unit_price").data_type is DataType.EMPTY


def test_the_same_text_changes_nothing(dataset: Dataset, boq_profile: DomainProfile) -> None:
    table = dataset.tables[0]
    revised, applied = revise(
        dataset, [_fix(table, 7, "quantity", "1.250,50")], profile=boq_profile, created_at=LATER
    )
    assert revised is dataset and applied == []


def test_unknown_ids_and_duplicates_are_rejected(
    dataset: Dataset, boq_profile: DomainProfile
) -> None:
    table = dataset.tables[0]
    fix = _fix(table, 7, "quantity", "2")
    with pytest.raises(InvalidInputError):
        revise(dataset, [fix, fix], profile=boq_profile, created_at=LATER)
    for wrong in (
        CellCorrection("tbl_nope", fix.row_id, fix.column_id, "2"),
        CellCorrection(fix.table_id, "row_nope", fix.column_id, "2"),
        CellCorrection(fix.table_id, fix.row_id, "col_nope", "2"),
    ):
        with pytest.raises(NotFoundError):
            revise(dataset, [wrong], profile=boq_profile, created_at=LATER)
