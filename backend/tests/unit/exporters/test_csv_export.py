"""issues.csv and table CSVs: columns, encoding, RFC 4180 quoting and formula protection."""

from __future__ import annotations

import csv
import io

import pytest

from app.exporters.csv_export import (
    ISSUE_COLUMNS,
    cell_reference,
    issues_csv,
    table_csv,
)
from app.exporters.safety import is_plain_number, needs_formula_prefix
from app.models.profile import DomainProfile
from app.models.source import BoundingBox, SourceKind, SourceLocation
from tests.unit.exporters.samples import (
    EXPLANATION,
    as_delimited,
    build_dataset,
    build_issues,
    make_bundle,
)

BOM = b"\xef\xbb\xbf"


def parse(data: bytes) -> list[list[str]]:
    assert data.startswith(BOM)
    text = data[len(BOM) :].decode("utf-8")
    return list(csv.reader(io.StringIO(text, newline=""), strict=True))


def issue_records(data: bytes) -> list[dict[str, str]]:
    header, *rows = parse(data)
    assert tuple(header) == ISSUE_COLUMNS
    return [dict(zip(header, row, strict=True)) for row in rows]


def assert_spreadsheet_safe(rows: list[list[str]]) -> None:
    """No field could be read as a formula: it is a plain number or neutralized text."""
    for row in rows:
        for value in row:
            safe = is_plain_number(value) or value.startswith("'")
            assert safe or not needs_formula_prefix(value), value


def test_issues_csv_has_bom_crlf_and_the_documented_header(boq_profile: DomainProfile) -> None:
    data = issues_csv(make_bundle(boq_profile))
    assert data.startswith(BOM + b"validation_run_id,dataset_id,dataset_revision,issue_id,")
    assert data.split(b"\r\n", 1)[0] == BOM + ",".join(ISSUE_COLUMNS).encode()
    assert data.endswith(b"\r\n")
    assert data.count(b"\r\n") >= 4  # header and three records (plus quoted line breaks)
    assert len(ISSUE_COLUMNS) == 25
    assert ISSUE_COLUMNS[4:6] == ("severity", "finding_category")


def test_issues_csv_writes_every_column(boq_profile: DomainProfile) -> None:
    line_total, table_level, reviewed = issue_records(issues_csv(make_bundle(boq_profile)))
    assert line_total == {
        "validation_run_id": "run_000001",
        "dataset_id": "ds_000001",
        "dataset_revision": "1",
        "issue_id": "iss_000001",
        "severity": "high",
        "finding_category": "",  # the test probe is no registered detector: no category
        "evidence_class": "confirmed_rule_violation",
        "effective_evidence_class": "confirmed_rule_violation",
        "review_status": "pending_review",
        "detector_id": "test.export_probe",
        "detector_version": "1.0.0",
        "rule_id": "line_total",
        "issue_category": "arithmetic",
        "table": "LV",
        "sheet": "LV",
        "source_row": "3",
        "cells": "F3",
        "title": "'@cmd line total differs",
        "observed_value": '\'=HYPERLINK("https://attacker.example","x")',
        "expected_value": "'-2+3",
        "financial_impact_amount": "-12.50",
        "financial_impact_currency": "EUR",
        "explanation": EXPLANATION,  # quotes, commas, LF and CRLF line breaks survive
        "suggested_action": "'\t=x",
        "reviewer_comment": "",
    }
    assert table_level["table"] == "../../etc/passwd"  # the real name, as text
    assert table_level["sheet"] == "../../etc/passwd"
    assert (table_level["source_row"], table_level["cells"]) == ("", "")
    assert (table_level["financial_impact_amount"], table_level["financial_impact_currency"]) == (
        "",
        "",
    )
    assert table_level["observed_value"] == table_level["expected_value"] == ""
    assert table_level["evidence_class"] == "needs_external_context"
    assert reviewed["review_status"] == "confirmed_error"
    assert reviewed["evidence_class"] == "confirmed_rule_violation"
    assert reviewed["effective_evidence_class"] == "human_confirmed_error"
    assert reviewed["reviewer_comment"] == "'\r=x geprüft"
    assert reviewed["cells"] == "C4 E4"
    assert reviewed["source_row"] == "4"
    assert reviewed["observed_value"] == "'-12.50"  # text, not a number written from Decimal


def test_the_finding_category_is_written_and_empty_without_one(boq_profile: DomainProfile) -> None:
    dataset = build_dataset(boq_profile)
    line_total, table_level, reviewed = build_issues(dataset, boq_profile)
    issues = [
        line_total.evolve(detector_id="deterministic.line_total"),
        table_level.evolve(detector_id="deterministic.reference_integrity"),
        reviewed.evolve(detector_id="deterministic.unit_vocabulary"),  # reading the file
    ]
    records = issue_records(issues_csv(make_bundle(boq_profile, dataset=dataset, issues=issues)))
    assert [record["finding_category"] for record in records] == ["error", "ambiguity", ""]
    assert [record["severity"] for record in records] == [i.severity.value for i in issues]


def test_issue_rows_keep_the_given_order(boq_profile: DomainProfile) -> None:
    dataset = build_dataset(boq_profile)
    issues = build_issues(dataset, boq_profile)
    reordered = make_bundle(boq_profile, dataset=dataset, issues=issues[::-1])
    ids = [record["issue_id"] for record in issue_records(issues_csv(reordered))]
    assert ids == ["iss_000003", "iss_000002", "iss_000001"]


def test_numbers_from_decimals_are_written_bare(boq_profile: DomainProfile) -> None:
    data = issues_csv(make_bundle(boq_profile))
    assert b",-12.50,EUR," in data  # unquoted and without a prefix
    assert b"'-12.50,EUR" not in data


def test_quotes_commas_and_line_breaks_follow_rfc_4180(boq_profile: DomainProfile) -> None:
    data = issues_csv(make_bundle(boq_profile))
    assert b'"Menge \xc3\x97 Preis = 131,25 ""EUR"", nicht 25,00;\nzweite Zeile' in data
    assert issue_records(data)[0]["explanation"] == EXPLANATION


def test_issues_csv_is_spreadsheet_safe(boq_profile: DomainProfile) -> None:
    assert_spreadsheet_safe(parse(issues_csv(make_bundle(boq_profile))))


def test_delimited_text_cells_are_named_by_record_and_field(boq_profile: DomainProfile) -> None:
    dataset = as_delimited(build_dataset(boq_profile))
    line_total, _, reviewed = issue_records(issues_csv(make_bundle(boq_profile, dataset=dataset)))
    assert line_total["cells"] == "CSV record 3 field 6"
    assert reviewed["cells"] == "CSV record 4 field 3 CSV record 4 field 5"
    assert line_total["sheet"] == ""
    assert line_total["source_row"] == "3"


@pytest.mark.parametrize(
    ("source", "reference"),
    [
        (SourceLocation(kind=SourceKind.SPREADSHEET, row_number=12, column_number=3), "C12"),
        (SourceLocation(kind=SourceKind.SPREADSHEET, row_number=1, column_number=28), "AB1"),
        (
            SourceLocation(kind=SourceKind.DELIMITED_TEXT, row_number=14, column_number=3),
            "CSV record 14 field 3",
        ),
        (SourceLocation(kind=SourceKind.DELIMITED_TEXT, row_number=14), "CSV record 14"),
        (
            SourceLocation(
                kind=SourceKind.PDF_TEXT,
                page_number=2,
                bbox=BoundingBox(page_number=2, x0=0, y0=0, x1=1, y1=1),
            ),
            "pdf_text page 2",
        ),
        (None, "?"),
    ],
)
def test_cell_reference(source: SourceLocation | None, reference: str) -> None:
    assert cell_reference(source) == reference


def test_table_csv_writes_raw_values_under_original_headers(boq_profile: DomainProfile) -> None:
    bill = build_dataset(boq_profile).tables[0]
    rows = parse(table_csv(bill))
    assert rows == [
        ["source_row", "row_kind", "Item", "Description", "Qty", "Unit", "'=Rate", "Amount"],
        ["2", "section", "", "Erdarbeiten", "", "", "", ""],
        ["3", "item", "01.001", "'=1+1", "10.500", "m³", "12.50", "131.25"],
        ["4", "item", "01.002", 'Aushub "BK 3", tief\nZeile 2', "-2", "m3", "-12.50", "25.00"],
        ["5", "item", "'@cmd", "Nul�Zeichen", "1", "St", "'-12,50 €", "approx. 5"],
        ["6", "subtotal", "", "Summe Erdarbeiten", "", "", "", "156.25"],
    ]
    assert_spreadsheet_safe(rows)


def test_table_csv_numbers_stay_numbers_and_number_text_does_not(
    boq_profile: DomainProfile,
) -> None:
    _, other, device = build_dataset(boq_profile).tables
    assert parse(table_csv(other)) == [
        ["source_row", "row_kind", "Item", "column_2", "Amount"],  # no header: normalized name
        ["2", "item", "00.001", "-7", "-2500.00"],
    ]
    assert b"\r\n2,item,00.001,-7,-2500.00\r\n" in table_csv(other)
    assert parse(table_csv(device)) == [
        ["source_row", "row_kind", "Note"],
        ["2", "item", "'-2+3"],
        ["3", "item", "'-5"],  # a text cell is always neutralized
    ]


def test_table_csv_has_bom_and_crlf(boq_profile: DomainProfile) -> None:
    data = table_csv(build_dataset(boq_profile).tables[2])
    assert data == BOM + b"source_row,row_kind,Note\r\n2,item,'-2+3\r\n3,item,'-5\r\n"
