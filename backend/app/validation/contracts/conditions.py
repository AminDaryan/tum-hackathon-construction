"""Which detector reports which cell condition, and the shared coverage vocabulary.

One defective cell must yield one finding, not one per detector that reads it. Every cell is
classified by :func:`cell_condition`; each condition that is a finding in its own right has
exactly one owning detector (:data:`CONDITION_OWNERS`). Every other detector that needs the
cell as an input abstains on it and counts the row under the standard coverage key from
:func:`skip_key`, so the run report still shows what could not be checked. The full table is
in ``docs/architecture/validation-engine.md``.

Arithmetic detectors use ``usable`` inputs; ``inferred`` inputs are usable too (the issue
factory adds a caveat note to confirmed findings built on them).
"""

from __future__ import annotations

from enum import StrEnum

from app.models.dataset import Cell
from app.models.values import DataType, ParseStatus


class CellCondition(StrEnum):
    EMPTY = "empty"  # no value at all (missing, blank text)
    USABLE = "usable"  # typed value read exactly
    INFERRED = "inferred"  # typed value that needed column/document evidence (usable, caveat)
    TEXT = "text"  # plain text where text is expected
    MARKER = "marker"  # conventional token ("Incl.", "entfällt", "psch"); see Cell.marker
    AMBIGUOUS = "ambiguous"  # several readings, no value chosen
    FAILED = "failed"  # text where a number/date was expected, or a number out of range
    UNAVAILABLE = "unavailable"  # formula whose cached result is not stored in the file
    ERROR = "error"  # spreadsheet error literal (#REF!, #DIV/0!, ...)


def cell_condition(cell: Cell | None) -> CellCondition:
    """Classify a cell (``None``, a cell outside the table, counts as empty)."""
    if cell is None or cell.data_type is DataType.EMPTY:
        return CellCondition.EMPTY
    status = cell.parse_status
    if cell.data_type is DataType.ERROR:
        return CellCondition.ERROR
    if status is ParseStatus.UNAVAILABLE:
        return CellCondition.UNAVAILABLE
    if status is ParseStatus.AMBIGUOUS:
        return CellCondition.AMBIGUOUS
    if status is ParseStatus.FAILED:
        return CellCondition.FAILED
    if status is ParseStatus.MARKER:
        return CellCondition.MARKER
    if status is ParseStatus.INFERRED:
        return CellCondition.INFERRED
    if cell.data_type is DataType.TEXT:
        return CellCondition.TEXT
    return CellCondition.USABLE


USABLE_CONDITIONS: frozenset[CellCondition] = frozenset(
    {CellCondition.USABLE, CellCondition.INFERRED}
)

# The detector that reports a condition as a finding. Conditions without an owner here are
# not findings by themselves: EMPTY is reported by deterministic.required_values only where a
# value is required, MARKER is a legitimate value, USABLE / INFERRED / TEXT are values.
CONDITION_OWNERS: dict[CellCondition, str] = {
    CellCondition.ERROR: "deterministic.formula_errors",
    CellCondition.UNAVAILABLE: "deterministic.formula_errors",
    CellCondition.AMBIGUOUS: "deterministic.data_type_conformance",
    CellCondition.FAILED: "deterministic.data_type_conformance",
}


class Coverage:
    """Standard coverage keys (``DetectorResult.coverage``). Detectors may add their own
    specific keys, but use these for the shared meanings so reports can be compared."""

    ROWS_CHECKED = "rows_checked"  # rows on which the rule was evaluated
    ROWS_CONSISTENT = "rows_consistent"
    ROWS_INCONSISTENT = "rows_inconsistent"
    ROWS_SKIPPED_MISSING_INPUTS = "rows_skipped_missing_inputs"  # an input was EMPTY
    ROWS_SKIPPED_MARKER = "rows_skipped_marker"  # an input was a value marker
    # an input was ERROR / UNAVAILABLE / AMBIGUOUS / FAILED (reported by its owner)
    ROWS_SKIPPED_UNUSABLE_INPUTS = "rows_skipped_unusable_inputs"
    ROWS_SKIPPED_NOT_APPLICABLE = "rows_skipped_not_applicable"  # documented abstention
    ROWS_FAILED = "rows_failed"  # a row check raised and was skipped (see _support.row_guard)
    TOTALS_CHECKED = "totals_checked"
    TOTALS_CONSISTENT = "totals_consistent"
    TOTALS_INCONSISTENT = "totals_inconsistent"
    TOTALS_UNDECIDED = "totals_undecided"  # result depends on context the document lacks
    TOTALS_SKIPPED_NO_SCOPE = "totals_skipped_no_scope"
    TOTALS_SKIPPED_INCOMPLETE_SCOPE = "totals_skipped_incomplete_scope"
    TOTALS_SKIPPED_MISSING_AMOUNT = "totals_skipped_missing_amount"
    CELLS_CHECKED = "cells_checked"


def skip_key(condition: CellCondition) -> str | None:
    """Coverage key for a row skipped because an input has ``condition`` (``None`` when the
    condition is usable)."""
    if condition in USABLE_CONDITIONS or condition is CellCondition.TEXT:
        return None
    if condition is CellCondition.EMPTY:
        return Coverage.ROWS_SKIPPED_MISSING_INPUTS
    if condition is CellCondition.MARKER:
        return Coverage.ROWS_SKIPPED_MARKER
    return Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS
