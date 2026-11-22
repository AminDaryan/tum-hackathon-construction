"""Persistence: ports in :mod:`app.repositories.base`, adapters in :mod:`app.repositories.memory`
(tests, reference behaviour) and :mod:`app.repositories.sql` (SQLite / PostgreSQL)."""

from app.repositories.base import (
    AuditRepository,
    DatasetRepository,
    DocumentRepository,
    IssueCounts,
    IssueQuery,
    IssueRepository,
    Page,
    UnitOfWork,
    UnitOfWorkFactory,
    ValidationRunRepository,
)
from app.repositories.errors import (
    CorruptSnapshotError,
    IncompatibleRecordError,
    IntegrityViolationError,
    PayloadEncodingError,
    PersistenceError,
    SchemaVersionError,
    SnapshotCodecError,
    UnitOfWorkError,
    UnknownSnapshotCodecError,
)
from app.repositories.memory import (
    InMemoryDatabase,
    InMemoryUnitOfWork,
    InMemoryUnitOfWorkFactory,
)

__all__ = [
    "AuditRepository",
    "CorruptSnapshotError",
    "DatasetRepository",
    "DocumentRepository",
    "InMemoryDatabase",
    "InMemoryUnitOfWork",
    "InMemoryUnitOfWorkFactory",
    "IncompatibleRecordError",
    "IntegrityViolationError",
    "IssueCounts",
    "IssueQuery",
    "IssueRepository",
    "Page",
    "PayloadEncodingError",
    "PersistenceError",
    "SchemaVersionError",
    "SnapshotCodecError",
    "UnitOfWork",
    "UnitOfWorkError",
    "UnitOfWorkFactory",
    "UnknownSnapshotCodecError",
    "ValidationRunRepository",
]
