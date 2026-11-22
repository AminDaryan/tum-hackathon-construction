"""Extraction warning codes, whether each needs review, and the dataset quality rule.

A warning that can affect values or structure needs review; the dataset's quality is then
``needs_review``. Purely informational notes do not change the quality.

======================================  =============  ==========================================
code                                    needs review   meaning
======================================  =============  ==========================================
header_uncertain                        yes [1]_       header found by layout, first row or none
header_ambiguous                        yes            several rows look like the header
column_mapping_ambiguous                yes            two columns tie for one field: unmapped
mapping_rejected_type_mismatch          yes            a number field's column holds no numbers
required_field_unmapped                 yes            a required profile field has no column
number_format_ambiguous                 yes            values left unparsed (separator, parens…)
decimal_separator_conflict              yes            a column uses both separators
formula_without_cached_result           yes            formulas whose result the file lacks
unclassified_amount_row                 yes            a row with an amount but no row kind
encoding_guessed, ragged_rows,          yes            delimited-text adapter findings
single_column_file
hidden_sheet_skipped                    no             a hidden sheet was not normalized
empty_sheet_skipped                     no             a sheet without content
chartsheet_skipped                      no             chart sheets hold no cells
macro_project_ignored                   no             macros are never run
external_links_ignored                  no             external links are never followed
decisions_applied                       no             reviewer decisions applied / ignored
structure_declared                      no             structure stated by the file (GAEB) applied
hidden_rows_present                     no             hidden rows are kept and checked
section_amount_on_heading               no             a section heading states an amount
======================================  =============  ==========================================

.. [1] Informational for profiles without fields (nothing to map, so nothing to review).

Adapter warnings are re-flagged from this table; codes it does not list keep the adapter's own
flag (``True`` unless the adapter decided otherwise).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.models.dataset import ExtractionQuality, ExtractionWarning
from app.models.source import SourceLocation

NEEDS_REVIEW: frozenset[str] = frozenset(
    {
        "header_uncertain",
        "header_ambiguous",
        "column_mapping_ambiguous",
        "mapping_rejected_type_mismatch",
        "required_field_unmapped",
        "number_format_ambiguous",
        "decimal_separator_conflict",
        "formula_without_cached_result",
        "unclassified_amount_row",
        "encoding_guessed",
        "ragged_rows",
        "single_column_file",
    }
)
INFORMATIONAL: frozenset[str] = frozenset(
    {
        "hidden_sheet_skipped",
        "empty_sheet_skipped",
        "chartsheet_skipped",
        "macro_project_ignored",
        "external_links_ignored",
        "decisions_applied",
        "structure_declared",
        "hidden_rows_present",
        "section_amount_on_heading",
    }
)
MAX_LISTED_ROWS = 10


def warning(
    code: str,
    message: str,
    *,
    table_id: str | None = None,
    source: SourceLocation | None = None,
    count: int | None = None,
    needs_review: bool | None = None,
) -> ExtractionWarning:
    """A normalization warning; ``needs_review`` defaults to the table above."""
    flag = needs_review if needs_review is not None else code not in INFORMATIONAL
    return ExtractionWarning(
        code=code,
        message=message,
        table_id=table_id,
        source=source,
        count=count,
        needs_review=flag,
    )


def reflag(item: ExtractionWarning, table_id: str | None = None) -> ExtractionWarning:
    """An adapter warning with the flag from the table above (and the table it belongs to)."""
    if item.code in INFORMATIONAL:
        flag = False
    elif item.code in NEEDS_REVIEW:
        flag = True
    else:
        flag = item.needs_review
    changes: dict[str, object] = {}
    if flag != item.needs_review:
        changes["needs_review"] = flag
    if table_id is not None and item.table_id is None:
        changes["table_id"] = table_id
    return item.evolve(**changes) if changes else item


def quality(warnings: Iterable[ExtractionWarning]) -> ExtractionQuality:
    if any(w.needs_review for w in warnings):
        return ExtractionQuality.NEEDS_REVIEW
    return ExtractionQuality.OK


def list_rows(rows: list[int]) -> str:
    """``"rows 4, 9 and 12"``; long lists are cut after :data:`MAX_LISTED_ROWS`."""
    shown = [str(r) for r in rows[:MAX_LISTED_ROWS]]
    if len(rows) > MAX_LISTED_ROWS:
        return f"rows {', '.join(shown)} and {len(rows) - MAX_LISTED_ROWS} more"
    if len(shown) == 1:
        return f"row {shown[0]}"
    return f"rows {', '.join(shown[:-1])} and {shown[-1]}"
