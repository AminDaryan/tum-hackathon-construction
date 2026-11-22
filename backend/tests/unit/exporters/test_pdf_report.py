"""pdf: a valid PDF that names the file and its findings, most severe first, byte-identical for
the same input; the writer wraps text and repeats the table header on every page."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pypdfium2 as pdfium

from app.exporters import get_exporter
from app.exporters.pdf_report import project_report, summary
from app.exporters.pdf_writer import Cell, Column, PdfDocument, text_width, wrap
from app.models.profile import DomainProfile
from tests.unit.exporters.samples import DOCUMENT_FILENAME, make_bundle


def _pages(data: bytes) -> list[str]:
    document = pdfium.PdfDocument(io.BytesIO(data))
    try:
        return [page.get_textpage().get_text_range() for page in document]
    finally:
        document.close()


def test_a_run_report_names_the_file_and_lists_its_findings(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    exporter = get_exporter("pdf")
    assert (exporter.media_type, exporter.filename_suffix) == ("application/pdf", " report.pdf")
    data = exporter.export(bundle)
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    text = "\n".join(_pages(data))
    assert "Findings report" in text
    assert DOCUMENT_FILENAME in text  # German letters and € survive
    assert summary(bundle.issues) in text.replace("\r\n", " ").replace("\n", " ")
    for issue in bundle.issues:
        assert issue.title.split()[0] in text
    assert "Page 1 of 1" in text
    # Deterministic: the same bundle gives the same bytes.
    assert exporter.export(bundle) == data


def test_summary_counts_by_severity_and_those_to_review(boq_profile: DomainProfile) -> None:
    issues = make_bundle(boq_profile).issues
    text = summary(issues)
    assert text.startswith(f"{len(issues)} findings: ")
    assert text.endswith(" still to review.")
    assert summary([]) == "No findings."


def test_a_project_report_has_one_section_per_bill(boq_profile: DomainProfile) -> None:
    bundles = [make_bundle(boq_profile), make_bundle(boq_profile)]
    moment = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
    text = "\n".join(_pages(project_report("Brücke Nord", moment, bundles, moment)))
    assert "Findings report: Brücke Nord" in text
    assert "2 bills" in text
    assert text.count(DOCUMENT_FILENAME) == 2


def test_long_tables_continue_on_new_pages_with_their_header() -> None:
    pdf = PdfDocument("Long", datetime(2026, 11, 21, tzinfo=UTC))
    columns = [Column("Severity", 80), Column("Finding", 400)]
    pdf.table(
        columns,
        [
            [Cell("high"), Cell(f"Finding {n}", bold_first_line=True, detail="x " * 80)]
            for n in range(60)
        ],
    )
    pages = _pages(pdf.render())
    assert len(pages) > 1
    assert all(page.count("Severity") == 1 for page in pages)
    assert "Finding 59" in pages[-1]
    assert f"Page {len(pages)} of {len(pages)}" in pages[-1]


def test_wrap_breaks_at_spaces_and_inside_words_only_when_needed() -> None:
    lines = wrap("Menge mal Preis ergibt den Gesamtpreis", 10, 60)
    assert all(text_width(line, 10) <= 60 for line in lines)
    assert " ".join(lines) == "Menge mal Preis ergibt den Gesamtpreis"
    assert wrap("A" * 40, 10, 50)[0] != "A" * 40
    assert wrap("one\ntwo", 10, 500) == ["one", "two"]
