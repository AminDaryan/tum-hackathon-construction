"""Datasets: the dataset summary, pages of canonical rows and the workspace summary."""

from __future__ import annotations

from collections import Counter

from app.core.errors import ConflictError, NotFoundError
from app.models.audit import AuditAction, EntityType
from app.models.dataset import Dataset, Row, RowKind
from app.models.issue import EvidenceClass, ReviewStatus
from app.normalization.revise import CellCorrection, revise
from app.repositories.base import IssueQuery, UnitOfWork
from app.repositories.errors import IntegrityViolationError
from app.schemas.datasets import (
    CorrectionsResult,
    DatasetSummary,
    RowPage,
    TableSummary,
    WorkspaceCounts,
    WorkspaceRun,
    WorkspaceSummary,
)
from app.services.workbench import Workbench


def load(uow: UnitOfWork, dataset_id: str) -> Dataset:
    dataset = uow.datasets.get(dataset_id)
    if dataset is None:
        raise NotFoundError(f"Unknown dataset {dataset_id!r}.")
    return dataset


def _required_missing(wb: Workbench, dataset: Dataset) -> dict[str, list[str]]:
    try:
        profile = wb.profiles.get(dataset.profile_id)
    except NotFoundError:  # a profile removed since: nothing to compare with
        return {}
    required = [field.field_id for field in profile.fields if field.required]
    missing = {
        table.table_id: [f for f in required if table.column_for_field(f) is None]
        for table in dataset.tables
    }
    return {table_id: fields for table_id, fields in missing.items() if fields}


def summary(wb: Workbench, dataset_id: str) -> DatasetSummary:
    with wb.uow() as uow:
        dataset = load(uow, dataset_id)
    return dataset_summary(wb, dataset)


def dataset_summary(wb: Workbench, dataset: Dataset) -> DatasetSummary:
    """Everything about a dataset except its rows."""
    return DatasetSummary(
        dataset_id=dataset.dataset_id,
        document_id=dataset.document_id,
        revision=dataset.revision,
        parent_revision=dataset.parent_revision,
        profile_id=dataset.profile_id,
        profile_version=dataset.profile_version,
        created_at=dataset.created_at,
        extraction=dataset.extraction,
        tables=[
            TableSummary(
                table_id=table.table_id,
                name=table.name,
                source=table.source,
                header=table.header,
                row_count=len(table.rows),
                row_kind_counts=dict(Counter(row.kind for row in table.rows)),
                columns=table.columns,
            )
            for table in dataset.tables
        ],
        required_fields_missing=_required_missing(wb, dataset),
    )


def rows(
    wb: Workbench,
    dataset_id: str,
    table_id: str,
    *,
    offset: int,
    limit: int,
    row_id: str | None = None,
) -> RowPage:
    """A page of the latest revision's rows; with ``row_id``, the page that holds that row
    (``offset`` is then ignored and the response says which page it is)."""
    with wb.uow() as uow:
        dataset = load(uow, dataset_id)
    tables = [table for table in dataset.tables if table.table_id == table_id]
    if not tables:
        raise NotFoundError(f"Table {table_id!r} is not part of dataset {dataset_id!r}.")
    table = tables[0]
    if row_id is not None:
        index = next((i for i, row in enumerate(table.rows) if row.row_id == row_id), None)
        if index is None:
            raise NotFoundError(f"Row {row_id!r} is not part of table {table_id!r}.")
        offset = (index // limit) * limit
    return RowPage(
        items=table.rows[offset : offset + limit],
        total=len(table.rows),
        offset=offset,
        limit=limit,
    )


def workspace_summary(wb: Workbench, dataset_id: str, run_id: str | None) -> WorkspaceSummary:
    with wb.uow() as uow:
        dataset = load(uow, dataset_id)
        if run_id is None:
            run = uow.runs.latest_for_dataset(dataset_id)
        else:
            run = uow.runs.get(run_id)
            if run is None or run.dataset_id != dataset_id:
                raise NotFoundError(f"Unknown validation run {run_id!r} for this dataset.")
        counts = uow.issues.counts(IssueQuery(run_id=run.run_id)) if run is not None else None
    columns = [column for table in dataset.tables for column in table.columns]
    missing = _required_missing(wb, dataset)
    by_class = counts.by_evidence_class if counts is not None else {}
    by_status = counts.by_review_status if counts is not None else {}
    return WorkspaceSummary(
        dataset_id=dataset.dataset_id,
        document_id=dataset.document_id,
        revision=dataset.revision,
        table_count=len(dataset.tables),
        rows_processed=sum(len(table.rows) for table in dataset.tables),
        item_rows=sum(
            1 for table in dataset.tables for row in table.rows if row.kind is RowKind.ITEM
        ),
        columns_total=len(columns),
        columns_mapped=sum(1 for column in columns if column.mapping is not None),
        required_fields_missing=sorted({f for fields in missing.values() for f in fields}),
        extraction_quality=dataset.extraction.quality,
        extraction_warning_count=len(dataset.extraction.warnings),
        run=(
            None
            if run is None
            else WorkspaceRun(
                run_id=run.run_id,
                status=run.status,
                review_status=run.review_status,
                review_finished_at=run.review_finished_at,
                started_at=run.started_at,
                planner=run.plan.planner,
                finished_at=run.finished_at,
            )
        ),
        counts=WorkspaceCounts(
            total=counts.total if counts is not None else 0,
            pending_review=by_status.get(ReviewStatus.PENDING_REVIEW.value, 0),
            **{cls.value: by_class.get(cls.value, 0) for cls in EvidenceClass},
        ),
    )


def correct(
    wb: Workbench,
    dataset_id: str,
    *,
    expected_revision: int,
    corrections: list[CellCorrection],
) -> CorrectionsResult:
    """Store the corrected cells as the dataset's next revision (ADR 0001), with one audit
    event per changed cell. ``expected_revision`` must be the latest revision."""
    with wb.uow() as uow:
        dataset = load(uow, dataset_id)
        if dataset.revision != expected_revision:
            raise ConflictError(
                f"The table is at revision {dataset.revision}; the change was made on revision"
                f" {expected_revision}. Reload the table and make the change again.",
                details={
                    "dataset_id": dataset_id,
                    "expected_revision": expected_revision,
                    "current_revision": dataset.revision,
                },
            )
        profile = wb.profiles.get(dataset.profile_id)
        revised, applied = revise(dataset, corrections, profile=profile, created_at=wb.clock.now())
        if applied:
            try:
                uow.datasets.add(revised)
            except IntegrityViolationError as exc:
                # Another correction stored this revision between our read and our write.
                raise ConflictError(
                    f"The table changed to revision {revised.revision} while this change was"
                    " saved. Reload the table and make the change again.",
                    details={
                        "dataset_id": dataset_id,
                        "expected_revision": expected_revision,
                        "current_revision": revised.revision,
                    },
                ) from exc
            for change in applied:
                wb.audit(
                    uow,
                    AuditAction.CORRECTION_APPLIED,
                    EntityType.DATASET,
                    dataset_id,
                    f"Cell {change.reference} of '{change.table_name}' corrected in revision"
                    f" {revised.revision}",
                    before={"revision": dataset.revision, "raw_value": change.before.raw_value},
                    after={"revision": revised.revision, "raw_value": change.after.raw_value},
                    context={
                        "table_id": change.table_id,
                        "row_id": change.row_id,
                        "column_id": change.column_id,
                        "reference": change.reference,
                    },
                )
    changed_rows = {(change.table_id, change.row_id) for change in applied}
    rows_out: list[Row] = [
        row
        for table in revised.tables
        for row in table.rows
        if (table.table_id, row.row_id) in changed_rows
    ]
    return CorrectionsResult(
        dataset_id=revised.dataset_id,
        revision=revised.revision,
        parent_revision=revised.parent_revision,
        changed=len(applied),
        rows=rows_out,
    )
