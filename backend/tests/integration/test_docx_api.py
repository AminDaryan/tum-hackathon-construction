"""The user flow for Word documents: upload a .docx, the bill is extracted from its table or
its item paragraphs, validation finds the planted error and names where it is in Word."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.ingestion.security import DOCX_MEDIA_TYPE
from app.main import create_app
from tests.integration.test_api import API, _workbench
from tests.support.docx_builder import paragraph, table_bill, write_docx

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    workbench = _workbench(tmp_path)
    with TestClient(create_app(workbench=workbench), base_url="http://localhost") as test_client:
        yield test_client
    workbench.close()


def _upload(client: TestClient, path: Path) -> dict:
    content = path.read_bytes()
    response = client.post(
        f"{API}/documents", files={"file": (path.name, content, DOCX_MEDIA_TYPE)}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_bill_in_a_word_table_is_validated_like_a_spreadsheet(
    client: TestClient, tmp_path: Path
) -> None:
    upload = _upload(client, write_docx(tmp_path / "LV Rohbau.docx", table_bill()))
    document, dataset = upload["document"], upload["dataset"]
    assert document["format"] == "docx"
    assert document["processing_status"] == "processed"
    [table] = client.get(f"{API}/datasets/{dataset['dataset_id']}").json()["tables"]
    assert table["name"] == "Table 1"
    mapped = {c["mapped_semantic_field"] for c in table["columns"]}
    assert {"item_code", "description", "quantity", "unit", "unit_price", "line_total"} <= mapped

    run = client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()
    issues = client.get(f"{API}/validation-runs/{run['run_id']}/issues").json()["items"]
    [line_total] = [i for i in issues if i["detector_id"] == "deterministic.line_total"]
    [cell] = line_total["affected_cells"]
    assert cell["source"]["kind"] == "word"
    assert (cell["source"]["sheet_name"], cell["source"]["row_number"]) == ("Table 1", 5)

    workbook = client.get(f"{API}/validation-runs/{run['run_id']}/export/xlsx")
    assert workbook.status_code == 200
    book = load_workbook(io.BytesIO(workbook.content))
    header, *rows = book["Table 1"].iter_rows(values_only=True)
    concrete = next(dict(zip(header, row, strict=True)) for row in rows if "01.0020" in row)
    assert concrete["Source"] == "Table 1, row 5"


def test_a_bill_written_as_item_paragraphs(client: TestClient, tmp_path: Path) -> None:
    body = "".join(
        paragraph(text)
        for text in (
            "Erdarbeiten",
            "1.10\tOberboden abtragen\tm2\t250,000\t4,50\t1.125,00",
            "1.20\tBoden lösen und und laden\tm3\t80,000\t12,00\t960,00",
            "1.30\tBoden einbauen\tm3\t80,000\t9,50\t706,00",  # 80 × 9,50 = 760,00
        )
    )
    upload = _upload(client, write_docx(tmp_path / "Erdarbeiten.docx", body))
    dataset = upload["dataset"]
    warnings = {w["code"] for w in dataset["extraction"]["warnings"]}
    assert "docx_list_read" in warnings
    run = client.post(f"{API}/datasets/{dataset['dataset_id']}/validation-runs").json()
    issues = client.get(f"{API}/validation-runs/{run['run_id']}/issues").json()["items"]
    by_check = {i["detector_id"]: i for i in issues}
    line_total = by_check["deterministic.line_total"]
    assert line_total["affected_cells"][0]["source"]["line_number"] == 4  # paragraph 4
    assert "'und und'" in by_check["domain.boq_typos"]["title"]


def test_a_legacy_doc_is_refused_with_advice(client: TestClient) -> None:
    response = client.post(
        f"{API}/documents",
        files={
            "file": (
                "LV.doc",
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64,
                "application/msword",
            )
        },
    )
    assert response.status_code == 415
    assert "Save the document as .docx" in response.json()["error"]["message"]
