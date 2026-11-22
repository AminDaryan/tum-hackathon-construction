"""The user flow for printed bills: upload a PDF, download the extracted table as Excel, run
validation, download the run's Excel workbook with its findings."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.exporters.xlsx_export import XLSX_MEDIA_TYPE
from app.main import create_app
from tests.integration.test_api import API, _workbench
from tests.support.pdf_builder import sample_bill

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    workbench = _workbench(tmp_path)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as test_client:
        yield test_client
    workbench.close()


def _upload(client: TestClient, content: bytes, name: str, media: str) -> dict:
    response = client.post(f"{API}/documents", files={"file": (name, content, media)})
    assert response.status_code == 201, response.text
    return response.json()["document"]


def test_a_pdf_bill_is_extracted_and_exported_to_excel(client: TestClient) -> None:
    content = sample_bill()
    document = _upload(client, content, "LV Erdarbeiten.pdf", "application/pdf")
    assert document["format"] == "pdf"
    assert document["processing_status"] == "processed"
    original = client.get(f"{API}/documents/{document['document_id']}/original")
    assert original.status_code == 200
    assert original.content == content
    assert original.headers["content-type"] == "application/pdf"
    assert original.headers["cache-control"] == "no-store"
    assert original.headers["content-disposition"].startswith("attachment;")
    assert client.get(f"{API}/documents/doc_missing/original").status_code == 404
    response = client.get(f"{API}/datasets/{document['dataset_id']}/export/xlsx")
    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    assert "LV Erdarbeiten" in response.headers["content-disposition"]
    assert "-extracted.xlsx" in response.headers["content-disposition"]
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Erdarbeiten Testbau", "Extraction"]
    rows = list(book.worksheets[0].iter_rows(values_only=True))
    header = rows[0]
    assert header[:4] == ("Source", "Row kind", "OZ", "Kurztext")
    assert "GAEB-ID" not in header  # empty for a PDF bill: left out
    first = next(row for row in rows if row[2] == "01.10")
    by_header = dict(zip(header, first, strict=True))
    assert by_header["Source"] == "page 2"
    assert by_header["Menge"] == 120 and by_header["Einheit"] == "m2"
    assert by_header["GP"] == 540


def test_the_run_workbook_lists_the_findings(client: TestClient) -> None:
    wrong = sample_bill().replace(b"(646,10)", b"(664,10)")
    document = _upload(client, wrong, "LV.pdf", "application/pdf")
    run = client.post(f"{API}/datasets/{document['dataset_id']}/validation-runs").json()
    response = client.get(f"{API}/validation-runs/{run['run_id']}/export/xlsx")
    assert response.status_code == 200
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames[-2:] == ["Issues", "Extraction"]
    header, *rows = book["Issues"].iter_rows(values_only=True)
    found = [dict(zip(header, row, strict=True)) for row in rows]
    line_total = next(row for row in found if row["Check"] == "deterministic.line_total")
    assert line_total["Category"] == "error"  # downgraded (a PDF value), still an error


def test_a_wrong_total_on_a_pdf_bill_is_an_error_to_verify_in_the_source(
    client: TestClient,
) -> None:
    """Values from a PDF's text layer are unverified, so the evidence policy downgrades a failed
    rule to extraction_uncertainty; the finding keeps its check's category, so the Error filter
    and the category counts show it."""
    wrong = sample_bill().replace(b"(646,10)", b"(664,10)")
    document = _upload(client, wrong, "LV.pdf", "application/pdf")
    run = client.post(f"{API}/datasets/{document['dataset_id']}/validation-runs").json()
    url = f"{API}/validation-runs/{run['run_id']}/issues"
    items = client.get(url).json()["items"]
    # The wrong line total, and the two subtotals above it that no longer add up; and, since
    # step B2, the list of the bill's contingency position, a Risk note that no rule failed.
    assert sorted((i["detector_id"], i["rule_id"]) for i in items) == [
        ("deterministic.line_total", "line_total_mismatch"),
        ("deterministic.subtotal", "subtotal_mismatch"),
        ("deterministic.subtotal", "subtotal_mismatch"),
        ("domain.boq_position_types", "contingency_and_hourly"),
    ]
    assert {(i["evidence_class"], i["finding_category"]) for i in items} == {
        ("extraction_uncertainty", "error"),
        ("semantic_warning", "risk"),
    }
    assert run["issue_counts"]["by_finding_category"] == {"error": 3, "risk": 1}
    assert client.get(url, params={"finding_category": "error"}).json()["total"] == 3
    assert client.get(url, params={"finding_category": "none"}).json()["total"] == 0


def test_a_spreadsheet_is_exported_to_excel_as_well(client: TestClient) -> None:
    csv = b"Pos;Text;Menge;Einheit;EP;GP\r\n1;=1+2;2;m;3,00;6,00\r\n"
    document = _upload(client, csv, "bill.csv", "text/csv")
    response = client.get(f"{API}/datasets/{document['dataset_id']}/export/xlsx")
    book = load_workbook(io.BytesIO(response.content))
    cells = [cell for row in book.worksheets[0].iter_rows() for cell in row]
    hostile = next(cell for cell in cells if cell.value == "=1+2")
    assert hostile.data_type == "s"  # shown as text, never evaluated


def test_an_unknown_dataset_is_404(client: TestClient) -> None:
    assert client.get(f"{API}/datasets/ds_missing/export/xlsx").status_code == 404
