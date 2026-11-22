"""B0's profile fields and item frame over B1's generated bills: the ``boq`` profile maps the
Positionsart column of the generated bills by its header, the harness maps the STLB-Bau and
EP-Anteil columns as a reviewer would (no header maps ``standard_text_key`` or the unit price
components), and :func:`~app.validation.support.items.item_frame` reads one record per
generated position, with the generator's exact values, keys, units, sections and item kinds,
whether the Positionsart column writes the short codes or the GAEB import's names."""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.evaluation.boq import (
    ALTERNATIVE,
    BASE,
    NORMAL,
    TYPE_CODES,
    TYPE_NAMES,
    WITH_TOTAL,
    WITHOUT_TOTAL,
    BoqBill,
    BoqLine,
    Features,
    document,
    generate_bill,
)
from app.evaluation.prices import UNITS
from app.evaluation.runner import benchmark_workbench
from app.ingestion.gaeb.flatten import item_type
from app.ingestion.gaeb.model import EntryKind, GaebEntry
from app.models.dataset import MappingMethod, Table
from app.services import documents
from app.validation.contracts.context import ValidationContext
from app.validation.support.items import ItemFrame, item_frame
from tests.support.builders import make_context

pytestmark = pytest.mark.evaluation

BILLS = {
    "de-columns": Features(
        language="de", buildings=True, keys=True, components=4, type_column=True
    ),
    "de-text": Features(language="de", keys=True, components=2),  # item kinds in the text
    "de-names": Features(language="de", type_column=True, type_names=True),
    "en": Features(language="en", buildings=True),
}
FORMATS = ("xlsx", "csv")
EXACT, USER = MappingMethod.HEADER_EXACT, MappingMethod.USER
# Header -> (field, how it was mapped): every column of a German bill is mapped.
GERMAN_HEADERS: dict[str, tuple[str, MappingMethod]] = {
    "OZ": ("item_code", EXACT),
    "Positionsart": ("item_type", EXACT),
    "Kurztext": ("description", EXACT),
    "STLB-Bau": ("standard_text_key", USER),  # the harness maps it like a reviewer
    "Menge": ("quantity", EXACT),
    "ME": ("unit", EXACT),
    "EP-Anteil 1": ("unit_price_component_1", USER),  # and these
    "EP-Anteil 2": ("unit_price_component_2", USER),
    "EP-Anteil 3": ("unit_price_component_3", USER),
    "EP-Anteil 4": ("unit_price_component_4", USER),
    "EP": ("unit_price", EXACT),
    "GP": ("line_total", EXACT),
}


@dataclass(frozen=True)
class Read:
    """A generated bill as the product read it."""

    bill: BoqBill
    table: Table
    context: ValidationContext
    frame: ItemFrame
    row_ids: dict[int, str]  # source row number -> row id

    def source_row(self, row_id: str) -> int:
        return next(number for number, other in self.row_ids.items() if other == row_id)


@pytest.fixture(scope="module")
def read(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], Read]:
    wb = benchmark_workbench(tmp_path_factory.mktemp("boq-items"))
    profile = wb.profiles.get("boq")
    result: dict[tuple[str, str], Read] = {}
    for index, (name, features) in enumerate(BILLS.items()):
        bill = generate_bill(random.Random(1 + index), features, 160)
        for file_format in FORMATS:
            doc = document(bill, name=name, file_format=file_format)
            _, dataset = documents.upload(
                wb,
                filename=doc.name,
                chunks=[doc.content],
                profile_id="boq",
                decisions=doc.decisions(),
            )
            assert dataset is not None
            [table] = dataset.tables
            context = make_context(dataset, profile)
            result[(name, file_format)] = Read(
                bill=bill,
                table=table,
                context=context,
                frame=item_frame(context),
                row_ids={row.source_row_number: row.row_id for row in table.rows},
            )
    return result


@pytest.mark.parametrize("file_format", FORMATS)
def test_the_columns_of_a_generated_bill_are_mapped(
    read: dict[tuple[str, str], Read], file_format: str
) -> None:
    got = read[("de-columns", file_format)]
    assert [column.original_header for column in got.table.columns] == list(GERMAN_HEADERS)
    mapped = {
        column.original_header: (column.mapping.field_id, column.mapping.method)
        for column in got.table.columns
        if column.mapping is not None
    }
    assert mapped == GERMAN_HEADERS


@pytest.mark.parametrize("file_format", FORMATS)
def test_keys_and_unit_price_components_are_read_exactly(
    read: dict[tuple[str, str], Read], file_format: str
) -> None:
    for name, parts in (("de-columns", 4), ("de-text", 2)):
        got = read[(name, file_format)]
        rows = {row.row_id: row for row in got.table.rows}
        for line in got.bill.items():
            row = rows[got.row_ids[got.bill.row_of(line)]]
            assert line.key is not None
            assert got.context.text(got.table, row, "standard_text_key") == line.key
            components = [
                got.context.number(got.table, row, f"unit_price_component_{k}")
                for k in range(1, parts + 1)
            ]
            assert components == list(line.components) and len(components) == parts
            assert all(isinstance(value, Decimal) for value in components)
            assert sum(line.components) == line.unit_price  # they add up to the unit price


def _titel(bill: BoqBill, line: BoqLine) -> BoqLine:
    return next(s for s in bill.lines if s.kind == "section" and s.section == line.section)


def _los(bill: BoqBill, line: BoqLine) -> BoqLine:
    return next(s for s in bill.lines if s.kind == "section" and s.section == s.los == line.los)


@pytest.mark.parametrize("file_format", FORMATS)
@pytest.mark.parametrize("name", list(BILLS))
def test_the_item_frame_holds_one_exact_record_per_generated_position(
    read: dict[tuple[str, str], Read], name: str, file_format: str
) -> None:
    got = read[(name, file_format)]
    bill, frame = got.bill, got.frame
    by_source_row = {got.source_row(record.row_id): record for record in frame.records}
    assert len(frame) == len(by_source_row) == len(bill.items())
    assert set(by_source_row) == {bill.row_of(line) for line in bill.items()}
    assert {line.item_type for line in bill.items()} > {"normal"}  # kinds other than normal
    for line in bill.items():
        record = by_source_row[bill.row_of(line)]
        assert (record.item_code, record.description) == (line.code, line.text)
        exact = (
            (record.quantity, line.quantity),
            (record.unit_price, line.unit_price),
            (record.line_total, line.total),
        )
        assert all(isinstance(value, Decimal) and value == want for value, want in exact)
        assert line.unit is not None
        unit = UNITS[line.unit]
        assert (record.unit_id, record.dimension) == (unit.unit_id, unit.dimension)
        # No unit the generator writes carries a multiplier ("100 St"), so the price per base
        # unit is the unit price itself.
        assert record.multiplier is None
        assert record.unit_price_per_base_unit == record.unit_price
        keyed = "key" in bill.columns  # the German bills with keys
        assert record.standard_text_key == (line.key if keyed else None)
        spelling = TYPE_NAMES if bill.features.type_names else TYPE_CODES
        typed = "type" in bill.columns
        assert record.item_type == (spelling[line.item_type] if typed else None)
        assert record.counts_toward_totals is line.counted
        titel = got.row_ids[bill.row_of(_titel(bill, line))]
        assert record.section_row_id == titel
        if bill.features.buildings:
            los = got.row_ids[bill.row_of(_los(bill, line))]
            assert record.section_path == (los, titel)
        else:
            assert record.section_path == (titel,)
        assert record.verified  # spreadsheet cells are verbatim
    assert frame.frame["unit_price"].tolist() == [float(r.unit_price or 0) for r in frame.records]


@pytest.mark.parametrize(
    ("kind", "flags"),
    [
        (NORMAL, ()),
        (BASE, ("ALNSerNo=0",)),
        (WITH_TOTAL, ("Provis=WithTotal",)),
        (WITHOUT_TOTAL, ("Provis=WithoutTotal",)),
        (ALTERNATIVE, ("ALNSerNo=1",)),
    ],
)
def test_the_type_names_are_the_ones_the_gaeb_import_writes(
    kind: str, flags: tuple[str, ...]
) -> None:
    entry = GaebEntry(
        kind=EntryKind.ITEM, element="Item", element_id=None, number="1", line=None, flags=flags
    )
    assert item_type(entry) == TYPE_NAMES[kind]
