"""Persistence ports. Services depend on these protocols only.

Two implementations exist: ``app.repositories.sql`` (SQLAlchemy Core; SQLite now, PostgreSQL by
changing ``TWB_DATABASE_URL``) and ``app.repositories.memory`` (tests). Canonical datasets are
stored as immutable revision snapshots; issues are stored as rows with indexed filter columns.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from app.models.audit import AuditEvent, EntityType
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.explanation import Explanation
from app.models.finding_category import FindingCategoryKey
from app.models.issue import EvidenceClass, ReviewStatus, Severity, ValidationIssue
from app.models.project import Project
from app.models.run import RunStatus, ValidationRun
from app.models.user import User

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class IssueQuery:
    """Filters combine with AND; values inside one filter combine with OR. Empty = no filter."""

    run_id: str | None = None
    dataset_id: str | None = None
    table_id: str | None = None
    row_id: str | None = None
    severities: frozenset[Severity] = frozenset()
    evidence_classes: frozenset[EvidenceClass] = frozenset()  # matches effective_evidence_class
    review_statuses: frozenset[ReviewStatus] = frozenset()
    detector_ids: frozenset[str] = frozenset()
    categories: frozenset[str] = frozenset()
    # Computed, no column: matches ValidationIssue.finding_category; "none" matches findings
    # without a category.
    finding_categories: frozenset[FindingCategoryKey] = frozenset()


@dataclass(frozen=True, slots=True)
class IssueCounts:
    total: int = 0
    by_evidence_class: dict[str, int] = field(default_factory=dict)  # effective evidence class
    by_severity: dict[str, int] = field(default_factory=dict)
    by_review_status: dict[str, int] = field(default_factory=dict)
    by_detector: dict[str, int] = field(default_factory=dict)
    by_finding_category: dict[str, int] = field(default_factory=dict)  # "none": no category


@dataclass(frozen=True, slots=True)
class DatasetCounts:
    """The size of one stored dataset revision, kept beside it so listings need not load it."""

    dataset_id: str
    revision: int
    table_count: int
    row_count: int

    @classmethod
    def of(cls, dataset: Dataset) -> DatasetCounts:
        tables = dataset.tables
        rows = sum(len(table.rows) for table in tables)
        return cls(dataset.dataset_id, dataset.revision, len(tables), rows)


class DocumentRepository(Protocol):
    def add(self, document: Document) -> None: ...
    def update(self, document: Document) -> None: ...
    def get(self, document_id: str) -> Document | None: ...
    def list(self, *, offset: int = 0, limit: int = 50) -> Page[Document]: ...


class DatasetRepository(Protocol):
    def add(self, dataset: Dataset) -> None: ...
    def get(self, dataset_id: str, revision: int | None = None) -> Dataset | None:
        """Latest revision when ``revision`` is None."""
        ...

    def list_for_document(self, document_id: str) -> list[Dataset]: ...
    def latest_for_document(self, document_id: str) -> Dataset | None:
        """The document's latest dataset at its latest (highest) revision; ``None`` when the
        document has none.

        Datasets are ordered by creation: a dataset is created when its first revision is
        stored (earliest ``created_at``, then storage order). The latest dataset is chosen
        first and then returned at its highest revision, so a correction of an older dataset
        (its revision N+1) does not make that dataset the latest one again.
        """
        ...

    def latest_counts_for_document(self, document_id: str) -> DatasetCounts | None:
        """The counts of :meth:`latest_for_document`'s dataset, read without loading it."""
        ...


class ValidationRunRepository(Protocol):
    def add(self, run: ValidationRun) -> None: ...
    def update(self, run: ValidationRun) -> None: ...
    def get(self, run_id: str) -> ValidationRun | None: ...
    def list_for_dataset(self, dataset_id: str) -> list[ValidationRun]: ...
    def latest_for_dataset(self, dataset_id: str) -> ValidationRun | None: ...
    def list_with_status(self, statuses: Collection[RunStatus]) -> list[ValidationRun]:
        """Runs of every dataset whose status is one of ``statuses``, newest started first
        (background runs a crash left unfinished)."""
        ...


class IssueRepository(Protocol):
    def add_many(self, issues: Sequence[ValidationIssue]) -> None: ...
    def get(self, issue_id: str) -> ValidationIssue | None: ...
    def update(self, issue: ValidationIssue, *, expected_version: int) -> None:
        """Replace the stored issue with ``issue``, its next version (for example from
        :meth:`ValidationIssue.with_review`), only if the stored issue still has
        ``expected_version`` (compare-and-set: ``UPDATE … WHERE issue_id = ? AND version = ?``).

        Raises :class:`ValueError` unless ``expected_version >= 1`` and ``issue.version ==
        expected_version + 1`` (nothing is read or written then),
        :class:`~app.core.errors.NotFoundError` when no issue has the id, and
        :class:`~app.core.errors.ConflictError` with ``details`` ``issue_id``,
        ``expected_version`` and ``current_version`` when the stored version differs (a
        decision made on a stale screen, or a concurrent review).
        """
        ...

    def reviewed_by_fingerprint(
        self, document_id: str, fingerprints: Collection[str]
    ) -> dict[str, ValidationIssue]:
        """For each fingerprint, the most recently reviewed issue with that fingerprint in any
        run on any dataset of the document; fingerprints without one are absent.

        Reviewed means ``review_status != pending_review``. Most recent means the latest
        ``reviewed_at`` (a reviewed issue without ``reviewed_at`` ranks last); for equal
        instants the issue stored last wins. Keys follow the order of ``fingerprints`` (each
        once). Services carry a decision into a later run only when the fingerprint *and* the
        ``evidence_digest`` match (ADR 0003).
        """
        ...

    def query(
        self, query: IssueQuery, *, offset: int = 0, limit: int = 100
    ) -> Page[ValidationIssue]: ...
    def counts(self, query: IssueQuery) -> IssueCounts: ...
    def change_mark(self, query: IssueQuery) -> tuple[int, int]:
        """(how many issues match, the sum of their versions). Every update raises an issue's
        version by one, so the mark changes whenever a matching issue is added or reviewed."""
        ...

    def iter_all(self, query: IssueQuery) -> Iterator[ValidationIssue]: ...


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def list_for_entity(self, entity_type: EntityType | str, entity_id: str) -> list[AuditEvent]:
        """The entity's events, oldest first (appending order for identical timestamps).
        ``entity_type`` is an :class:`EntityType` or its value; any other string raises
        :class:`~app.core.errors.InvalidInputError`."""
        ...


class ExplanationRepository(Protocol):
    """Language model explanations of a run's problems. An explanation's run must exist."""

    def add(self, explanation: Explanation) -> None: ...
    def update(self, explanation: Explanation) -> None:
        """Replace the stored explanation with the same id (for example when it finished);
        :class:`~app.core.errors.NotFoundError` when none has the id."""
        ...

    def get(self, explanation_id: str) -> Explanation | None: ...
    def latest_for_problem(self, run_id: str, problem_id: str) -> Explanation | None:
        """The problem's most recently created explanation in the run (for equal creation
        times, the one stored last)."""
        ...

    def list_for_run(self, run_id: str) -> list[Explanation]:
        """The run's explanations, newest created first (stored last first for equal times)."""
        ...


class ProjectRepository(Protocol):
    def add(self, project: Project) -> None: ...
    def update(self, project: Project) -> None: ...
    def get(self, project_id: str) -> Project | None: ...
    def list(self) -> list[Project]: ...


class UserRepository(Protocol):
    """User accounts, listed by name (code point order of the case-folded name, then id)."""

    def add(self, user: User) -> None: ...
    def update(self, user: User) -> None: ...
    def delete(self, user_id: str) -> None: ...
    def get(self, user_id: str) -> User | None: ...
    def by_token_digest(self, token_digest: str) -> User | None: ...
    def list(self) -> list[User]: ...


class UnitOfWork(Protocol):
    """Groups repository reads and writes into one transaction: ``with uow: ...`` commits on
    success and rolls back on exception.

    On SQLite and in memory, units of work run one at a time (SQLite: ``BEGIN IMMEDIATE``
    takes the write lock when the block starts, so a read-check-write cannot interleave with
    another writer; ADR 0005) and cannot be nested in one thread; both, and a lock not freed
    within the timeout, raise :class:`~app.repositories.errors.UnitOfWorkError`.
    PostgreSQL keeps its default isolation (READ COMMITTED); read-check-write of issues
    relies on ``IssueRepository.update(..., expected_version=...)`` there.
    """

    documents: DocumentRepository
    datasets: DatasetRepository
    runs: ValidationRunRepository
    issues: IssueRepository
    audit: AuditRepository
    explanations: ExplanationRepository
    projects: ProjectRepository
    users: UserRepository

    def __enter__(self) -> UnitOfWork: ...
    def __exit__(self, *exc_info: object) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractContextManager[UnitOfWork]: ...
