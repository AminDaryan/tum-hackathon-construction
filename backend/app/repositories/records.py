"""Payload encoding and column projections shared by both persistence adapters.

Every canonical model is stored whole (a JSON payload, or a compressed snapshot for datasets).
Both adapters encode and decode it with the functions below, so they accept, refuse and return
exactly the same values. A few of its fields are *projected* into indexed columns so they can be
filtered and ordered; both adapters compute those values here as well (the SQL adapter writes
them as columns, the in-memory adapter keeps them next to the model), so the two can never
disagree about, for example, an issue's sort keys or its effective evidence class.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from app.models.audit import AuditEvent
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.explanation import Explanation
from app.models.issue import SEVERITY_RANK, ValidationIssue
from app.models.run import ValidationRun
from app.repositories.base import DatasetCounts
from app.repositories.errors import IncompatibleRecordError, PayloadEncodingError

Columns = dict[str, Any]
ModelT = TypeVar("ModelT", bound=BaseModel)


def as_utc(moment: datetime) -> datetime:
    """``moment`` as an aware UTC datetime; a naive value is taken to be UTC already.

    Ordering columns are normalized because SQLite stores datetimes as text without an offset:
    only UTC values compare correctly there.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def dumps_strict(value: Any) -> str:
    """Compact JSON that rejects ``NaN`` and ``Infinity`` (as PostgreSQL does)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def encode_json(value: Any, *, what: str) -> str:
    """:func:`dumps_strict`, raising :class:`PayloadEncodingError` that names ``what``."""
    try:
        return dumps_strict(value)
    except (TypeError, ValueError) as exc:
        raise PayloadEncodingError(f"Cannot store {what} as strict JSON: {exc}") from exc


def describe(record: BaseModel) -> str:
    """How messages name a stored record, e.g. ``issue 'iss_1'``."""
    match record:
        case Document():
            return f"document {record.document_id!r}"
        case Dataset():
            return f"dataset {record.dataset_id!r} revision {record.revision}"
        case ValidationRun():
            return f"validation run {record.run_id!r}"
        case ValidationIssue():
            return f"issue {record.issue_id!r}"
        case AuditEvent():
            return f"audit event {record.event_id!r}"
        case Explanation():
            return f"explanation {record.explanation_id!r}"
    return type(record).__name__


def json_dump(model: BaseModel) -> dict[str, Any]:
    """``model.model_dump(mode="json")`` (decimals become exact strings), refused with
    :class:`PayloadEncodingError` when JSON cannot hold the model faithfully.

    Non-finite numbers are refused wherever they occur. JSON has no NaN or Infinity, and in
    ``Any``-typed fields (``AuditEvent.context``, a detector report's ``config``...) Pydantic's
    JSON mode would silently write ``null`` for them, so they are looked for in the Python-mode
    dump. Values Pydantic cannot serialize at all are refused as well.
    """
    try:
        location = _non_finite_location(model.model_dump())
        if location is None:
            return model.model_dump(mode="json")
    except PydanticSerializationError as exc:
        raise PayloadEncodingError(f"Cannot store {describe(model)} as JSON: {exc}") from exc
    field = ".".join(str(key) for key in reversed(location))
    raise PayloadEncodingError(
        f"Cannot store {describe(model)}: {field} is not a finite number "
        "(JSON has no NaN or Infinity).",
        details={"field": field},
    )


def _non_finite_location(value: Any) -> list[Any] | None:
    """Keys and indexes leading to the first NaN or infinite float or Decimal in ``value``,
    innermost first, or None when every number is finite."""
    if isinstance(value, float):
        return None if math.isfinite(value) else []
    if isinstance(value, Decimal):
        return None if value.is_finite() else []
    items: Iterable[tuple[Any, Any]]
    if isinstance(value, Mapping):
        items = value.items()
    elif isinstance(value, list | tuple | set | frozenset):
        items = enumerate(value)
    else:
        return None
    for key, item in items:
        location = _non_finite_location(item)
        if location is not None:
            location.append(key)
            return location
    return None


def to_payload(model: BaseModel) -> dict[str, Any]:
    """The JSON payload stored for ``model``: its :func:`json_dump`, checked to be strict JSON.

    Both adapters call this before storing a record (the in-memory adapter rebuilds the model
    from the payload, the snapshot codec encodes datasets from the same :func:`json_dump`), so
    a model one adapter refuses is refused by the other as well.
    """
    payload = json_dump(model)
    encode_json(payload, what=describe(model))
    return payload


def load_model(model_type: type[ModelT], payload: Any, *, what: str) -> ModelT:
    """Validate a stored payload back into ``model_type``; one that no longer fits the model
    raises :class:`IncompatibleRecordError` naming the record."""
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        raise IncompatibleRecordError(
            f"Stored {what} does not match the current {model_type.__name__} model "
            f"({exc.error_count()} validation error(s)); it needs a data migration."
        ) from exc


def document_columns(document: Document) -> Columns:
    return {
        "document_id": document.document_id,
        "uploaded_at": as_utc(document.uploaded_at),
        "processing_status": document.processing_status.value,
    }


def dataset_columns(dataset: Dataset) -> Columns:
    counts = DatasetCounts.of(dataset)
    return {
        "dataset_id": dataset.dataset_id,
        "revision": dataset.revision,
        "document_id": dataset.document_id,
        "profile_id": dataset.profile_id,
        "created_at": as_utc(dataset.created_at),
        "table_count": counts.table_count,
        "row_count": counts.row_count,
    }


def run_columns(run: ValidationRun) -> Columns:
    return {
        "run_id": run.run_id,
        "dataset_id": run.dataset_id,
        "dataset_revision": run.dataset_revision,
        "status": run.status.value,
        "started_at": as_utc(run.started_at),
        "finished_at": as_utc(run.finished_at) if run.finished_at else None,
    }


def issue_sort_position(issue: ValidationIssue) -> tuple[int | None, int | None, int | None]:
    """``(sheet_index, row_number, column_number)`` of the first affected cell's source.

    All three are ``None`` when the issue has no affected cell (or the cell carries no source
    location); an affected cell located at a sheet but not at a row (a table-level location)
    has a sheet but no row number.
    """
    if not issue.affected_cells or issue.affected_cells[0].source is None:
        return (None, None, None)
    source = issue.affected_cells[0].source
    return (source.sheet_index, source.row_number, source.column_number)


def issue_columns(issue: ValidationIssue) -> Columns:
    """Every indexed issue column. Recomputed on each write, so ``review_status``,
    ``effective_evidence_class``, ``reviewed_at`` and ``version`` (the compare-and-set key of
    ``update``) always follow the stored payload."""
    sheet, row, column = issue_sort_position(issue)
    return {
        "issue_id": issue.issue_id,
        "validation_run_id": issue.validation_run_id,
        "document_id": issue.document_id,
        "dataset_id": issue.dataset_id,
        "dataset_revision": issue.dataset_revision,
        "table_id": issue.table_id,
        "row_id": issue.row_id,
        "detector_id": issue.detector_id,
        "rule_id": issue.rule_id,
        "issue_category": issue.issue_category,
        "severity": issue.severity.value,
        "severity_rank": SEVERITY_RANK[issue.severity],
        "evidence_class": issue.evidence_class.value,
        "effective_evidence_class": issue.effective_evidence_class.value,
        "review_status": issue.review_status.value,
        "reviewed_at": as_utc(issue.reviewed_at) if issue.reviewed_at else None,
        "version": issue.version,
        "sort_sheet": sheet,
        "sort_row": row,
        "sort_column": column,
        "fingerprint": issue.fingerprint,
    }


def explanation_columns(explanation: Explanation) -> Columns:
    return {
        "explanation_id": explanation.explanation_id,
        "run_id": explanation.run_id,
        "problem_id": explanation.problem_id,
        "status": explanation.status.value,
        "created_at": as_utc(explanation.created_at),
        "finished_at": as_utc(explanation.finished_at) if explanation.finished_at else None,
    }


def audit_columns(event: AuditEvent) -> Columns:
    return {
        "event_id": event.event_id,
        "occurred_at": as_utc(event.occurred_at),
        "entity_type": event.entity_type.value,
        "entity_id": event.entity_id,
        "action": event.action.value,
    }
