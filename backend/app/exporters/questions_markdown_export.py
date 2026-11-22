"""A ready-to-send questions document for findings marked ``needs_more_information``."""

from __future__ import annotations

from app.exporters.bundle import ExportBundle
from app.exporters.csv_export import cell_reference, cell_source
from app.models.dataset import Dataset
from app.models.issue import ReviewStatus, ValidationIssue


def _question_text(issue: ValidationIssue) -> str:
    for candidate in (issue.reviewer_comment, issue.suggested_action, issue.explanation):
        text = (candidate or "").strip()
        if text:
            return text
    return "Please clarify this finding."


def _location(issue: ValidationIssue, dataset: Dataset) -> str:
    table = next((item for item in dataset.tables if item.table_id == issue.table_id), None)
    row = (
        table.row(issue.row_id).source_row_number
        if table is not None and issue.row_id is not None and table.has_row(issue.row_id)
        else None
    )
    cells = [cell_reference(cell_source(ref, dataset)) for ref in issue.affected_cells]
    location = []
    if table is not None:
        location.append(f"Table {table.name}")
    if row is not None:
        location.append(f"row {row}")
    if cells:
        location.append("cells " + ", ".join(cells))
    return ", ".join(location) if location else "Unknown location"


def questions_markdown(bundle: ExportBundle) -> bytes:
    findings = [
        issue
        for issue in bundle.issues
        if issue.review_status is ReviewStatus.NEEDS_MORE_INFORMATION
    ]
    lines = [
        "# Questions for client",
        "",
        f"- Validation run: `{bundle.run.run_id}`",
        f"- Document: `{bundle.document.original_filename}`",
        f"- Dataset: `{bundle.dataset.dataset_id}` revision `{bundle.dataset.revision}`",
        f"- Generated at: `{bundle.generated_at_text}`",
        f"- Findings needing clarification: **{len(findings)}**",
        "",
    ]
    if not findings:
        lines.extend(
            [
                "No findings are marked as **Needs more information** in this run.",
                "",
            ]
        )
    for index, issue in enumerate(findings, start=1):
        lines.extend(
            [
                f"## {index}. {issue.title}",
                "",
                f"- Issue ID: `{issue.issue_id}`",
                f"- Location: {_location(issue, bundle.dataset)}",
                f"- Question: {_question_text(issue)}",
                f"- Context: {issue.explanation.strip()}",
                "",
            ]
        )
    return ("\n".join(lines)).encode("utf-8")


class QuestionsMarkdownExporter:
    """``GET /validation-runs/{run_id}/export/questions.md``."""

    format_id = "questions.md"
    media_type = "text/markdown; charset=utf-8"
    filename_suffix = " questions.md"

    def export(self, bundle: ExportBundle) -> bytes:
        return questions_markdown(bundle)
