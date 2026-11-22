"""The item frame: one record per item row of the tables that map a unit price, read through
the context's accessors (markers and ambiguous numbers stay None), cached per run."""

from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal

import numpy as np
import pytest

from app.models.dataset import RowKind
from app.models.profile import DomainProfile
from app.validation.contracts.context import ValidationContext
from app.validation.support.items import (
    FLAG_COLUMNS,
    ITEM_FRAME_KEY,
    NUMBER_COLUMNS,
    TEXT_COLUMNS,
    ItemFields,
    ItemFrame,
    item_frame,
)
from tests.support.builders import (
    DatasetBuilder,
    ambiguous_cell,
    failed_number_cell,
    make_context,
    number_cell,
    text_cell,
)

D = Decimal
COLUMNS = [
    ("OZ", "item_code"),
    ("Kurztext", "description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
    ("EP", "unit_price"),
    ("GP", "line_total"),
    ("Art", "item_type"),
]


@pytest.fixture
def context(boq_profile: DomainProfile) -> ValidationContext:
    builder = DatasetBuilder(boq_profile)
    bill = builder.table("LV", COLUMNS)
    bill.row(["01", "Rohbau", None, None, None, None, None], kind=RowKind.SECTION)  # 0
    bill.row(["01.0010", "Beton  C25/30 für Wände", "12.5", "m3", "145.80", "1822.50", None])
    bill.row(["01.0020", "Mauerwerk KS 24 cm", "Incl.", "m2", "54.80", "-", None])  # 2 markers
    bill.row(["01.0030", "Schalung", "30", "m2", ambiguous_cell("1.234"), "nur EP", None])
    bill.row(["01.0040", "Dübel", "4", "100 St", "250.00", "1000.00", None])  # 4 multiplier
    bill.row(["01.0050", "Alternativ: Fertigteil", "2", "St", "900", "1800", "A"], in_totals=False)
    bill.row(["01.0060", "Bedarfsposition Wasser", "1", "psch", "0", "0", "B"], in_totals=None)
    bill.row(["01.0070", "Gutschrift", "1", "psch", "-150.00", "-150.00", None])  # 7 credit
    bill.row(["01.0080", "Ausgeschlossen", "1", "St", "5", "5", None], excluded=True)
    bill.row([None, "Summe Titel 01", None, None, None, "3622.50", None], kind=RowKind.SUBTOTAL)
    bill.row(["02.0010", "Gerüst", "100", "m2", failed_number_cell("ca. 8"), None, None])  # 10
    scanned = builder.table("Scan", COLUMNS)
    scanned.row(
        [
            text_cell("01.0010", confidence=0.99),
            text_cell("Beton C25/30", confidence=0.99),
            number_cell("10", confidence=0.5),  # an engine score below the 0.9 threshold
            text_cell("m3", confidence=0.99),
            number_cell("140.00", confidence=0.95),
            number_cell("1400.00", confidence=0.95),
            None,
        ]
    )
    notes = builder.table("Notes", [("Text", "description"), ("Qty", "quantity")])
    notes.row(["Bauzeit", "12"])  # no unit price mapped: not an item table here
    partial = builder.table("Partial", [("Rate", "unit_price"), ("Amount", "line_total")])
    partial.row(["10.00", "10.00"])
    return make_context(builder.build(), boq_profile)


def _by_code(frame: ItemFrame) -> dict[str | None, object]:
    return {record.item_code: record for record in frame.records}


def test_one_record_per_item_row_of_the_priced_tables(context: ValidationContext) -> None:
    frame = item_frame(context)
    lv, scan, _, partial = context.tables()
    assert [(r.table_id, r.item_code) for r in frame.records] == [
        (lv.table_id, "01.0010"),
        (lv.table_id, "01.0020"),
        (lv.table_id, "01.0030"),
        (lv.table_id, "01.0040"),
        (lv.table_id, "01.0050"),
        (lv.table_id, "01.0060"),
        (lv.table_id, "01.0070"),
        (lv.table_id, "02.0010"),  # sections, subtotals and the excluded row are left out
        (scan.table_id, "01.0010"),
        (partial.table_id, None),
    ]
    assert [r.position for r in frame.records] == list(range(10))
    assert len(frame) == 10
    first = frame.records[0]
    assert first.row_id == lv.rows[1].row_id
    assert frame.record(lv.table_id, lv.rows[1].row_id) is first
    assert frame.record(lv.table_id, lv.rows[8].row_id) is None  # excluded
    assert frame.record("tbl_unknown", "row_unknown") is None


def test_exact_values_and_keys(context: ValidationContext) -> None:
    concrete = item_frame(context).records[0]
    assert concrete.description == "Beton C25/30 für Wände"  # the normalized text
    assert concrete.description_key == "beton c25/30 für wände"
    assert (concrete.quantity, concrete.unit_price, concrete.line_total) == (
        D("12.5"),
        D("145.80"),
        D("1822.50"),
    )
    assert isinstance(concrete.unit_price, Decimal)
    assert (concrete.unit_id, concrete.dimension, concrete.multiplier) == ("m3", "volume", None)
    assert concrete.unit_price_per_base_unit == D("145.80")
    assert concrete.standard_text_key is None  # not mapped in this table
    assert concrete.long_description is None  # not mapped either
    assert (concrete.discount_percent, concrete.discount_factor) == (None, D(1))  # no discount
    assert concrete.item_type is None
    assert concrete.verified


def test_markers_and_unusable_numbers_stay_none(context: ValidationContext) -> None:
    records = item_frame(context).records
    masonry, formwork, scaffold = records[1], records[2], records[7]
    assert masonry.quantity is None and masonry.line_total is None  # "Incl." and "-" markers
    assert masonry.unit_price == D("54.80")
    assert formwork.unit_price is None  # ambiguous "1.234"
    assert formwork.unit_price_per_base_unit is None
    assert formwork.line_total is None  # "nur EP" is a marker, not a number
    assert scaffold.unit_price is None  # "ca. 8" did not parse
    assert scaffold.line_total is None  # empty


def test_unit_multipliers_give_the_price_per_base_unit(context: ValidationContext) -> None:
    anchors = item_frame(context).records[3]
    assert (anchors.unit_id, anchors.dimension) == ("pcs", "count")
    assert anchors.multiplier == D("100")
    assert anchors.unit_price == D("250.00")  # as written: per 100 pieces
    assert anchors.unit_price_per_base_unit == D("2.50")


def test_counts_toward_totals_item_type_and_sections(context: ValidationContext) -> None:
    records = item_frame(context).records
    lv = context.tables()[0]
    section_id = lv.rows[0].row_id
    assert [r.counts_toward_totals for r in records[:7]] == [
        True,
        True,
        True,
        True,
        False,
        None,
        True,
    ]
    assert (records[4].item_type, records[5].item_type) == ("A", "B")
    assert all(r.section_row_id == section_id for r in records[:7])
    assert records[7].section_row_id is None  # after the subtotal that closed the section
    assert records[0].section_path == (section_id,)
    assert records[8].section_row_id is None and records[8].section_path == ()


def test_verified_cells(context: ValidationContext) -> None:
    records = item_frame(context).records
    assert all(record.verified for record in records if record.table_id != records[8].table_id)
    assert not records[8].verified  # one OCR cell below the threshold
    lenient = make_context(context.dataset, context.profile, low_confidence_threshold=0.4)
    assert item_frame(lenient).records[8].verified


def test_cell_references(context: ValidationContext) -> None:
    lv = context.tables()[0]
    concrete = item_frame(context).records[0]
    price = concrete.cell("unit_price")
    assert price is not None
    assert (price.table_id, price.row_id) == (lv.table_id, lv.rows[1].row_id)
    assert price.column_id == lv.column_for_field("unit_price").column_id
    assert price.source is not None and price.source.row_number == 3
    assert set(concrete.cells) == {
        "item_code",
        "description",
        "quantity",
        "unit",
        "unit_price",
        "line_total",
        "item_type",
    }
    assert concrete.cell("standard_text_key") is None
    partial = item_frame(context).records[9]
    assert set(partial.cells) == {"unit_price", "line_total"}
    assert partial.description is None and partial.unit_id is None
    with pytest.raises(TypeError):
        concrete.cells["x"] = price  # type: ignore[index]  # read-only on purpose: tested here


GAEB_COLUMNS = [
    ("OZ", "item_code"),
    ("Kurztext", "description"),
    ("Langtext", "long_description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
    ("EP", "unit_price"),
    ("Nachlass %", "discount_percent"),
    ("GP", "line_total"),
]


def test_the_long_description_and_the_item_discount(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    bill = builder.table("LV", GAEB_COLUMNS)
    long_text = "Beton C25/30 für Wände, d = 24 cm, Sichtbeton SB2"
    bill.row(["01.0010", "Beton", long_text, "10", "m3", "100.00", "1.5", "985.00"])
    three_percent = number_cell("0.03", raw="3 %", percent=True)  # already divided by 100
    bill.row(["01.0020", "Schalung", None, "10", "m2", "20.00", three_percent, "194.00"])
    bill.row(["01.0030", "Bewehrung", None, "1", "t", "900.00", None, "900.00"])  # none stated
    bill.row(["01.0040", "Dämmung", None, "5", "m2", "10.00", "0", "50.00"])
    bill.row(["01.0050", "Abdichtung", None, "5", "m2", "10.00", "ca. 2", "49.00"])  # unusable
    records = item_frame(make_context(builder.build(), boq_profile)).records
    assert records[0].long_description == long_text
    assert records[1].long_description is None
    assert [(r.discount_percent, r.discount_factor) for r in records] == [
        (D("1.5"), D("0.985")),
        (D("3"), D("0.97")),
        (None, D(1)),
        (D(0), D(1)),
        (None, None),  # an amount that depends on the discount is not computed
    ]
    assert all(isinstance(r.discount_factor, Decimal) for r in records[:4])
    # The factor is what the line total took: round(10 x 100.00) x 0.985 = 985.00.
    concrete = records[0]
    assert concrete.quantity is not None and concrete.unit_price is not None
    assert concrete.quantity * concrete.unit_price * D("0.985") == concrete.line_total
    assert {"long_description", "discount_percent"} <= set(concrete.cells)


def test_the_data_frame_mirrors_the_records(context: ValidationContext) -> None:
    items = item_frame(context)
    frame = items.frame
    assert list(frame.columns) == [*TEXT_COLUMNS, *NUMBER_COLUMNS, *FLAG_COLUMNS]
    assert list(frame.index) == list(range(len(items)))
    for name in NUMBER_COLUMNS:
        assert frame[name].dtype == np.float64, name
    assert frame.loc[0, "unit_price"] == 145.80
    assert frame.loc[0, "quantity"] == 12.5
    assert math.isnan(frame.loc[1, "quantity"])  # marker
    assert math.isnan(frame.loc[2, "unit_price"])  # ambiguous
    assert frame.loc[3, "unit_price_per_base_unit"] == 2.5
    assert frame.loc[3, "multiplier"] == 100.0
    assert frame.loc[0, "log_price"] == pytest.approx(math.log(145.80))
    assert frame.loc[3, "log_price"] == pytest.approx(math.log(2.5))
    for position in (2, 5, 6, 7):  # no price, a price of 0, a credit, no price
        assert math.isnan(frame.loc[position, "log_price"]), position
    assert frame.loc[0, "description_key"] == "beton c25/30 für wände"
    assert frame.loc[0, "unit_id"] == "m3"
    assert frame["standard_text_key"].isna().all()  # not mapped
    flags = frame["counts_toward_totals"]
    assert flags.isna().tolist() == [False] * 5 + [True] + [False] * 4  # undecided
    assert flags.dropna().tolist() == [True, True, True, True, False, True, True, True, True]
    assert list(frame["verified"]) == [True] * 8 + [False, True]


def test_changes_to_a_frame_copy_do_not_reach_the_cache(context: ValidationContext) -> None:
    copy = item_frame(context).frame
    copy.loc[0, "unit_price"] = -1.0
    copy["extra"] = 1
    again = item_frame(context).frame
    assert again.loc[0, "unit_price"] == 145.80
    assert "extra" not in again.columns


def test_built_once_per_run_and_shared_by_the_context_copies(
    context: ValidationContext, boq_profile: DomainProfile
) -> None:
    first = item_frame(context)
    assert context.memo[ITEM_FRAME_KEY] is first
    assert item_frame(context) is first
    per_detector = replace(context, deadline=None)  # the pipeline's per-step copy
    assert item_frame(per_detector) is first
    other_run = make_context(context.dataset, boq_profile)
    assert item_frame(other_run) is not first
    assert item_frame(other_run).records == first.records


def test_other_fields_are_cached_apart(context: ValidationContext) -> None:
    default = item_frame(context)
    codes_as_text = ItemFields(description="item_code", unit="unit")
    other = item_frame(context, codes_as_text)
    assert other is not default
    assert other.records[0].description == "01.0010"
    assert item_frame(context, ItemFields(description="item_code", unit="unit")) is other
    assert item_frame(context) is default
    assert item_frame(context, ItemFields()) is default  # equal to the default fields
    assert context.memo[(ITEM_FRAME_KEY, codes_as_text)] is other


def test_no_priced_table_gives_an_empty_frame(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    builder.table("Notes", [("Text", "description"), ("Qty", "quantity")]).row(["x", "1"])
    items = item_frame(make_context(builder.build(), boq_profile))
    assert items.records == ()
    frame = items.frame
    assert len(frame) == 0
    assert list(frame.columns) == [*TEXT_COLUMNS, *NUMBER_COLUMNS, *FLAG_COLUMNS]
    assert all(frame[name].dtype == np.float64 for name in NUMBER_COLUMNS)


def test_a_price_per_unit_that_does_not_divide_evenly(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    builder.table("LV", COLUMNS).row(["1", "Anker", "3", "3 St", "10.00", "10.00", None])
    record = item_frame(make_context(builder.build(), boq_profile)).records[0]
    assert record.multiplier == D("3")
    assert record.unit_price_per_base_unit == D("3.333333333333333333333333333")
