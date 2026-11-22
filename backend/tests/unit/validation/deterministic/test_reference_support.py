"""The windows and repeated matching that the reference, unit and BoQ text checks share."""

from __future__ import annotations

import itertools

from app.core import patterns
from app.validation.deterministic._reference_support import find_captures, find_spans, windows


def test_find_spans_reports_the_first_group_when_it_took_part() -> None:
    text = "Verbau ist einzukalkulieren; Wasserhaltung wird gesondert vergütet."
    assert find_spans(r"verbau|wasserhaltung", text) == [(0, 6, None), (29, 42, None)]
    with_group = find_spans(r"(verbau)|wasserhaltung", text)
    assert with_group == [(0, 6, (0, 6)), (29, 42, None)]
    assert find_captures(r"(verbau)|wasserhaltung", text) == [("Verbau", "Verbau")]


def test_find_spans_masks_each_match_before_the_next_search() -> None:
    assert find_spans(r"^rohr", "Rohr und Rohr") == [(0, 4, None)]  # ^ only at the real start
    assert find_spans(r"x*", "abc") == []  # an empty match ends the search
    assert len(find_spans(r"bogen", " ".join(["Bogen"] * 40), limit=5)) == 5
    # A match that would reuse masked text of an earlier one is skipped.
    assert find_spans(r"ab|\W+c", "ab c") == [(0, 2, None)]


def test_windows_overlap_by_the_given_number_of_characters() -> None:
    text = " ".join(f"wort{i:05d}" for i in range(1000))  # about 10,000 characters
    half = patterns.MAX_MATCH_CHARS // 2
    pieces = list(windows(text, half))
    covered = 0
    for offset, window in pieces:
        assert len(window) <= patterns.MAX_MATCH_CHARS
        assert text[offset : offset + len(window)] == window
        assert offset <= covered and (offset == 0 or text[offset - 1] == " ")
        covered = max(covered, offset + len(window))
    assert covered == len(text)
    for (first, window), (second, _) in itertools.pairwise(pieces):
        assert half - 10 <= first + len(window) - second <= half
    assert list(windows("kurz", half)) == [(0, "kurz")]
