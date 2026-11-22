"""xlsx: sheets, exact numbers, hostile text kept as text, and byte-identical files."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.exporters import get_exporter
from app.exporters.xlsx_export import (
    EXTRACTION_SHEET,
    ISSUES_SHEET,
    LEADING_COLUMNS,
    WorkbookInput,
    _sheet_name,
    workbook,
)
from app.models.profile import DomainProfile
from tests.unit.exporters.samples import (
    GENERATED_AT,
    HOSTILE_TEXTS,
    build_dataset,
    build_issues,
    make_bundle,
)


def _open(data: bytes):
    return load_workbook(io.BytesIO(data))


def _run_workbook(profile: DomainProfile, **kwargs) -> bytes:
    return get_exporter("xlsx").export(make_bundle(profile, **kwargs))


def test_a_run_workbook_has_the_tables_the_issues_and_the_extraction(
    boq_profile: DomainProfile,
) -> None:
    bundle = make_bundle(boq_profile)
    book = _open(get_exporter("xlsx").export(bundle))
    table_names = [table.name for table in bundle.dataset.tables]
    assert book.sheetnames[-2:] == [ISSUES_SHEET, EXTRACTION_SHEET]
    assert len(book.sheetnames) == len(table_names) + 2
    issues = book[ISSUES_SHEET]
    assert issues.max_row == len(bundle.issues) + 1
    assert issues.freeze_panes == "A2"


def test_the_issues_sheet_shows_the_finding_category_after_the_severity(
    boq_profile: DomainProfile,
) -> None:
    dataset = build_dataset(boq_profile)
    line_total, table_level, reviewed = build_issues(dataset, boq_profile)
    issues = [
        line_total.evolve(detector_id="deterministic.line_total"),
        table_level.evolve(detector_id="statistical.peer_price"),
        reviewed.evolve(detector_id="deterministic.unit_vocabulary"),  # reading the file
    ]
    book = _open(_run_workbook(boq_profile, dataset=dataset, issues=issues))
    header, *rows = book[ISSUES_SHEET].iter_rows(values_only=True)
    assert header[:3] == ("Severity", "Category", "Evidence")
    found = [dict(zip(header, row, strict=True)) for row in rows]
    assert [row["Category"] for row in found] == ["error", "risk", None]
    assert [row["Severity"] for row in found] == [issue.severity.value for issue in issues]
    # The columns after it moved with it: the impact is a number, the expected value text.
    assert found[0]["Financial impact"] == Decimal("-12.50")
    assert (found[0]["Currency"], found[0]["Expected"]) == ("EUR", "-2+3")
    issue_ids = [row["Issue ID"] for row in found]
    assert issue_ids == [issue.issue_id for issue in issues]


def test_the_extraction_workbook_needs_no_run(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    data = workbook(WorkbookInput(bundle.document, bundle.dataset, GENERATED_AT))
    book = _open(data)
    assert ISSUES_SHEET not in book.sheetnames
    facts = {row[0]: row[1] for row in book[EXTRACTION_SHEET].iter_rows(values_only=True) if row[0]}
    assert facts["Document"] == bundle.document.original_filename
    assert facts["Generated at"] == "2026-11-18T10:30:00Z"


def test_table_sheets_start_with_source_and_row_kind(boq_profile: DomainProfile) -> None:
    book = _open(_run_workbook(boq_profile))
    sheet = book.worksheets[0]
    header = [cell.value for cell in sheet[1]]
    assert tuple(header[:2]) == LEADING_COLUMNS
    kinds = {row[1] for row in sheet.iter_rows(min_row=2, values_only=True)}
    assert "item" in kinds


def test_numbers_are_exact_and_keep_their_decimals(boq_profile: DomainProfile) -> None:
    book = _open(_run_workbook(boq_profile))
    numbers = [
        cell
        for sheet in book.worksheets[:-2]
        for row in sheet.iter_rows(min_row=2)
        for cell in row
        if cell.data_type == "n" and cell.value is not None
    ]
    assert numbers, "the sample tables contain numbers"
    for cell in numbers:
        text = format(Decimal(str(cell.value)), "f")
        if "." in text and not cell.number_format.endswith("%"):
            assert cell.number_format.startswith("#,##0")


def test_hostile_text_is_kept_as_text_never_as_a_formula(boq_profile: DomainProfile) -> None:
    data = _run_workbook(boq_profile)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sheets = [n for n in archive.namelist() if n.startswith("xl/worksheets/sheet")]
        assert all(b"<f>" not in archive.read(name) for name in sheets)
    book = _open(data)
    texts = {
        cell.value
        for sheet in book.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if isinstance(cell.value, str)
    }
    found = [
        text for text in HOSTILE_TEXTS if text.strip("\t\r ") in {t.strip("\t\r ") for t in texts}
    ]
    assert found, "the hostile cell texts reach the workbook unchanged"
    assert all(not text.startswith("'=") for text in texts)  # no quote prefix is added


def test_the_same_bundle_gives_the_same_bytes(boq_profile: DomainProfile) -> None:
    first = _run_workbook(boq_profile)
    assert _run_workbook(boq_profile) == first
    later = _run_workbook(boq_profile, generated_at=GENERATED_AT + timedelta(days=1))
    assert later != first
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert {info.date_time for info in archive.infolist()} == {(2026, 11, 18, 10, 30, 0)}
        core = archive.read("docProps/core.xml")  # openpyxl would write the time of saving
        assert b">2026-11-18T10:30:00Z</dcterms:modified>" in core
        assert b">2026-11-18T10:30:00Z</dcterms:created>" in core


def test_a_naive_timestamp_is_refused(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    naive = datetime(2026, 11, 18, 10, 30)
    with pytest.raises(ValueError, match="timezone-aware"):
        workbook(WorkbookInput(bundle.document, bundle.dataset, naive))


def test_sheet_names_are_valid_and_unique() -> None:
    taken: set[str] = set()
    names = [
        _sheet_name(name, taken)
        for name in ("LV", "lv", "a/b:c*d?[e]", "x" * 40, "History", "", "'quoted'")
    ]
    assert names[0] == "LV" and names[1] == "lv (2)"
    assert all(len(name) <= 31 for name in names)
    assert all(not set(name) & set("[]:*?/\\") for name in names)
    assert len({name.lower() for name in names}) == len(names)
    assert "History" not in names
