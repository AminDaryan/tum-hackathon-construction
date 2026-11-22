"""In-memory persistence adapter: the reference implementation services are tested against.

Each table is a dict of immutable models plus their projected columns
(:mod:`app.repositories.records`). Ordering, filtering, paging and counting evaluate the same
specs as the SQL adapter (:mod:`app.repositories.querying`), and the same integrity rules are
enforced (duplicate keys are refused, a dataset's document and an issue's validation run must
exist, payloads must be strict JSON), so a service tested here behaves the same on SQLite or
PostgreSQL.

Records are stored as the SQL adapter returns them: documents, runs, issues and audit events
are rebuilt from their JSON payload, so values in ``Any``-typed fields (``AuditEvent.context``
and the like) come back in their JSON form here too, e.g. a Decimal as a string. Datasets are
kept as given, as the SQL adapter's write-through cache does (the Dataset model has no
``Any``-typed field, so its JSON snapshot decodes to an equal dataset).

Transactions: a unit of work holds the database's :class:`ExclusiveLock` for its whole block
(one unit of work at a time), snapshots every dict on entry (shallow copies suffice because the
models are immutable), writes directly and restores the snapshot if the block raises. A clean
exit keeps the writes; that is the commit.
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.errors import NotFoundError
from app.models.audit import AuditEvent, EntityType
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.explanation import Explanation
from app.models.issue import ValidationIssue
from app.models.project import Project
from app.models.run import RunStatus, ValidationRun
from app.models.user import User
from app.repositories.base import (
    AuditRepository,
    DatasetCounts,
    DatasetRepository,
    DocumentRepository,
    ExplanationRepository,
    IssueCounts,
    IssueQuery,
    IssueRepository,
    Page,
    ProjectRepository,
    UserRepository,
    ValidationRunRepository,
)
from app.repositories.errors import IntegrityViolationError, PersistenceError, UnitOfWorkError
from app.repositories.querying import (
    AUDIT_ORDER,
    COUNT_COLUMNS,
    DATASET_ORDER,
    DOCUMENT_ORDER,
    EXPLANATION_ORDER,
    ISSUE_ORDER,
    REVIEWED_ORDER,
    RUN_ORDER,
    IssueCondition,
    SortTerm,
    build_issue_counts,
    carried_decisions,
    check_paging,
    entity_type_value,
    issue_column_value,
    issue_conditions,
    latest_dataset_key,
    latest_reviews,
    reviewed_conditions,
)
from app.repositories.records import (
    Columns,
    audit_columns,
    dataset_columns,
    describe,
    document_columns,
    explanation_columns,
    issue_columns,
    load_model,
    run_columns,
    to_payload,
)
from app.repositories.transactions import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    ExclusiveLock,
    UnitOfWorkBase,
    UnitOfWorkScope,
)
from app.repositories.versions import check_successor_version, stale_version

ModelT = TypeVar("ModelT")
KeyT = TypeVar("KeyT")
PayloadModelT = TypeVar("PayloadModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StoredRecord(Generic[ModelT]):
    """A stored model with its projected columns, including the insertion ``seq``."""

    columns: Mapping[str, Any]
    model: ModelT


Snapshot = tuple[dict[Any, StoredRecord[Any]], ...]


class InMemoryDatabase:
    """Process-local tables shared by all units of work created for it."""

    def __init__(self, *, lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS) -> None:
        self.documents: dict[str, StoredRecord[Document]] = {}
        self.datasets: dict[tuple[str, int], StoredRecord[Dataset]] = {}
        self.runs: dict[str, StoredRecord[ValidationRun]] = {}
        self.issues: dict[str, StoredRecord[ValidationIssue]] = {}
        self.audit_events: dict[str, StoredRecord[AuditEvent]] = {}
        self.explanations: dict[str, StoredRecord[Explanation]] = {}
        self.projects: dict[str, StoredRecord[Project]] = {}
        self.users: dict[str, StoredRecord[User]] = {}
        self.lock = ExclusiveLock("the in-memory database", timeout_seconds=lock_timeout_seconds)
        self._sequence = itertools.count(1)

    def new_record(self, columns: Columns, model: ModelT) -> StoredRecord[ModelT]:
        """A record that takes the next insertion sequence number."""
        return StoredRecord({**columns, "seq": next(self._sequence)}, model)

    def snapshot(self) -> Snapshot:
        return tuple(dict(table) for table in self._tables())

    def restore(self, snapshot: Snapshot) -> None:
        for table, saved in zip(self._tables(), snapshot, strict=True):
            table.clear()
            table.update(saved)

    def _tables(self) -> Snapshot:
        return (
            self.documents,
            self.datasets,
            self.runs,
            self.issues,
            self.audit_events,
            self.explanations,
            self.projects,
            self.users,
        )


# --------------------------------------------------------------------------- helpers
def _as_stored(model: PayloadModelT) -> PayloadModelT:
    """``model`` as the SQL adapter returns it: rebuilt from its strict-JSON payload (which also
    leaves the stored record sharing no mutable state with the caller's object)."""
    return load_model(type(model), to_payload(model), what=describe(model))


def _replaced(record: StoredRecord[Any], columns: Columns, model: ModelT) -> StoredRecord[ModelT]:
    """``record`` with new columns and model, keeping its insertion position (like UPDATE)."""
    return StoredRecord({**columns, "seq": record.columns["seq"]}, model)


def _ensure_new(table: Mapping[Any, Any], key: Any, what: str) -> None:
    if key in table:
        raise IntegrityViolationError(f"Cannot store {what}: it already exists.")


def _ensure_referenced(table: Mapping[Any, Any], key: Any, what: str, target: str) -> None:
    if key not in table:
        raise IntegrityViolationError(f"Cannot store {what}: {target} does not exist.")


def _existing(
    table: Mapping[KeyT, StoredRecord[ModelT]], key: KeyT, what: str
) -> StoredRecord[ModelT]:
    record = table.get(key)
    if record is None:
        raise NotFoundError(f"Cannot update {what}: it does not exist.")
    return record


def _model_or_none(record: StoredRecord[ModelT] | None) -> ModelT | None:
    return record.model if record is not None else None


def _ordered(
    records: Iterable[StoredRecord[ModelT]], order: Sequence[SortTerm]
) -> list[StoredRecord[ModelT]]:
    """Python evaluation of an ORDER BY spec: one stable sort per term, last term first."""
    ordered = list(records)
    for term in reversed(order):
        ordered.sort(key=partial(_sort_key, term), reverse=term.descending)
    return ordered


def _sort_key(term: SortTerm, record: StoredRecord[Any]) -> tuple[Any, ...]:
    value = issue_column_value(record.columns, term.column)
    if term.nulls is None:
        if value is None:
            raise PersistenceError(
                f"Column {term.column!r} is NULL although its ordering declares it NOT NULL."
            )
        return (value,)
    # The rank the sort direction puts first goes to the group that must lead.
    leading_rank = 1 if term.descending else 0
    null_rank = leading_rank if term.nulls == "first" else 1 - leading_rank
    return (null_rank,) if value is None else (1 - null_rank, value)


def _page(records: Sequence[StoredRecord[ModelT]], offset: int, limit: int) -> Page[ModelT]:
    items = [record.model for record in records[offset : offset + limit]]
    return Page(items=items, total=len(records), offset=offset, limit=limit)


# ---------------------------------------------------------------------- repositories
class _Repository:
    def __init__(self, scope: UnitOfWorkScope[InMemoryDatabase]) -> None:
        self._scope = scope

    @property
    def _db(self) -> InMemoryDatabase:
        return self._scope.resource()


class InMemoryProjectRepository(_Repository):
    def add(self, project: Project) -> None:
        db = self._db
        _ensure_new(db.projects, project.project_id, "project")
        db.projects[project.project_id] = db.new_record({}, _as_stored(project))

    def update(self, project: Project) -> None:
        db = self._db
        current = _existing(db.projects, project.project_id, "project")
        db.projects[project.project_id] = _replaced(current, {}, _as_stored(project))

    def get(self, project_id: str) -> Project | None:
        return _model_or_none(self._db.projects.get(project_id))

    def list(self) -> list[Project]:
        return [record.model for _, record in sorted(self._db.projects.items())]


class InMemoryUserRepository(_Repository):
    def add(self, user: User) -> None:
        db = self._db
        _ensure_new(db.users, user.user_id, f"user {user.user_id!r}")
        _ensure_unique_token(db.users, user)
        db.users[user.user_id] = db.new_record({}, _as_stored(user))

    def update(self, user: User) -> None:
        db = self._db
        current = _existing(db.users, user.user_id, f"user {user.user_id!r}")
        _ensure_unique_token(db.users, user)
        db.users[user.user_id] = _replaced(current, {}, _as_stored(user))

    def delete(self, user_id: str) -> None:
        if self._db.users.pop(user_id, None) is None:
            raise NotFoundError(f"Cannot delete user {user_id!r}: it does not exist.")

    def get(self, user_id: str) -> User | None:
        return _model_or_none(self._db.users.get(user_id))

    def by_token_digest(self, token_digest: str) -> User | None:
        for record in self._db.users.values():
            if record.model.token_digest == token_digest:
                return record.model
        return None

    def list(self) -> list[User]:
        return sorted(
            (record.model for record in self._db.users.values()),
            key=lambda user: (user.name.casefold(), user.user_id),
        )


def _ensure_unique_token(users: Mapping[str, StoredRecord[User]], user: User) -> None:
    """The SQL adapter's unique index on the token digest."""
    if user.token_digest is None:
        return
    for user_id, record in users.items():
        if user_id != user.user_id and record.model.token_digest == user.token_digest:
            raise IntegrityViolationError(f"Cannot store user {user.user_id!r}: duplicate token.")


class InMemoryDocumentRepository(_Repository):
    def add(self, document: Document) -> None:
        db = self._db
        stored = _as_stored(document)
        _ensure_new(db.documents, document.document_id, describe(document))
        db.documents[document.document_id] = db.new_record(document_columns(stored), stored)

    def update(self, document: Document) -> None:
        db = self._db
        stored = _as_stored(document)
        current = _existing(db.documents, document.document_id, describe(document))
        db.documents[document.document_id] = _replaced(current, document_columns(stored), stored)

    def get(self, document_id: str) -> Document | None:
        return _model_or_none(self._db.documents.get(document_id))

    def list(self, *, offset: int = 0, limit: int = 50) -> Page[Document]:
        check_paging(offset, limit)
        return _page(_ordered(self._db.documents.values(), DOCUMENT_ORDER), offset, limit)


class InMemoryDatasetRepository(_Repository):
    def add(self, dataset: Dataset) -> None:
        """Stores ``dataset`` itself after the checks the SQL adapter's snapshot encoding makes
        (see the module docstring)."""
        db = self._db
        to_payload(dataset)
        key = (dataset.dataset_id, dataset.revision)
        what = describe(dataset)
        _ensure_new(db.datasets, key, what)
        _ensure_referenced(
            db.documents, dataset.document_id, what, f"its document {dataset.document_id!r}"
        )
        db.datasets[key] = db.new_record(dataset_columns(dataset), dataset)

    def get(self, dataset_id: str, revision: int | None = None) -> Dataset | None:
        """Latest revision when ``revision`` is None."""
        datasets = self._db.datasets
        if revision is None:
            revisions = [rev for stored_id, rev in datasets if stored_id == dataset_id]
            if not revisions:
                return None
            revision = max(revisions)
        return _model_or_none(datasets.get((dataset_id, revision)))

    def list_for_document(self, document_id: str) -> list[Dataset]:
        """All revisions of the document's datasets, oldest first."""
        return [record.model for record in self._document_revisions(document_id)]

    def latest_for_document(self, document_id: str) -> Dataset | None:
        """The latest dataset by creation at its highest revision (rule:
        :func:`~app.repositories.querying.latest_dataset_key`)."""
        revisions = self._document_revisions(document_id)
        key = latest_dataset_key(
            (record.columns["dataset_id"], record.columns["revision"]) for record in revisions
        )
        return None if key is None else self._db.datasets[key].model

    def latest_counts_for_document(self, document_id: str) -> DatasetCounts | None:
        latest = self.latest_for_document(document_id)
        return None if latest is None else DatasetCounts.of(latest)

    def _document_revisions(self, document_id: str) -> list[StoredRecord[Dataset]]:
        records = [r for r in self._db.datasets.values() if r.columns["document_id"] == document_id]
        return _ordered(records, DATASET_ORDER)


class InMemoryValidationRunRepository(_Repository):
    def add(self, run: ValidationRun) -> None:
        db = self._db
        stored = _as_stored(run)
        _ensure_new(db.runs, run.run_id, describe(run))
        db.runs[run.run_id] = db.new_record(run_columns(stored), stored)

    def update(self, run: ValidationRun) -> None:
        db = self._db
        stored = _as_stored(run)
        current = _existing(db.runs, run.run_id, describe(run))
        db.runs[run.run_id] = _replaced(current, run_columns(stored), stored)

    def get(self, run_id: str) -> ValidationRun | None:
        return _model_or_none(self._db.runs.get(run_id))

    def list_for_dataset(self, dataset_id: str) -> list[ValidationRun]:
        """Runs of every revision of the dataset, newest started first."""
        records = [r for r in self._db.runs.values() if r.columns["dataset_id"] == dataset_id]
        return [record.model for record in _ordered(records, RUN_ORDER)]

    def latest_for_dataset(self, dataset_id: str) -> ValidationRun | None:
        runs = self.list_for_dataset(dataset_id)
        return runs[0] if runs else None

    def list_with_status(self, statuses: Collection[RunStatus]) -> list[ValidationRun]:
        wanted = {RunStatus(status).value for status in statuses}
        records = [r for r in self._db.runs.values() if r.columns["status"] in wanted]
        return [record.model for record in _ordered(records, RUN_ORDER)]


class InMemoryIssueRepository(_Repository):
    def add_many(self, issues: Sequence[ValidationIssue]) -> None:
        """All or nothing: the whole batch is checked before anything is stored."""
        db = self._db
        batch = [_as_stored(issue) for issue in issues]
        counts = Counter(issue.issue_id for issue in batch)
        duplicates = sorted(
            {issue_id for issue_id, n in counts.items() if n > 1} | (counts.keys() & db.issues)
        )
        if duplicates:
            raise IntegrityViolationError(
                f"Cannot store issues: issue id(s) {', '.join(duplicates)} already exist or "
                "repeat within the batch.",
                details={"issue_ids": duplicates},
            )
        missing_runs = sorted({issue.validation_run_id for issue in batch} - db.runs.keys())
        if missing_runs:
            raise IntegrityViolationError(
                f"Cannot store issues: validation run(s) {', '.join(missing_runs)} do not exist.",
                details={"run_ids": missing_runs},
            )
        for issue in batch:
            db.issues[issue.issue_id] = db.new_record(issue_columns(issue), issue)

    def get(self, issue_id: str) -> ValidationIssue | None:
        return _model_or_none(self._db.issues.get(issue_id))

    def update(self, issue: ValidationIssue, *, expected_version: int) -> None:
        """Compare-and-set on the stored version, in the SQL adapter's order of checks: the
        version arithmetic, existence, the stored version, then the run reference. Every
        indexed column (review status, effective evidence class, version…) is recomputed."""
        check_successor_version(issue, expected_version)
        db = self._db
        stored = _as_stored(issue)
        what = describe(issue)
        current = _existing(db.issues, issue.issue_id, what)
        current_version = current.columns["version"]
        if current_version != expected_version:
            raise stale_version(
                issue.issue_id, expected_version=expected_version, current_version=current_version
            )
        _ensure_referenced(
            db.runs, issue.validation_run_id, what, f"validation run {issue.validation_run_id!r}"
        )
        db.issues[issue.issue_id] = _replaced(current, issue_columns(stored), stored)

    def reviewed_by_fingerprint(
        self, document_id: str, fingerprints: Collection[str]
    ) -> dict[str, ValidationIssue]:
        """Evaluates the shared conditions and :data:`REVIEWED_ORDER` in Python."""
        candidates = _ordered(
            self._where(reviewed_conditions(document_id, fingerprints)), REVIEWED_ORDER
        )
        return carried_decisions(
            latest_reviews(
                fingerprints,
                ((record.columns["fingerprint"], record.model) for record in candidates),
            )
        )

    def query(
        self, query: IssueQuery, *, offset: int = 0, limit: int = 100
    ) -> Page[ValidationIssue]:
        check_paging(offset, limit)
        return _page(self._matching(query), offset, limit)

    def counts(self, query: IssueQuery) -> IssueCounts:
        groups = Counter(
            tuple(record.columns[column] for column in COUNT_COLUMNS)
            for record in self._filtered(query)
        )
        return build_issue_counts(groups.items())

    def change_mark(self, query: IssueQuery) -> tuple[int, int]:
        records = self._filtered(query)
        return len(records), sum(record.columns["version"] for record in records)

    def iter_all(self, query: IssueQuery) -> Iterator[ValidationIssue]:
        """Every match in query order; the matches are fixed when iteration starts. Consume it
        inside the unit of work: the next item after its block ends raises."""
        for record in self._matching(query):
            self._scope.ensure_open()
            yield record.model

    def _filtered(self, query: IssueQuery) -> list[StoredRecord[ValidationIssue]]:
        return self._where(issue_conditions(query))

    def _where(self, conditions: Sequence[IssueCondition]) -> list[StoredRecord[ValidationIssue]]:
        """Python evaluation of shared conditions (AND across, OR within)."""
        return [
            record
            for record in self._db.issues.values()
            if all(
                issue_column_value(record.columns, column) in accepted
                for column, accepted in conditions
            )
        ]

    def _matching(self, query: IssueQuery) -> list[StoredRecord[ValidationIssue]]:
        return _ordered(self._filtered(query), ISSUE_ORDER)


class InMemoryAuditRepository(_Repository):
    def append(self, event: AuditEvent) -> None:
        db = self._db
        stored = _as_stored(event)
        _ensure_new(db.audit_events, event.event_id, describe(event))
        db.audit_events[event.event_id] = db.new_record(audit_columns(stored), stored)

    def list_for_entity(self, entity_type: EntityType | str, entity_id: str) -> list[AuditEvent]:
        """The entity's events, oldest first (appending order for identical timestamps)."""
        stored_type = entity_type_value(entity_type)
        records = [
            r
            for r in self._db.audit_events.values()
            if r.columns["entity_type"] == stored_type and r.columns["entity_id"] == entity_id
        ]
        return [record.model for record in _ordered(records, AUDIT_ORDER)]


class InMemoryExplanationRepository(_Repository):
    def add(self, explanation: Explanation) -> None:
        db = self._db
        stored = _as_stored(explanation)
        what = describe(explanation)
        _ensure_new(db.explanations, explanation.explanation_id, what)
        _ensure_referenced(
            db.runs, explanation.run_id, what, f"validation run {explanation.run_id!r}"
        )
        db.explanations[explanation.explanation_id] = db.new_record(
            explanation_columns(stored), stored
        )

    def update(self, explanation: Explanation) -> None:
        db = self._db
        stored = _as_stored(explanation)
        what = describe(explanation)
        current = _existing(db.explanations, explanation.explanation_id, what)
        _ensure_referenced(
            db.runs, explanation.run_id, what, f"validation run {explanation.run_id!r}"
        )
        db.explanations[explanation.explanation_id] = _replaced(
            current, explanation_columns(stored), stored
        )

    def get(self, explanation_id: str) -> Explanation | None:
        return _model_or_none(self._db.explanations.get(explanation_id))

    def latest_for_problem(self, run_id: str, problem_id: str) -> Explanation | None:
        records = [
            r
            for r in self._db.explanations.values()
            if r.columns["run_id"] == run_id and r.columns["problem_id"] == problem_id
        ]
        ordered = _ordered(records, EXPLANATION_ORDER)
        return ordered[0].model if ordered else None

    def list_for_run(self, run_id: str) -> list[Explanation]:
        records = [r for r in self._db.explanations.values() if r.columns["run_id"] == run_id]
        return [record.model for record in _ordered(records, EXPLANATION_ORDER)]


# ---------------------------------------------------------------------- unit of work
class InMemoryUnitOfWork(UnitOfWorkBase[InMemoryDatabase]):
    """One transaction on an :class:`InMemoryDatabase` (see the module docstring)."""

    def __init__(self, database: InMemoryDatabase) -> None:
        super().__init__("in-memory unit of work")
        self._database = database
        self._snapshot: Snapshot | None = None
        self.documents: DocumentRepository = InMemoryDocumentRepository(self._scope)
        self.datasets: DatasetRepository = InMemoryDatasetRepository(self._scope)
        self.runs: ValidationRunRepository = InMemoryValidationRunRepository(self._scope)
        self.issues: IssueRepository = InMemoryIssueRepository(self._scope)
        self.audit: AuditRepository = InMemoryAuditRepository(self._scope)
        self.explanations: ExplanationRepository = InMemoryExplanationRepository(self._scope)
        self.projects: ProjectRepository = InMemoryProjectRepository(self._scope)
        self.users: UserRepository = InMemoryUserRepository(self._scope)

    def _begin(self, resources: ExitStack) -> InMemoryDatabase:
        resources.enter_context(self._database.lock.hold())
        self._snapshot = self._database.snapshot()
        return self._database

    def _finish(self, resource: InMemoryDatabase, *, failed: bool) -> None:
        snapshot, self._snapshot = self._snapshot, None
        if not failed:
            return
        if snapshot is None:  # pragma: no cover - _begin always takes one
            raise UnitOfWorkError("The in-memory unit of work has no snapshot to roll back to.")
        resource.restore(snapshot)


class InMemoryUnitOfWorkFactory:
    """:class:`~app.repositories.base.UnitOfWorkFactory` for the in-memory adapter."""

    def __init__(self, database: InMemoryDatabase | None = None) -> None:
        self.database = database if database is not None else InMemoryDatabase()

    def __call__(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self.database)
