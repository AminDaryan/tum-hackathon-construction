"""Project membership and bounded background validation of every bill, with source comparison."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from decimal import Decimal
from functools import partial
from typing import Any, Literal

from app.core.errors import ConflictError, NotFoundError
from app.models.dataset import Dataset, RowKind
from app.models.project import FileGroup, Project, ProjectCheck, ProjectFile, ProjectValidation
from app.models.values import NumberValue, TextValue
from app.repositories.base import UnitOfWork
from app.risk.service import clarification_questions
from app.schemas.documents import DocumentSummary
from app.services import documents, runs
from app.services.jobs import JobQueueFullError, JobRunnerClosedError
from app.services.workbench import Workbench

logger = logging.getLogger(__name__)


def load(uow: UnitOfWork, project_id: str) -> Project:
    project = uow.projects.get(project_id)
    if project is None:
        raise NotFoundError(f"Unknown project {project_id!r}.")
    return project


def create(
    wb: Workbench, name: str, description: str = "", assignees: Sequence[str] = ()
) -> Project:
    project = Project(
        project_id=wb.ids.new("prj"),
        name=name,
        description=description,
        created_at=wb.clock.now(),
        assignees=list(assignees),
    )
    with wb.uow() as uow:
        uow.projects.add(project)
    return project


def update(wb: Workbench, project_id: str, changes: Mapping[str, Any]) -> Project:
    """Change the project's details (name, description, assigned users, status, decision
    cutoff). Its files and validation are left as they are."""
    with wb.uow() as uow:
        project = load(uow, project_id)
        if changes:
            project = project.evolve(**changes)
            uow.projects.update(project)
    return project


def membership(
    wb: Workbench,
    project_id: str,
    document_id: str,
    *,
    role: Literal["bill", "reference"] = "bill",
    remove: bool = False,
) -> Project:
    with wb.uow() as uow:
        project = load(uow, project_id)
        if project.validation and project.validation.status == "running":
            raise ConflictError("Wait for project validation to finish before changing its files.")
        if uow.documents.get(document_id) is None:
            raise NotFoundError(f"Unknown document {document_id!r}.")
        files = [file for file in project.files if file.document_id != document_id]
        if not remove:
            files.append(ProjectFile(document_id=document_id, role=role))
        project = project.evolve(files=files, validation=None)
        uow.projects.update(project)
    return project


def check_bills_soon(wb: Workbench, project: Project, document_id: str) -> None:
    """After ``document_id`` was added to, removed from or moved in ``project``: queue a
    background validation of it and of each of the project's bills whose inputs changed, since
    this can change which tender a bid is compared with (:mod:`app.services.tenders`). Bills
    whose inputs are the same are left alone."""
    bills = [file.document_id for file in project.files if file.group != "support"]
    for bill in dict.fromkeys([document_id, *bills]):
        with wb.uow() as uow:
            dataset = uow.datasets.latest_for_document(bill)
        if dataset is not None:
            runs.check_soon(wb, dataset.dataset_id)


def group_of(file: ProjectFile, format: str, has_table: bool) -> FileGroup:
    """Whether a project file is a bill (opened in the table view, validated, compared) or a
    supporting document (a drawing, report or spec, opened as the document itself). A person's
    choice wins. GAEB, Excel and CSV files are bills; a PDF or Word file is a bill when a bill
    table was read from it, else supporting material."""
    if file.group is not None:
        return file.group
    return "support" if format in {"pdf", "docx"} and not has_table else "bill"


def groups(project: Project, docs: Iterable[DocumentSummary]) -> dict[str, FileGroup]:
    files = {file.document_id: file for file in project.files}
    return {
        doc.document_id: group_of(files[doc.document_id], doc.format, doc.table_count > 0)
        for doc in docs
        if doc.document_id in files
    }


def move(wb: Workbench, project_id: str, document_id: str, group: FileGroup) -> Project:
    """Put a project file among the bills or the supporting documents. A file moved out of the
    bills leaves the last validation's results; one moved in waits for the next validation."""
    with wb.uow() as uow:
        project = load(uow, project_id)
        if project.validation and project.validation.status == "running":
            raise ConflictError("Wait for project validation to finish before changing its files.")
        if not any(file.document_id == document_id for file in project.files):
            raise NotFoundError(f"Document {document_id!r} is not in this project.")
        files = [
            file.evolve(group=group) if file.document_id == document_id else file
            for file in project.files
        ]
        validation = project.validation
        if validation and group == "support":
            validation = validation.evolve(
                runs={k: v for k, v in validation.runs.items() if k != document_id},
                skipped={k: v for k, v in validation.skipped.items() if k != document_id},
            )
        project = project.evolve(files=files, validation=validation)
        uow.projects.update(project)
    return project


def summaries(wb: Workbench, project: Project) -> list[DocumentSummary]:
    with wb.uow() as uow:
        return [
            documents.summary(uow, doc)
            for file in project.files
            if (doc := uow.documents.get(file.document_id)) is not None
        ]


def start(wb: Workbench, project_id: str) -> Project:
    wb.jobs.ensure_capacity()
    with wb.uow() as uow:
        project = load(uow, project_id)
        if project.preparation != "ready":
            raise ConflictError("This project's demo files are not ready yet.")
        if project.validation and project.validation.status == "running":
            raise ConflictError("This project is already being validated.")
        project = project.evolve(validation=ProjectValidation(started_at=wb.clock.now()))
        uow.projects.update(project)
    try:
        wb.jobs.submit(
            f"project:{project_id}",
            partial(_validate, wb, project),
            on_cancelled=partial(_fail, wb, project_id),
        )
    except Exception:
        _fail(wb, project_id)
        raise
    return project


def _fail(wb: Workbench, project_id: str) -> None:
    with wb.uow() as uow:
        project = load(uow, project_id)
        if project.validation and project.validation.status == "running":
            uow.projects.update(
                project.evolve(
                    validation=project.validation.evolve(
                        status="failed",
                        finished_at=wb.clock.now(),
                        error="Project validation was interrupted. Run it again.",
                    )
                )
            )


def recover_interrupted(wb: Workbench) -> None:
    with wb.uow() as uow:
        ids = [
            p.project_id
            for p in uow.projects.list()
            if p.validation and p.validation.status == "running"
        ]
    for project_id in ids:
        _fail(wb, project_id)


def _validate(wb: Workbench, project: Project) -> None:
    assert project.validation is not None
    result = project.validation

    def sources() -> Iterator[tuple[str, Dataset]]:
        nonlocal result
        # Compare one source at a time; do not retain every large PDF dataset in the batch.
        for file in project.files:
            with wb.uow() as uow:
                dataset = uow.datasets.latest_for_document(file.document_id)
                document = uow.documents.get(file.document_id)
            has_table = dataset is not None and bool(dataset.tables)
            if document is not None and group_of(file, document.format, has_table) == "support":
                result = result.evolve(
                    skipped={**result.skipped, file.document_id: "Supporting document"}
                )
                dataset = None
            elif dataset is None:
                result = result.evolve(
                    skipped={**result.skipped, file.document_id: "No readable tables"}
                )
            else:
                if file.role == "reference":
                    result = result.evolve(
                        skipped={
                            **result.skipped,
                            file.document_id: "Reference: compared, not validated as a bill",
                        }
                    )
                else:
                    run = runs.start(wb, dataset.dataset_id)
                    result = result.evolve(runs={**result.runs, file.document_id: run["run_id"]})
            with wb.uow() as uow:
                uow.projects.update(project.evolve(validation=result))
            if dataset is not None:
                yield file.document_id, dataset

    try:
        comparisons = compare(sources())
        result = result.evolve(
            status="completed",
            finished_at=wb.clock.now(),
            comparisons=comparisons,
        )
        with wb.uow() as uow:
            uow.projects.update(project.evolve(validation=result))
    except Exception:
        logger.exception("Project validation failed for %s", project.project_id)
        _fail(wb, project.project_id)
        return
    _read_questions(wb, project.evolve(validation=result))


def _read_questions(wb: Workbench, project: Project) -> None:
    """Build the clarification questions of every bill of the project now, in the background,
    so its Follow-ups list them at once instead of reading every bill on first view."""
    try:
        clarification_questions(wb, project)
    except Exception:
        logger.exception("Reading the clarification questions failed for %s", project.project_id)


def read_questions_at_start(wb: Workbench) -> None:
    """At start-up, in the background: read the clarification questions of every project once.
    They are kept in memory only, so after a restart the first view would read every bill."""

    def work() -> None:
        with wb.uow() as uow:
            projects = uow.projects.list()
        for project in projects:
            _read_questions(wb, project)

    try:
        wb.jobs.submit("clarification-questions", work, on_cancelled=lambda: None)
    except (JobQueueFullError, JobRunnerClosedError, ValueError):
        logger.warning("The clarification questions were not read at start-up: no free worker")


def compare(sources: Iterable[tuple[str, Dataset]]) -> list[ProjectCheck]:
    """Conservative source differences, not confirmed faults or double-counted costs.

    Item numbers alone repeat between trades. Require the same normalized description and
    unit too. Never infer a missing item from an incomplete extraction or sum alternative
    document representations. Exact decimals compare numerically, not by display precision.
    """
    grouped: dict[tuple[str, str, str, str], dict[str, str]] = defaultdict(dict)
    for document_id, dataset in sources:
        for table in dataset.tables:
            columns = {
                field: table.column_for_field(field)
                for field in ("item_code", "description", "unit", "quantity", "unit_price")
            }
            for row in table.rows:
                if row.excluded or row.classification.kind != RowKind.ITEM:
                    continue
                values = {}
                for field, column in columns.items():
                    cell = row.cells.get(column.column_id) if column else None
                    value = cell.normalized_value if cell else None
                    if isinstance(value, NumberValue | TextValue) and (
                        field not in {"quantity", "unit_price"} or isinstance(value, NumberValue)
                    ):
                        values[field] = str(value.value)
                code, description, unit = (
                    " ".join(values.get(f, "").split()).casefold()
                    for f in ("item_code", "description", "unit")
                )
                if not code or not description or not unit:
                    continue
                for field in ("quantity", "unit_price"):
                    if field in values:
                        grouped[(code, description, unit, field)][document_id] = values[field]
    checks = []
    for (code, _, _, field), values in sorted(grouped.items()):
        if len(values) > 1 and len({Decimal(value) for value in values.values()}) > 1:
            checks.append(
                ProjectCheck(
                    item_code=code,
                    field=field,
                    documents=list(values),
                    values=list(values.values()),
                )
            )
            if len(checks) >= 500:
                break  # bounded response; the UI states the cap
    return checks
