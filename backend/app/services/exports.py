"""Exports of one validation run (``issues.csv``, ``tables.zip``, ``json``, ``xlsx``,
``questions.md``, ``pdf``): the run, the dataset revision it checked, its document, findings and
detector specs, rendered by the registered exporter for the format; the extracted tables of a
dataset as an Excel workbook (no run needed); and the findings of a project's last validation,
every bill together, as a PDF report, an Excel workbook or a CSV file, or its bid risk report as
a PDF."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.exporters import ExportBundle, get_exporter
from app.exporters.csv_export import ISSUE_COLUMNS, issue_row, write_csv
from app.exporters.filenames import (
    dataset_export_filename,
    export_filename,
    project_export_filename,
)
from app.exporters.pdf_report import PDF_MEDIA_TYPE, project_report
from app.exporters.safety import csv_value
from app.exporters.xlsx_export import XLSX_MEDIA_TYPE, WorkbookInput, project_workbook, workbook
from app.models.project import ProjectReport, ReportFormat
from app.repositories.base import IssueQuery, UnitOfWork
from app.risk.bid_report_pdf import render as render_bid_report
from app.risk.service import bid_report
from app.services import projects
from app.services.workbench import Workbench

PROJECT_FORMATS = ("pdf", "xlsx", "issues.csv")
BID_RISK_REPORT = "bid-risk.pdf"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExportFile:
    content: bytes
    filename: str
    media_type: str


def export_dataset(wb: Workbench, dataset_id: str) -> ExportFile:
    """The extracted tables of a dataset (its latest revision) as an Excel workbook, without
    a validation run."""
    with wb.uow() as uow:
        dataset = uow.datasets.get(dataset_id)
        if dataset is None:
            raise NotFoundError(f"Unknown dataset {dataset_id!r}.")
        document = uow.documents.get(dataset.document_id)
        if document is None:
            raise NotFoundError(f"The document of dataset {dataset_id!r} no longer exists.")
    content = workbook(WorkbookInput(document, dataset, wb.clock.now()))
    file = ExportFile(
        content=content,
        filename=dataset_export_filename(document, dataset.dataset_id, "-extracted.xlsx"),
        media_type=XLSX_MEDIA_TYPE,
    )
    logger.info(
        "dataset %s exported as xlsx: %d bytes",
        dataset_id,
        len(content),
        extra={"dataset_id": dataset_id, "export_format": "xlsx", "size_bytes": len(content)},
    )
    return file


def _bundle(wb: Workbench, uow: UnitOfWork, run_id: str) -> ExportBundle:
    run = uow.runs.get(run_id)
    if run is None:
        raise NotFoundError(f"Unknown validation run {run_id!r}.")
    dataset = uow.datasets.get(run.dataset_id, run.dataset_revision)
    document = uow.documents.get(run.document_id)
    if dataset is None or document is None:
        raise NotFoundError(f"The dataset or document of run {run_id!r} no longer exists.")
    issues = list(uow.issues.iter_all(IssueQuery(run_id=run_id)))
    known = set(wb.detectors.ids())
    specs = [
        wb.detectors.get(report.detector_id).spec
        for report in run.detector_reports
        if report.detector_id in known
    ]
    return ExportBundle(
        document=document,
        dataset=dataset,
        run=run,
        issues=issues,
        detectors=specs,
        generated_at=wb.clock.now(),
    )


def export(wb: Workbench, run_id: str, format_id: str) -> ExportFile:
    exporter = get_exporter(format_id)  # NotFoundError for an unknown format
    with wb.uow() as uow:
        bundle = _bundle(wb, uow, run_id)
    run, document, issues = bundle.run, bundle.document, bundle.issues
    file = ExportFile(
        content=exporter.export(bundle),
        filename=export_filename(document, run, exporter.filename_suffix),
        media_type=exporter.media_type,
    )
    logger.info(
        "run %s exported as %s: %d bytes, %d findings",
        run_id,
        format_id,
        len(file.content),
        len(issues),
        extra={"run_id": run_id, "export_format": format_id, "size_bytes": len(file.content)},
    )
    return file


def export_project(wb: Workbench, project_id: str, format_id: str) -> ExportFile:
    """The findings of every bill in the project's last completed validation, in the order of
    the project's files: ``pdf`` (a report, one section per bill), ``xlsx`` (one Issues sheet
    with a File column) or ``issues.csv`` (a ``file`` column, then the run export's columns)."""
    if format_id not in PROJECT_FORMATS:
        raise NotFoundError(f"Unknown project export format {format_id!r}.")
    with wb.uow() as uow:
        project = projects.load(uow, project_id)
        validation = project.validation
        if validation is None or validation.status != "completed" or not validation.runs:
            raise ConflictError("The project has not been validated yet: validate it first.")
        bundles = [
            _bundle(wb, uow, validation.runs[file.document_id])
            for file in project.files
            if file.document_id in validation.runs
        ]
    generated_at = wb.clock.now()
    if format_id == "pdf":
        content = project_report(project.name, validation.finished_at, bundles, generated_at)
        file = ExportFile(
            content, project_export_filename(project.name, " report.pdf"), PDF_MEDIA_TYPE
        )
    elif format_id == "xlsx":
        content = project_workbook(bundles, generated_at)
        file = ExportFile(
            content, project_export_filename(project.name, " issues.xlsx"), XLSX_MEDIA_TYPE
        )
    else:
        rows = [
            [
                csv_value(bundle.document.original_filename, is_number=False),
                *issue_row(issue, bundle.dataset),
            ]
            for bundle in bundles
            for issue in bundle.issues
        ]
        content = write_csv([["file", *ISSUE_COLUMNS], *rows])
        file = ExportFile(
            content,
            project_export_filename(project.name, " issues.csv"),
            "text/csv; charset=utf-8",
        )
    logger.info(
        "project %s exported as %s: %d bytes, %d bills",
        project_id,
        format_id,
        len(file.content),
        len(bundles),
        extra={
            "project_id": project_id,
            "export_format": format_id,
            "size_bytes": len(file.content),
        },
    )
    return file


def create_report(
    wb: Workbench, project_id: str, format_id: ReportFormat, document_id: str | None = None
) -> ProjectReport:
    """Generate a report on the findings of the project's last completed validation (the whole
    project, or the bill ``document_id``), or its bid risk report (``bid-risk.pdf``, the whole
    project only), keep its file in the file store and list it in the project. 409 before the
    project is validated; 404 for a bill not in that validation. The bid risk report, like
    ``GET /projects/{id}/risk-report/pdf``, also covers a validation that stopped part-way."""
    if format_id not in (*PROJECT_FORMATS, BID_RISK_REPORT):
        raise NotFoundError(f"Unknown report format {format_id!r}.")
    if format_id == BID_RISK_REPORT and document_id is not None:
        raise InvalidInputError("The bid risk report covers the whole project, not one bill.")
    with wb.uow() as uow:
        validation = projects.load(uow, project_id).validation
    if validation is None:
        raise ConflictError("The project has not been validated yet: validate it first.")
    if format_id == BID_RISK_REPORT:
        # 409 while a validation runs.
        bid = bid_report(wb, project_id)
        file = ExportFile(
            render_bid_report(bid),
            project_export_filename(bid.project_name, "-bid-risk-report.pdf"),
            PDF_MEDIA_TYPE,
        )
    elif validation.status != "completed" or not validation.runs:
        raise ConflictError("The project has not been validated yet: validate it first.")
    elif document_id is None:
        file = export_project(wb, project_id, format_id)
    elif document_id in validation.runs:
        file = export(wb, validation.runs[document_id], format_id)
    else:
        raise NotFoundError("This file is not in the project's last validation.")
    spooled = wb.files.spool([file.content], max_bytes=max(len(file.content), 1))
    stored = wb.files.commit(spooled, media_type=file.media_type)
    report = ProjectReport(
        report_id=wb.ids.new("rpt"),
        created_at=wb.clock.now(),
        format=format_id,
        document_id=document_id,
        filename=file.filename,
        media_type=file.media_type,
        size_bytes=stored.size_bytes,
        storage_key=stored.storage_key,
        validated_at=validation.finished_at,
    )
    with wb.uow() as uow:
        project = projects.load(uow, project_id)
        uow.projects.update(project.evolve(reports=[*project.reports, report]))
    return report


def report_file(wb: Workbench, project_id: str, report_id: str) -> ExportFile:
    """The file of a report the project keeps."""
    with wb.uow() as uow:
        project = projects.load(uow, project_id)
    report = next((r for r in project.reports if r.report_id == report_id), None)
    if report is None:
        raise NotFoundError(f"Unknown report {report_id!r}.")
    with wb.files.open(report.storage_key) as handle:
        content = handle.read()
    return ExportFile(content=content, filename=report.filename, media_type=report.media_type)
