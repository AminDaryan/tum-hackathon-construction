"""SQL unit of work: one connection and one transaction per ``with`` block. On SQLite the
transaction holds the write lock from its start (see
:class:`~app.repositories.sql.database.Database`).

Create one unit of work per request (``with factory() as uow: ...``) and never share it
between threads; the :class:`~app.repositories.sql.database.Database` it is created from is
shared and thread-safe (pooled connections, a locked dataset cache).
"""

from __future__ import annotations

from contextlib import ExitStack

from sqlalchemy import Connection, RootTransaction

from app.repositories.base import (
    AuditRepository,
    DatasetRepository,
    DocumentRepository,
    ExplanationRepository,
    IssueRepository,
    ProjectRepository,
    UserRepository,
    ValidationRunRepository,
)
from app.repositories.errors import UnitOfWorkError
from app.repositories.sql.audit import SqlAuditRepository
from app.repositories.sql.database import Database
from app.repositories.sql.datasets import SqlDatasetRepository
from app.repositories.sql.documents import SqlDocumentRepository
from app.repositories.sql.explanations import SqlExplanationRepository
from app.repositories.sql.issues import SqlIssueRepository
from app.repositories.sql.projects import SqlProjectRepository
from app.repositories.sql.runs import SqlValidationRunRepository
from app.repositories.sql.users import SqlUserRepository
from app.repositories.transactions import UnitOfWorkBase


class SqlUnitOfWork(UnitOfWorkBase[Connection]):
    """Commits on a clean exit, rolls back when the block raises; the repositories are bound to
    this unit of work's connection and refuse to work outside the ``with`` block."""

    def __init__(self, database: Database) -> None:
        super().__init__("SQL unit of work")
        self._database = database
        self._transaction: RootTransaction | None = None
        self.documents: DocumentRepository = SqlDocumentRepository(self._scope)
        self.datasets: DatasetRepository = SqlDatasetRepository(self._scope, database.dataset_cache)
        self.runs: ValidationRunRepository = SqlValidationRunRepository(self._scope)
        self.issues: IssueRepository = SqlIssueRepository(self._scope)
        self.audit: AuditRepository = SqlAuditRepository(self._scope)
        self.explanations: ExplanationRepository = SqlExplanationRepository(self._scope)
        self.projects: ProjectRepository = SqlProjectRepository(self._scope)
        self.users: UserRepository = SqlUserRepository(self._scope)

    def _begin(self, resources: ExitStack) -> Connection:
        connection = resources.enter_context(self._database.connect())
        self._transaction = self._database.begin(connection)
        return connection

    def _finish(self, resource: Connection, *, failed: bool) -> None:
        transaction, self._transaction = self._transaction, None
        if transaction is None:  # pragma: no cover - _begin always starts one
            raise UnitOfWorkError("The SQL unit of work has no transaction to finish.")
        if failed:
            transaction.rollback()
        else:
            transaction.commit()


class SqlUnitOfWorkFactory:
    """:class:`~app.repositories.base.UnitOfWorkFactory` for the SQL adapter."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def __call__(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self.database)
