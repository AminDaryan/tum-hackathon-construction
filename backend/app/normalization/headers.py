"""Header row detection over the first ``header_scan_rows`` non-empty rows of a sheet.

Methods, tried in order (``HeaderDetection.method``):

* ``profile_synonyms``: the row whose text cells match the most distinct profile fields (at
  least two) wins; on a tie the earlier row wins and ``header_ambiguous`` is reported unless
  the tied rows say the same (a header repeated on every page). A text-only row directly
  below that adds at least one field (``"Preis"`` over ``"EP" | "GP"``) makes a two-row header:
  each column is matched by its lower text first, then by the composed text, and horizontally
  merged upper cells apply their text to every column they span.
* ``structural``: the first row with two or more non-empty cells, all text, followed within
  ``normalization.structural_lookahead_rows`` (default three) rows by a row with a number,
  where at least two of its text cells sit in columns that hold data within
  ``normalization.data_lookahead_rows`` (default 20) rows below.
* ``first_row``: the first non-empty row when all its non-empty cells are text.
* ``none``: no header; columns are named by their letter and every row is data.

A reviewer decision (``TableDecisions.header_row_numbers``) replaces detection (``user``).
Rows above the header are a title block and are not part of the table.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.ingestion.base import RawSheet
from app.models.dataset import HeaderMethod
from app.models.profile import NormalizationThresholds
from app.normalization.mapping import FieldMatch, HeaderMatcher


@dataclass(slots=True)
class HeaderResult:
    rows: list[int]  # header rows, top to bottom
    method: HeaderMethod
    texts: dict[int, str]  # source column -> header text as written (composed for two rows)
    candidates: dict[int, tuple[FieldMatch, ...]]  # source column -> field matches
    note: str | None = None
    warnings: list[str] = field(default_factory=list)  # codes: header_ambiguous

    @property
    def data_start(self) -> int | None:
        return self.rows[-1] + 1 if self.rows else None


@dataclass(frozen=True, slots=True)
class SheetView:
    """What header detection needs to know about a sheet's cells."""

    sheet: RawSheet
    text_of: Callable[[int, int], str | None]  # plain text of a cell, None if not text
    non_empty: Callable[[int, int], bool]
    numeric: Callable[[int, int], bool]
    rows: list[int]  # non-empty source rows in order
    columns: list[int]  # source columns with any non-empty cell


def detect_header(
    view: SheetView, matcher: HeaderMatcher, scan_rows: int, user_rows: list[int] | None
) -> HeaderResult:
    if user_rows is not None:
        return _user_header(view, matcher, user_rows)
    scanned = view.rows[:scan_rows]
    if matcher.has_fields:
        found = _by_synonyms(view, matcher, scanned)
        if found is not None:
            return found
    for method, finder in (
        (HeaderMethod.STRUCTURAL, _structural),
        (HeaderMethod.FIRST_ROW, _first_row),
    ):
        row = finder(view, scanned, matcher.thresholds)
        if row is not None:
            texts = _row_texts(view, row)
            return HeaderResult(
                [row],
                method,
                texts,
                {c: matcher.matches(t) for c, t in texts.items()},
                note=_title_note(view, row),
            )
    return HeaderResult([], HeaderMethod.NONE, {}, {}, note="No header row was recognized.")


def _user_header(view: SheetView, matcher: HeaderMatcher, rows: list[int]) -> HeaderResult:
    rows = sorted(r for r in set(rows) if 1 <= r <= max(view.sheet.max_row, 1))
    texts: dict[int, str] = {}
    for column in view.columns:
        parts = [t for r in rows if (t := _spread_text(view, r, column))]
        if parts:
            texts[column] = " ".join(parts)
    candidates = {}
    for column, text in texts.items():
        lower = _spread_text(view, rows[-1], column) if rows else None
        candidates[column] = matcher.matches(lower) or matcher.matches(text)
    note = "Header rows chosen by a reviewer." if rows else "A reviewer chose no header row."
    return HeaderResult(rows, HeaderMethod.USER, texts, candidates, note=note)


def _by_synonyms(
    view: SheetView, matcher: HeaderMatcher, scanned: list[int]
) -> HeaderResult | None:
    best_row: int | None = None
    best_fields: set[str] = set()
    tied: list[int] = []
    for row in scanned:
        texts = _row_texts(view, row)
        fields = matcher.fields_matched(texts.values())
        if len(fields) > len(best_fields):
            best_row, best_fields, tied = row, fields, []
        elif best_row is not None and fields and len(fields) == len(best_fields):
            tied.append(row)
    if best_row is None or len(best_fields) < 2:
        return None
    upper = _row_texts(view, best_row)
    warnings = []
    if any(_keys(matcher, _row_texts(view, t)) != _keys(matcher, upper) for t in tied):
        warnings.append("header_ambiguous")
    single = {c: matcher.matches(t) for c, t in upper.items()}
    note = _title_note(view, best_row)
    lower_row = best_row + 1
    if lower_row in view.rows and _all_text(view, lower_row):
        composed, candidates = _two_rows(view, matcher, best_row, lower_row)
        if len(_distinct(candidates)) > len(_distinct(single)):
            two_note = f"Two-row header (rows {best_row} and {lower_row})."
            return HeaderResult(
                [best_row, lower_row],
                HeaderMethod.PROFILE_SYNONYMS,
                composed,
                candidates,
                note=" ".join(n for n in (note, two_note) if n),
                warnings=warnings,
            )
    return HeaderResult(
        [best_row], HeaderMethod.PROFILE_SYNONYMS, upper, single, note=note, warnings=warnings
    )


def _two_rows(
    view: SheetView, matcher: HeaderMatcher, upper_row: int, lower_row: int
) -> tuple[dict[int, str], dict[int, tuple[FieldMatch, ...]]]:
    texts: dict[int, str] = {}
    candidates: dict[int, tuple[FieldMatch, ...]] = {}
    for column in view.columns:
        upper = _spread_text(view, upper_row, column)
        lower = view.text_of(lower_row, column)
        composed = " ".join(t for t in (upper, lower) if t)
        if not composed:
            continue
        texts[column] = composed
        matches = matcher.matches(lower) if lower else ()
        candidates[column] = matches or matcher.matches(composed)
    return texts, candidates


def _distinct(candidates: dict[int, tuple[FieldMatch, ...]]) -> set[str]:
    return {m.field_id for matches in candidates.values() for m in matches}


def _keys(matcher: HeaderMatcher, texts: dict[int, str]) -> dict[int, str]:
    return {c: matcher.key(t) for c, t in texts.items()}


def _structural(
    view: SheetView, scanned: list[int], thresholds: NormalizationThresholds
) -> int | None:
    for index, row in enumerate(scanned):
        texts = _row_texts(view, row)
        if len(texts) < 2 or not _all_text(view, row):
            continue
        following = scanned[index + 1 : index + 1 + thresholds.structural_lookahead_rows]
        if not any(view.numeric(r, c) for r in following for c in view.columns):
            continue
        below = [r for r in view.rows if r > row][: thresholds.data_lookahead_rows]
        with_data = [c for c in texts if any(view.non_empty(r, c) for r in below)]
        if len(with_data) >= 2:
            return row
    return None


def _first_row(
    view: SheetView, scanned: list[int], _thresholds: NormalizationThresholds
) -> int | None:
    if scanned and _all_text(view, scanned[0]):
        return scanned[0]
    return None


def _all_text(view: SheetView, row: int) -> bool:
    cells = [c for c in view.columns if view.non_empty(row, c)]
    return bool(cells) and all(view.text_of(row, c) is not None for c in cells)


def _row_texts(view: SheetView, row: int) -> dict[int, str]:
    return {c: t for c in view.columns if (t := view.text_of(row, c)) is not None}


def _spread_text(view: SheetView, row: int, column: int) -> str | None:
    """Text of a header cell, or of the horizontally merged range that covers it."""
    text = view.text_of(row, column)
    if text is not None:
        return text
    for merged in view.sheet.merged_ranges:
        if (
            merged.min_row <= row <= merged.max_row
            and merged.min_column <= column <= merged.max_column
        ):
            return view.text_of(merged.min_row, merged.min_column)
    return None


def _title_note(view: SheetView, header_row: int) -> str | None:
    above = [r for r in view.rows if r < header_row]
    if not above:
        return None
    span = f"Row {above[0]}" if len(above) == 1 else f"Rows {above[0]}-{above[-1]}"
    verb = "was" if len(above) == 1 else "were"
    return f"{span} above the header {verb} treated as a title block."
