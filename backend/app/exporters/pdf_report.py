"""Findings reports as PDF: of one validation run (format id ``pdf``,
``GET /validation-runs/{run_id}/export/pdf``) and of a project's last validation, one section
per bill (``GET /projects/{project_id}/export/pdf``).

A section names the file, the revision checked and when, counts the findings by severity and
those still to review, then lists the findings most severe first: severity, review status,
where (table, source row, cells), the finding (title and explanation) and the financial impact.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from app.exporters.bundle import ExportBundle
from app.exporters.csv_export import cell_reference, cell_source
from app.exporters.pdf_writer import Cell, Column, PdfDocument
from app.exporters.xlsx_export import row_source
from app.models.dataset import Dataset
from app.models.issue import SEVERITY_RANK, ReviewStatus, Severity, ValidationIssue

PDF_MEDIA_TYPE = "application/pdf"

REVIEW_WORDS: dict[ReviewStatus, str] = {
    ReviewStatus.PENDING_REVIEW: "To review",
    ReviewStatus.CONFIRMED_ERROR: "Confirmed error",
    ReviewStatus.FALSE_POSITIVE: "False positive",
    ReviewStatus.CORRECTED: "Corrected",
    ReviewStatus.NEEDS_MORE_INFORMATION: "Needs clarification",
    ReviewStatus.DISMISSED: "Dismissed",
}

COLUMNS = (
    Column("Severity", 62),
    Column("Review status", 92),
    Column("Where", 150),
    Column("Finding", 370),
    Column("Financial impact", 88),
)


def _when(moment: datetime | None) -> str:
    return moment.strftime("%d %b %Y, %H:%M UTC") if moment is not None else "not finished"


def _where(issue: ValidationIssue, dataset: Dataset) -> str:
    table = next((t for t in dataset.tables if t.table_id == issue.table_id), None)
    parts = []
    if table is not None:
        parts.append(table.name)
        if issue.row_id is not None and table.has_row(issue.row_id):
            parts.append(row_source(table, table.row(issue.row_id)))
    cells = " ".join(cell_reference(cell_source(ref, dataset)) for ref in issue.affected_cells)
    if cells.strip():
        parts.append(f"cells {cells}")
    return ", ".join(part for part in parts if part) or "The whole file"


def _impact(issue: ValidationIssue) -> str:
    impact = issue.estimated_financial_impact
    if impact is None:
        return ""
    return f"{impact.amount:,.2f} {impact.currency or ''}".strip()


def summary(issues: Sequence[ValidationIssue]) -> str:
    """ "5 findings: 1 critical, 2 high, 2 low. 3 still to review." (or "No findings.")."""
    if not issues:
        return "No findings."
    counts = Counter(issue.severity for issue in issues)
    by_severity = ", ".join(
        f"{counts[severity]} {severity.value}"
        for severity in sorted(Severity, key=lambda s: -SEVERITY_RANK[s])
        if counts[severity]
    )
    to_review = sum(issue.review_status is ReviewStatus.PENDING_REVIEW for issue in issues)
    noun = "finding" if len(issues) == 1 else "findings"
    return f"{len(issues)} {noun}: {by_severity}. {to_review} still to review."


def _section(pdf: PdfDocument, bundle: ExportBundle, *, heading_size: float) -> None:
    run = bundle.run
    pdf.heading(bundle.document.original_filename, heading_size)
    pdf.paragraph(
        f"Revision {run.dataset_revision}, validated {_when(run.finished_at or run.started_at)}. "
        f"{summary(bundle.issues)}"
    )
    issues = sorted(bundle.issues, key=lambda issue: -SEVERITY_RANK[issue.severity])
    if not issues:
        return
    rows = [
        (
            Cell(issue.severity.value.capitalize()),
            Cell(REVIEW_WORDS.get(issue.review_status, issue.review_status.value)),
            Cell(_where(issue, bundle.dataset)),
            Cell(issue.title, bold_first_line=True, detail=issue.explanation or ""),
            Cell(_impact(issue)),
        )
        for issue in issues
    ]
    pdf.table(COLUMNS, rows)


def run_report(bundle: ExportBundle) -> bytes:
    """The report of one validation run."""
    pdf = PdfDocument(f"Findings report: {bundle.document.original_filename}", bundle.generated_at)
    pdf.heading("Findings report", 16)
    pdf.paragraph(f"Generated {_when(bundle.generated_at)}.")
    _section(pdf, bundle, heading_size=13)
    return pdf.render()


def project_report(
    name: str,
    validated_at: datetime | None,
    bundles: Sequence[ExportBundle],
    generated_at: datetime,
) -> bytes:
    """The report of a project's last validation: one section per bill, in the given order."""
    pdf = PdfDocument(f"Findings report: {name}", generated_at)
    pdf.heading(f"Findings report: {name}", 16)
    total = sum(len(bundle.issues) for bundle in bundles)
    bills = "bill" if len(bundles) == 1 else "bills"
    noun = "finding" if total == 1 else "findings"
    pdf.paragraph(
        f"Last validation of the project {_when(validated_at)}: {len(bundles)} {bills}, "
        f"{total} {noun}. Generated {_when(generated_at)}."
    )
    for bundle in bundles:
        pdf.space(6)
        _section(pdf, bundle, heading_size=12)
    return pdf.render()


class PdfReportExporter:
    """``GET /validation-runs/{run_id}/export/pdf``: the findings report of one run."""

    format_id = "pdf"
    media_type = PDF_MEDIA_TYPE
    filename_suffix = " report.pdf"

    def export(self, bundle: ExportBundle) -> bytes:
        return run_report(bundle)
