"""Issues: filtered pages of a run's findings, one finding with its history, review decisions.

A review decision names the ``expected_version`` the reviewer saw: a stale version is a 409
``conflict`` and nothing is stored. Transitions follow ``ALLOWED_REVIEW_TRANSITIONS``;
``corrected`` is reserved for the correction workflow (422). Each decision is a new version of
the finding plus an audit event; the source dataset is never modified. Every issue the API
returns says which decisions are possible now (``allowed_review_actions``), so clients never
keep their own copy of the transition rules.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.ingestion.base import RawCell, RawValueType
from app.models.audit import AuditAction, EntityType
from app.models.dataset import Cell, Column, Dataset, Row, Table
from app.models.finding_category import FindingCategoryKey
from app.models.issue import (
    ALLOWED_REVIEW_TRANSITIONS,
    REVIEW_DECISION_TARGETS,
    SEVERITY_RANK,
    EvidenceClass,
    ReviewStatus,
    Severity,
    ValidationIssue,
)
from app.models.profile import DomainProfile, SemanticField
from app.normalization.cells import CellParser, finish
from app.profiles.currency import CurrencyResolver
from app.profiles.units import UnitCatalog
from app.repositories.base import IssueQuery, UnitOfWork
from app.schemas.issues import (
    CorrectedCell,
    IssueCorrectionResult,
    IssueDetail,
    IssuePage,
    IssueView,
)
from app.schemas.runs import ValidationRunDetail
from app.services import datasets, runs
from app.services.workbench import Workbench

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CellCorrectionInput:
    table_id: str
    row_id: str
    column_id: str
    value: str | None


def list_for_run(
    wb: Workbench,
    run_id: str,
    *,
    severities: Collection[Severity] = (),
    evidence_classes: Collection[EvidenceClass] = (),
    review_statuses: Collection[ReviewStatus] = (),
    detector_ids: Collection[str] = (),
    categories: Collection[str] = (),
    finding_categories: Collection[FindingCategoryKey] = (),
    table_id: str | None = None,
    row_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> IssuePage:
    query = IssueQuery(
        run_id=run_id,
        table_id=table_id,
        row_id=row_id,
        severities=frozenset(severities),
        evidence_classes=frozenset(evidence_classes),
        review_statuses=frozenset(review_statuses),
        detector_ids=frozenset(detector_ids),
        categories=frozenset(categories),
        finding_categories=frozenset(finding_categories),
    )
    with wb.uow() as uow:
        if uow.runs.get(run_id) is None:
            raise NotFoundError(f"Unknown validation run {run_id!r}.")
        page = uow.issues.query(query, offset=offset, limit=limit)
    return IssuePage(
        items=[view(issue) for issue in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


def allowed_review_actions(status: ReviewStatus) -> list[ReviewStatus]:
    """The review statuses a plain review decision may set from ``status``, sorted: the allowed
    transitions that are not reserved for another workflow (``corrected``)."""
    allowed = ALLOWED_REVIEW_TRANSITIONS.get(status, frozenset())
    return sorted(allowed & REVIEW_DECISION_TARGETS)


def top_for_project(
    wb: Workbench, project_id: str, *, limit: int = 5, offset: int = 0
) -> tuple[list[IssueView], int]:
    """A page (``offset``, ``limit``) of the findings still to review over every bill of the
    project's last validation, and how many there are: the most severe first, then those with
    the largest financial impact (by its size: a bill can state too much or too little), then
    in the order of the project's files and of each run's findings. A comparison with reference
    prices (``reference_deviation``) is not money lost: it ranks with the findings without an
    impact. 409 before the project is validated or while it runs."""
    with wb.uow() as uow:
        project = uow.projects.get(project_id)
        if project is None:
            raise NotFoundError(f"Unknown project {project_id!r}.")
        validation = project.validation
        if validation is None:
            raise ConflictError(
                f"Project {project_id!r} has not been validated: validate it first."
            )
        if validation.status == "running":
            raise ConflictError(f"Project {project_id!r} is being validated: ask again when done.")
        found = [
            issue
            for file in project.files
            if (run_id := validation.runs.get(file.document_id)) is not None
            for issue in uow.issues.iter_all(
                IssueQuery(run_id=run_id, review_statuses=frozenset({ReviewStatus.PENDING_REVIEW}))
            )
        ]

    def key(item: tuple[int, ValidationIssue]) -> tuple[int, int, Decimal, int]:
        position, issue = item
        impact = issue.estimated_financial_impact
        if impact is not None and impact.kind == "reference_deviation":
            impact = None
        return (
            -SEVERITY_RANK[issue.severity],
            0 if impact is not None else 1,
            -abs(impact.amount) if impact is not None else Decimal(0),
            position,
        )

    ranked = sorted(enumerate(found), key=key)
    return [view(issue) for _, issue in ranked[offset : offset + limit]], len(ranked)


def view(issue: ValidationIssue) -> IssueView:
    """The issue as the API returns it (with ``allowed_review_actions``)."""
    fields = {name: getattr(issue, name) for name in ValidationIssue.model_fields}
    return IssueView.model_validate(
        fields | {"allowed_review_actions": allowed_review_actions(issue.review_status)}
    )


def _with_history(uow: UnitOfWork, issue: ValidationIssue) -> IssueDetail:
    history = uow.audit.list_for_entity(EntityType.ISSUE, issue.issue_id)
    return IssueDetail(issue=view(issue), history=history)


def _load(uow: UnitOfWork, issue_id: str) -> ValidationIssue:
    issue = uow.issues.get(issue_id)
    if issue is None:
        raise NotFoundError(f"Unknown issue {issue_id!r}.")
    return issue


def get(wb: Workbench, issue_id: str) -> IssueDetail:
    with wb.uow() as uow:
        return _with_history(uow, _load(uow, issue_id))


def review(
    wb: Workbench,
    issue_id: str,
    *,
    status: ReviewStatus,
    comment: str | None,
    expected_version: int,
) -> IssueDetail:
    if status not in REVIEW_DECISION_TARGETS:
        raise InvalidInputError(
            f"{status.value!r} is set by the correction workflow, not by a review decision.",
            details={"allowed": sorted(s.value for s in REVIEW_DECISION_TARGETS)},
        )
    with wb.uow() as uow:
        issue = _load(uow, issue_id)
        if issue.version != expected_version:
            raise ConflictError(
                "The issue changed since it was loaded; reload it and decide again.",
                details={
                    "issue_id": issue_id,
                    "expected_version": expected_version,
                    "current_version": issue.version,
                },
            )
        reviewed = issue.with_review(status, comment, at=wb.clock.now())
        uow.issues.update(reviewed, expected_version=expected_version)
        wb.audit(
            uow,
            AuditAction.ISSUE_REVIEWED,
            EntityType.ISSUE,
            issue_id,
            f"Review status {issue.review_status.value} → {status.value}",
            before={
                "review_status": issue.review_status.value,
                "reviewer_comment": issue.reviewer_comment,
                "version": issue.version,
            },
            after={
                "review_status": reviewed.review_status.value,
                "reviewer_comment": reviewed.reviewer_comment,
                "version": reviewed.version,
            },
        )
        result = _with_history(uow, reviewed)
    logger.info(  # never the comment: it is the reviewer's free text
        "issue %s reviewed: %s -> %s (version %d)",
        issue_id,
        issue.review_status.value,
        reviewed.review_status.value,
        reviewed.version,
        extra={
            "issue_id": issue_id,
            "review_status": reviewed.review_status.value,
            "version": reviewed.version,
        },
    )
    return result


def correct(
    wb: Workbench,
    issue_id: str,
    *,
    cells: Collection[CellCorrectionInput],
    comment: str | None,
    expected_version: int,
    rerun_validation: bool,
) -> IssueCorrectionResult:
    rerun: str | None = None
    with wb.uow() as uow:
        issue = _load(uow, issue_id)
        if issue.version != expected_version:
            raise ConflictError(
                "The issue changed since it was loaded; reload it and correct again.",
                details={
                    "issue_id": issue_id,
                    "expected_version": expected_version,
                    "current_version": issue.version,
                },
            )
        run = uow.runs.get(issue.validation_run_id)
        if run is None:
            raise NotFoundError(f"Validation run {issue.validation_run_id!r} no longer exists.")
        latest = uow.datasets.get(issue.dataset_id)
        if latest is None:
            raise NotFoundError(f"Dataset {issue.dataset_id!r} no longer exists.")
        if latest.revision != issue.dataset_revision:
            raise ConflictError(
                "The issue points to an older dataset revision; reload the issue register.",
                details={
                    "issue_id": issue_id,
                    "issue_dataset_revision": issue.dataset_revision,
                    "latest_dataset_revision": latest.revision,
                },
            )
        corrected_cells, revised_dataset = _revised_dataset(
            wb, latest, wb.profiles.get(latest.profile_id), cells
        )
        now = wb.clock.now()
        corrected = issue.with_correction(comment, at=now)
        uow.datasets.add(revised_dataset)
        uow.issues.update(corrected, expected_version=expected_version)
        wb.audit(
            uow,
            AuditAction.CORRECTION_PROPOSED,
            EntityType.ISSUE,
            issue_id,
            f"Correction proposed for {len(corrected_cells)} cell(s)",
            context={
                "dataset_id": latest.dataset_id,
                "from_revision": latest.revision,
                "to_revision": revised_dataset.revision,
                "cells": [
                    {
                        "table_id": cell.table_id,
                        "row_id": cell.row_id,
                        "column_id": cell.column_id,
                        "previous_raw_value": cell.previous_raw_value,
                        "corrected_raw_value": cell.corrected_raw_value,
                    }
                    for cell in corrected_cells
                ],
            },
        )
        wb.audit(
            uow,
            AuditAction.CORRECTION_APPLIED,
            EntityType.ISSUE,
            issue_id,
            f"Review status {issue.review_status.value} → {corrected.review_status.value}",
            before={
                "review_status": issue.review_status.value,
                "reviewer_comment": issue.reviewer_comment,
                "version": issue.version,
                "dataset_revision": issue.dataset_revision,
            },
            after={
                "review_status": corrected.review_status.value,
                "reviewer_comment": corrected.reviewer_comment,
                "version": corrected.version,
                "dataset_revision": revised_dataset.revision,
            },
        )
        detail = _with_history(uow, corrected)
        summary = datasets.dataset_summary(wb, revised_dataset)
        if rerun_validation:
            rerun = revised_dataset.dataset_id
    validation_run = (
        None if rerun is None else ValidationRunDetail.model_validate(runs.start(wb, rerun))
    )
    return IssueCorrectionResult(
        issue=detail.issue,
        history=detail.history,
        dataset=summary,
        validation_run=validation_run,
        corrected_cells=corrected_cells,
    )


def _revised_dataset(
    wb: Workbench,
    dataset: Dataset,
    profile: DomainProfile,
    cells: Collection[CellCorrectionInput],
) -> tuple[list[CorrectedCell], Dataset]:
    requested = list(cells)
    if not requested:
        raise InvalidInputError("At least one corrected cell is required.")
    parser = CellParser(
        profile,
        UnitCatalog.from_profile(profile),
        CurrencyResolver.from_profile(profile),
        {},
    )
    updates: dict[str, dict[str, dict[str, Cell]]] = defaultdict(lambda: defaultdict(dict))
    corrected: list[CorrectedCell] = []
    seen: set[tuple[str, str, str]] = set()
    for request in requested:
        key = (request.table_id, request.row_id, request.column_id)
        if key in seen:
            raise InvalidInputError(
                "A corrected cell is listed more than once.",
                details={
                    "table_id": request.table_id,
                    "row_id": request.row_id,
                    "column_id": request.column_id,
                },
            )
        seen.add(key)
        table = dataset.table(request.table_id)
        row = table.row(request.row_id)
        column = table.column(request.column_id)
        current = row.cells[request.column_id]
        field = profile.field(column.mapping.field_id) if column.mapping is not None else None
        next_cell = _corrected_cell(parser, row, column, current, field, request.value)
        if next_cell == current:
            continue
        updates[request.table_id][request.row_id][request.column_id] = next_cell
        corrected.append(
            CorrectedCell(
                table_id=request.table_id,
                row_id=request.row_id,
                column_id=request.column_id,
                previous_raw_value=current.raw_value,
                corrected_raw_value=next_cell.raw_value,
                previous_data_type=current.data_type,
                corrected_data_type=next_cell.data_type,
                previous_parse_status=current.parse_status,
                corrected_parse_status=next_cell.parse_status,
            )
        )
    if not corrected:
        raise InvalidInputError("No correction changed a cell value.")
    tables: list[Table] = []
    for table in dataset.tables:
        by_row = updates.get(table.table_id)
        if not by_row:
            tables.append(table)
            continue
        rows: list[Row] = []
        for row in table.rows:
            by_column = by_row.get(row.row_id)
            if not by_column:
                rows.append(row)
                continue
            rows.append(row.evolve(cells={**row.cells, **by_column}))
        tables.append(table.evolve(rows=rows))
    revised = dataset.evolve(
        tables=tables,
        revision=dataset.revision + 1,
        parent_revision=dataset.revision,
        created_at=wb.clock.now(),
    )
    return corrected, revised


def _corrected_cell(
    parser: CellParser,
    row: Row,
    column: Column,
    current: Cell,
    field: SemanticField | None,
    value: str | None,
) -> Cell:
    raw = RawCell(
        row=row.source_row_number,
        column=column.source_column_number,
        value_type=RawValueType.STRING,
        text=value,
        number_format=current.number_format,
        confidence=current.extraction_confidence,
    )
    draft = parser.draft(raw, field)
    resolved = None
    if draft.kind == "ambiguous" and column.decimal_separator in (".", ","):
        separator = column.decimal_separator
        resolved = (
            separator,
            f"Decimal separator '{separator}' inferred from this column's parsing evidence.",
        )
    return finish(raw, draft, current.source, resolved)
