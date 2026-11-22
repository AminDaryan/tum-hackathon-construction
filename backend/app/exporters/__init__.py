"""Export adapters (brief Part K).

Phase 1 formats, registered here by format id (the URL segment of
``GET /validation-runs/{run_id}/export/{format_id}``):

* ``json``: run, dataset revision, detectors and issues (:mod:`app.exporters.json_export`);
* ``issues.csv``: the issue register (:mod:`app.exporters.csv_export`);
* ``tables.zip``: the issue register, one CSV per table and a manifest
  (:mod:`app.exporters.zip_export`);
* ``xlsx``: an Excel workbook with one sheet per table, the issues and the extraction report
  (:mod:`app.exporters.xlsx_export`, which also writes the extraction-only workbook of
  ``GET /datasets/{dataset_id}/export/xlsx``).
* ``questions.md``: a ready-to-send question list for findings marked
  ``needs_more_information`` (:mod:`app.exporters.questions_markdown_export`).
* ``pdf``: a findings report (:mod:`app.exporters.pdf_report`, written by
  :mod:`app.exporters.pdf_writer`).

A new format (XLSX review workbook, PDF report) is one module with an exporter class plus one
``register_exporter`` line below; the API resolves it with :func:`get_exporter`. Formula
injection protection for text exports lives in :mod:`app.exporters.safety`, safe file and
entry names in :mod:`app.exporters.filenames`.
"""

from app.exporters.bundle import (
    EXPORTERS,
    ExportBundle,
    Exporter,
    get_exporter,
    register_exporter,
)
from app.exporters.csv_export import IssuesCsvExporter
from app.exporters.filenames import export_filename
from app.exporters.json_export import JsonExporter
from app.exporters.pdf_report import PdfReportExporter
from app.exporters.questions_markdown_export import QuestionsMarkdownExporter
from app.exporters.xlsx_export import XlsxExporter
from app.exporters.zip_export import TablesZipExporter

register_exporter(JsonExporter())
register_exporter(IssuesCsvExporter())
register_exporter(TablesZipExporter())
register_exporter(XlsxExporter())
register_exporter(QuestionsMarkdownExporter())
register_exporter(PdfReportExporter())

__all__ = [
    "EXPORTERS",
    "ExportBundle",
    "Exporter",
    "export_filename",
    "get_exporter",
    "register_exporter",
]
