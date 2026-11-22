"""Small helpers shared by all deterministic detectors (private module: not discovered).

Keep only genuinely shared, domain-neutral helpers here so detectors stay small and no logic is
duplicated across detector modules. Code canonicalization lives in :mod:`app.core.codes`
(normalization needs the same rules) and is re-exported here for convenience; the explicit
currency of a row comes from ``ValidationContext.currency_evidence``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Annotated

from pydantic import StringConstraints, ValidationError

from app.core.codes import MAX_CODE_SEGMENT_CHARS, code_segments, is_strict_prefix, normalize_code
from app.models.dataset import CellRef, Row, Table
from app.models.profile import FIELD_ID_PATTERN
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import format_decimal
from app.validation.contracts.detector import DetectorResult
from app.validation.contracts.issue_factory import IssuePolicyError

__all__ = [
    "MAX_CODE_SEGMENT_CHARS",
    "FieldId",
    "code_segments",
    "field_label",
    "fmt",
    "is_strict_prefix",
    "normalize_code",
    "refs",
    "row_guard",
    "row_label",
    "written_places",
]

_FAILED_ROWS_LISTED = 20

# A field id in a detector configuration, e.g. ``list[FieldId]`` or ``dict[FieldId, ...]``.
FieldId = Annotated[str, StringConstraints(pattern=FIELD_ID_PATTERN)]


def fmt(value: Decimal | None) -> str | None:
    """Plain decimal string for observed/expected values and evidence (``None`` stays ``None``)."""
    return None if value is None else format_decimal(value)


def row_label(table: Table, row: Row) -> str:
    """Human-readable row location for explanations, e.g. ``'LV' row 14``."""
    return f"'{table.name}' row {row.source_row_number}"


def field_label(context: ValidationContext, field_id: str) -> str:
    """Profile label of a field (``Unit price``), falling back to the field id."""
    field = context.profile_field(field_id)
    return field.label if field else field_id


def refs(
    context: ValidationContext, table: Table, row: Row, field_ids: Iterable[str]
) -> list[CellRef]:
    """Cell references for the mapped fields among ``field_ids`` (unmapped ones are skipped)."""
    return [
        context.cell_ref(table, row, field_id)
        for field_id in field_ids
        if table.column_for_field(field_id) is not None
    ]


@contextmanager
def row_guard(result: DetectorResult, table: Table, row: Row) -> Iterator[None]:
    """Run one row's check so that a value the check cannot handle skips only that row.

    ``ArithmeticError`` and ``ValueError`` raised by document-derived values are caught,
    counted as ``rows_failed`` in the coverage and listed in a note (the first few rows), so
    the skip is visible in the run report. Programming errors are not hidden: issue-policy
    violations and model validation errors propagate and fail the detector, and run limits
    (``DetectorStopped``) propagate to the pipeline.
    """
    try:
        yield
    except (IssuePolicyError, ValidationError):
        raise
    except (ArithmeticError, ValueError) as exc:
        failed = result.coverage.get("rows_failed", 0)
        result.count("rows_failed")
        if failed < _FAILED_ROWS_LISTED:
            result.notes.append(
                f"{row_label(table, row)} could not be checked ({type(exc).__name__}); it was "
                "skipped."
            )


def written_places(value: Decimal) -> int:
    """Decimal places as written (``9.70`` -> 2, ``40`` -> 0)."""
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0
