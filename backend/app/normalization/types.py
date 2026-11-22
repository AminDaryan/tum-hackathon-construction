"""Column type profiles: the measured type distribution of a column's data cells."""

from __future__ import annotations

from collections.abc import Iterable

from app.models.dataset import Cell, TypeProfile
from app.models.values import DataType, ParseStatus


def type_profile(cells: Iterable[Cell], dominance_threshold: float) -> TypeProfile:
    """Counts by data type over non-empty cells; value markers are counted apart
    (``marker_count``) so "Incl." does not make a numeric column look like text. The dominant
    type is the most frequent one when its share reaches ``dominance_threshold``, else
    ``mixed``; an empty column is ``empty`` with share 0."""
    counts: dict[DataType, int] = {}
    markers = 0
    for cell in cells:
        if cell.parse_status is ParseStatus.MARKER:
            markers += 1
        elif not cell.is_empty:
            counts[cell.data_type] = counts.get(cell.data_type, 0) + 1
    non_empty = sum(counts.values())
    if not non_empty:
        return TypeProfile(
            counts={},
            non_empty=0,
            dominant_type=DataType.EMPTY,
            dominant_share=0.0,
            marker_count=markers,
        )
    top = max(counts, key=lambda t: (counts[t], t.value))
    share = counts[top] / non_empty
    dominant = top if share >= dominance_threshold else DataType.MIXED
    return TypeProfile(
        counts=counts,
        non_empty=non_empty,
        dominant_type=dominant,
        dominant_share=round(share, 6),
        marker_count=markers,
    )
