"""Errors raised by the persistence adapters.

Both adapters raise the same exception types for the same situations, so services (and their
tests on the in-memory adapter) see identical behaviour whichever adapter is configured. Two
outcomes the API client can act on use the core errors: a missing record on ``update()``
raises :class:`app.core.errors.NotFoundError`, and an issue update naming a stale version
raises :class:`app.core.errors.ConflictError` (ADR 0005). Everything else that can go wrong in
storage derives from :class:`PersistenceError`. These are server-side faults (a programming
error, a corrupt or foreign database, a database busy for too long), not problems the API
client can fix, so the API layer should report them without leaking their details.
"""

from __future__ import annotations

from app.core.errors import WorkbenchError


class PersistenceError(WorkbenchError):
    """A storage operation failed."""

    code = "persistence_error"


class IntegrityViolationError(PersistenceError):
    """A write would break an integrity rule: a duplicate key or a reference to a record that
    does not exist (for example an issue whose validation run was never stored)."""

    code = "integrity_violation"


class PayloadEncodingError(PersistenceError):
    """A model cannot be stored faithfully as strict JSON: it holds a NaN or infinite number
    (JSON has none, and Pydantic would silently write ``null`` for one in an ``Any``-typed
    field) or a value Pydantic cannot serialize. Both adapters refuse such a model up front."""

    code = "payload_encoding_failed"


class UnitOfWorkError(PersistenceError):
    """A unit of work was misused or could not start: a repository was called outside the
    ``with`` block, a unit of work was entered twice, units of work were nested in one thread
    (in memory or on SQLite), or the database stayed busy beyond the lock or busy timeout."""

    code = "unit_of_work_misuse"


class SchemaVersionError(PersistenceError):
    """The database was created by an incompatible schema version (or its version is unknown).
    The application refuses to start rather than read or corrupt it."""

    code = "schema_version_mismatch"


class IncompatibleRecordError(PersistenceError):
    """A stored payload or snapshot no longer validates against the current model, e.g. after
    a model change without a data migration."""

    code = "incompatible_record"


class SnapshotCodecError(PersistenceError):
    """A dataset snapshot could not be decoded."""

    code = "snapshot_codec_error"


class UnknownSnapshotCodecError(SnapshotCodecError):
    """The snapshot was written with a codec this build does not know."""

    code = "unknown_snapshot_codec"


class CorruptSnapshotError(SnapshotCodecError):
    """The snapshot bytes are damaged (checksum, compression or JSON errors) or do not hold the
    dataset revision they are stored under."""

    code = "corrupt_snapshot"
