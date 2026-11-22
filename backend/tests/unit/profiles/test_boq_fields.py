"""The optional BoQ fields of the profile (since 1.3.0): the standard text key (STLB-Bau),
which only a file's declared structure (a GAEB bill) or a reviewer maps, and the six unit price
components (GAEB Preisanteile; components 1 to 4 are the columns of VHB Formblatt 223), which
only a reviewer maps. No header maps any of them."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.dataset import MappingMethod
from app.models.profile import DomainProfile, FieldRole
from app.models.schema import SchemaDecisions, TableDecisions
from app.models.values import DataType
from app.validation.deterministic.line_total import LineTotalDetector
from app.validation.domain.boq.bid_prices import BoqBidPricesDetector
from app.validation.support.items import item_frame
from tests.support.builders import make_context
from tests.unit.normalization.raw_builders import normalize, sheet, workbook
from tests.unit.validation.deterministic.references_fixtures import run

COMPONENTS = [f"unit_price_component_{n}" for n in range(1, 7)]


def test_the_profile_version_and_the_new_fields(boq_profile: DomainProfile) -> None:
    # 1.6.0: step B2 (the totals rules read the GAEB position kinds, duplicates are compared
    # within a Titel, the unit price prevails in line_total, and the bid price settings and the
    # not_offered marker are new; 1.4.0 on its branch, 1.5.0 with main's tender review checks)
    # merged with main's 1.5.0 (explicit price context for the history pilot), so a dataset
    # records which reading it was built with.
    assert boq_profile.version == "1.8.0"
    # The GAEB import's field holds the key; B0's standard_reference was dropped for it.
    assert boq_profile.field("standard_reference") is None
    key = boq_profile.field("standard_text_key")
    assert key is not None
    assert (key.data_type, key.role, key.required, key.match_headers) == (
        DataType.TEXT,
        FieldRole.OTHER,
        False,
        False,
    )
    assert key.header_synonyms == key.exact_header_synonyms == []
    for field_id in COMPONENTS:
        component = boq_profile.field(field_id)
        assert component is not None, field_id
        assert (
            component.data_type,
            component.role,
            component.required,
            component.match_headers,
        ) == (DataType.NUMBER, FieldRole.MONETARY, False, False)
        assert component.header_synonyms == component.exact_header_synonyms == []


FORMBLATT_223 = [
    "OZ",
    "Kurztext",
    "STLB-Bau",
    "Menge",
    "ME",
    "EP",
    "GP",
    "Lohn",
    "Stoffe",
    "Geräte",
    "Sonstiges",
    "EP-Anteil 5",
    "EP-Anteil 6",
]


PRICE_BREAKDOWN_ROWS = [
    FORMBLATT_223,
    [
        "01.0010",
        "Beton C25/30 für Wände",
        "013.456.789",
        "12.5",
        "m3",
        "145.80",
        "1822.50",
        "60.00",
        "70.00",
        "10.00",
        "5.80",
        "0",
        "0",
    ],
]
# What a reviewer maps in that layout (source column -> field).
REVIEWER_COLUMNS: dict[int, str | None] = {
    3: "standard_text_key",
    **{8 + k: f"unit_price_component_{k + 1}" for k in range(6)},
}


def test_only_the_basic_columns_of_a_price_breakdown_map_by_header(
    boq_profile: DomainProfile,
) -> None:
    table = normalize(workbook(sheet(PRICE_BREAKDOWN_ROWS)), boq_profile).tables[0]
    mapped = {
        column.original_header: column.mapping
        for column in table.columns
        if column.mapping is not None
    }
    assert {header: m.field_id for header, m in mapped.items()} == {
        "OZ": "item_code",
        "Kurztext": "description",
        "Menge": "quantity",
        "ME": "unit",
        "EP": "unit_price",
        "GP": "line_total",
    }
    assert {m.method for m in mapped.values()} == {MappingMethod.HEADER_EXACT}
    # The key and the components are never matched by their headers.
    for field_id in ("standard_text_key", *COMPONENTS):
        assert table.column_for_field(field_id) is None, field_id


def test_a_reviewer_maps_the_key_and_the_components(boq_profile: DomainProfile) -> None:
    reviewer = SchemaDecisions(
        tables=[TableDecisions(sheet_index=0, column_fields=REVIEWER_COLUMNS)]
    )
    dataset = normalize(workbook(sheet(PRICE_BREAKDOWN_ROWS)), boq_profile, decisions=reviewer)
    table = dataset.tables[0]
    by_field = {
        column.mapping.field_id: (column.original_header, column.mapping.method)
        for column in table.columns
        if column.mapping is not None
    }
    user = MappingMethod.USER
    assert {field_id: by_field[field_id] for field_id in ("standard_text_key", *COMPONENTS)} == {
        "standard_text_key": ("STLB-Bau", user),
        "unit_price_component_1": ("Lohn", user),
        "unit_price_component_2": ("Stoffe", user),
        "unit_price_component_3": ("Geräte", user),
        "unit_price_component_4": ("Sonstiges", user),
        "unit_price_component_5": ("EP-Anteil 5", user),
        "unit_price_component_6": ("EP-Anteil 6", user),
    }
    context = make_context(dataset, boq_profile)
    row = table.rows[0]
    assert context.number(table, row, "unit_price_component_2") == Decimal("70.00")
    assert context.text(table, row, "standard_text_key") == "013.456.789"


@pytest.mark.parametrize(
    "header", ["STLB-Bau", "STLB", "STL-Nr.", "Standardleistung", "Standardtext"]
)
def test_no_header_maps_the_standard_text_key(boq_profile: DomainProfile, header: str) -> None:
    rows = [["OZ", "Kurztext", "EP", header], ["1", "Beton", "10.00", "013.456.789"]]
    table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
    assert table.column_for_field("standard_text_key") is None
    assert next(c for c in table.columns if c.original_header == header).mapping is None


@pytest.mark.parametrize(
    "header",
    ["EP-Anteil 1", "Preisanteil 3", "EP-Anteil 4", "Lohn", "Stoffe", "Geräte", "Sonstiges"],
)
def test_no_header_maps_a_unit_price_component(boq_profile: DomainProfile, header: str) -> None:
    rows = [["OZ", "Kurztext", "EP", header], ["1", "Beton", "10.00", "1"]]
    table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
    assert all(table.column_for_field(field_id) is None for field_id in COMPONENTS)
    assert next(c for c in table.columns if c.original_header == header).mapping is None


def test_the_item_frame_reads_a_key_column_a_reviewer_maps(boq_profile: DomainProfile) -> None:
    rows = [
        ["OZ", "Kurztext", "STLB-Bau", "Menge", "ME", "EP", "GP"],
        ["01.0010", "Beton", "013.456.789", "2", "m3", "100.00", "200.00"],
        ["01.0020", "Schalung", None, "3", "m2", "20.00", "60.00"],
    ]
    unmapped = normalize(workbook(sheet(rows)), boq_profile)
    records = item_frame(make_context(unmapped, boq_profile)).records
    assert [r.standard_text_key for r in records] == [None, None]
    reviewer = SchemaDecisions(
        tables=[TableDecisions(sheet_index=0, column_fields={3: "standard_text_key"})]
    )
    dataset = normalize(workbook(sheet(rows)), boq_profile, decisions=reviewer)
    column = dataset.tables[0].column_for_field("standard_text_key")
    assert column is not None and column.original_header == "STLB-Bau"
    assert column.mapping is not None and column.mapping.method is MappingMethod.USER
    records = item_frame(make_context(dataset, boq_profile)).records
    assert [r.standard_text_key for r in records] == ["013.456.789", None]
    assert records[0].cell("standard_text_key") is not None


@pytest.mark.parametrize("header", ["Nachlass %", "Positionsnachlass %", "item discount %"])
def test_explicit_item_discounts_feed_line_total_checks(boq_profile, header) -> None:
    rows = [
        ["OZ", "Kurztext", "Menge", "ME", "EP", "GP", header],
        ["1.10", "Rohr", "3", "m", "21.34", "60.82", "5"],
        ["1.20", "Bogen", "2", "St", "47.25", "94.50", "7.5"],
        ["1.30", "Ventil", "1", "St", "58.00", "58.00", None],
    ]
    dataset = normalize(workbook(sheet(rows)), boq_profile)
    [issue] = run(LineTotalDetector, dataset, boq_profile).issues
    assert issue.row_id == dataset.tables[0].rows[1].row_id
    assert issue.expected_value == "87.41"


@pytest.mark.parametrize(
    "header",
    [
        "Nachlass",
        "Rabatt",
        "Rabatt %",
        "Nachlass EUR",
        "Nachlass % gesamt",
        "item discount",
        "item discounts %",
        "discount_percent",
    ],
)
def test_ambiguous_or_similar_discount_headers_stay_unmapped(boq_profile, header) -> None:
    rows = [["OZ", "Kurztext", "EP", header], ["1", "Rohr", "10.00", "5"]]
    table = normalize(workbook(sheet(rows)), boq_profile).tables[0]
    assert table.column_for_field("discount_percent") is None


@pytest.mark.parametrize("suffix", ["", "%"])
def test_item_discount_cannot_exceed_the_whole_price(boq_profile, suffix) -> None:
    rows = [
        ["OZ", "Kurztext", "EP", "Nachlass %"],
        ["1.10", "Rohr", "10.00", "100" + suffix],
        ["1.20", "Bogen", "20.00", "100.01" + suffix],
        ["1.30", "Ventil", "30.00", "-5" + suffix],  # signed surcharge, not a sign error
        ["1.40", "Kappe", "40.00", None],
    ]
    dataset = normalize(workbook(sheet(rows)), boq_profile)
    [issue] = run(BoqBidPricesDetector, dataset, boq_profile).issues
    assert issue.rule_id == "discount_exceeds_price"
    assert issue.row_id == dataset.tables[0].rows[1].row_id
    assert Decimal(issue.observed_value) == Decimal("100.01")
