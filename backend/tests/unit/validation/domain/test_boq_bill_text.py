"""The shared reader of the BoQ wording checks: rows, continuations, tokens, windows."""

from __future__ import annotations

import itertools

from app.core import patterns
from app.validation.deterministic._reference_support import windows
from app.validation.domain.boq._bill_text import (
    WINDOW_OVERLAP,
    BillFields,
    Found,
    read_bill,
    search,
    search_all,
    search_start,
)
from tests.support.builders import make_context
from tests.unit.validation.domain.boq_text_fixtures import (
    SHORT_ONLY,
    bill,
    continuation,
    item,
    long_text,
    note,
)

FIELDS = BillFields("description", "long_description", "item_code")


def read(profile, lines, **kwargs):
    dataset = bill(profile, lines, **kwargs)
    context = make_context(dataset, profile)
    return read_bill(context, dataset.tables[0], FIELDS)


def test_items_notes_and_continuation_lines(boq_profile) -> None:
    lines = [
        item("01.01.0010", "Rohrgraben ausheben", "Boden der Klasse 3-5."),
        continuation("Fortsetzung: einschließlich Verfüllung."),
        note("Hinweis", "Die Druckprüfung ist nach DIN EN 805 auszuführen."),
        item("01.01.0020", "Bauzaun aufstellen"),
    ]
    read_back = read(boq_profile, lines)
    assert [e.label for e in read_back.entries] == ["01.01.0010", "row 4", "01.01.0020"]
    first = read_back.entries[0]
    assert first.is_item and "Verfüllung" in first.long and "Klasse 3-5" in first.long
    assert first.text.startswith("Rohrgraben ausheben\n")
    assert first.long_offset == len("Rohrgraben ausheben") + 1
    assert first.top_section == "1"
    assert first.section == ("code", "1", "1")
    assert not read_back.entries[1].is_item
    assert [e.label for e in read_back.items] == ["01.01.0010", "01.01.0020"]
    assert read_back.has_long_texts


def test_a_bill_without_long_texts(boq_profile) -> None:
    lines = [item("1.1", "Kernbohrung DN 150 herstellen"), item("1.2", "Bauzaun")]
    assert not read(boq_profile, lines).has_long_texts
    assert not read(boq_profile, lines, columns=SHORT_ONLY).has_long_texts
    no_code = read(boq_profile, [item("7", "Bauzaun")])
    assert no_code.entries[0].top_section is None and no_code.entries[0].section is None


def test_quotes_are_cut_from_the_text_as_written(boq_profile) -> None:
    lines = [item("1.1", "Kernbohrung", "Erster Satz. Abstimmung mit [PERSON_074] vorab. Ende.")]
    entry = read(boq_profile, lines).entries[0]
    found = search(r"abstimmung", entry.text)
    assert found is not None
    assert entry.quote(found) == "Abstimmung mit [PERSON_074] vorab."
    assert entry.quote_short() == "Kernbohrung"
    sentence = "Das Rohr " + "und die weiteren Teile " * 20 + "wird geprüft."
    deep = read(boq_profile, [item("1.2", "Rohr", sentence)])
    hit = search(r"geprüft", deep.entries[0].text)
    assert hit is not None
    shown = deep.entries[0].quote(hit, 100)
    assert shown.startswith("…") and "geprüft" in shown and len(shown) <= 100


def test_windows_cover_a_long_text_in_bounded_overlapping_pieces() -> None:
    text = " ".join(f"wort{i:05d}" for i in range(4000))  # about 40,000 characters
    pieces = list(windows(text, WINDOW_OVERLAP))
    assert len(pieces) > len(text) // patterns.MAX_MATCH_CHARS
    covered = 0
    for offset, window in pieces:
        assert len(window) <= patterns.MAX_MATCH_CHARS
        assert text[offset : offset + len(window)] == window
        assert offset <= covered  # no gap
        assert offset == 0 or text[offset - 1] == " "  # starts at a word
        covered = max(covered, offset + len(window))
    assert covered == len(text)
    for (first, window), (second, _) in itertools.pairwise(pieces):
        assert first + len(window) - second <= WINDOW_OVERLAP + 10


def test_windows_of_text_without_whitespace_and_of_short_text() -> None:
    assert list(windows("kurz", WINDOW_OVERLAP)) == [(0, "kurz")]
    solid = "x" * 1200
    pieces = list(windows(solid, WINDOW_OVERLAP))
    assert sum(len(w) for _, w in pieces) >= len(solid)
    assert all(len(w) <= patterns.MAX_MATCH_CHARS for _, w in pieces)


def test_search_finds_words_deep_in_a_long_text() -> None:
    text = long_text("Die Ringraumdichtung ist gas- und wasserdicht.", 20_000)
    found = search(r"ringraumdichtung", text)
    assert found is not None and text[found.start : found.end] == "Ringraumdichtung"
    assert patterns.search(r"ringraumdichtung", text) is None  # the prefix alone misses it
    assert search(r"nicht vorhanden", text) is None


def test_search_start_reads_only_the_start() -> None:
    assert search_start(r"^rohr", "Rohr DN 100") == Found(0, 4)
    late = long_text("Rohr", 1000)
    assert search_start(r"rohr", late) is None
    assert search(r"rohr", late) is not None


def test_search_all_counts_a_match_in_an_overlap_once() -> None:
    text = long_text("wird gesondert vergütet", 450) + " und " + "x " * 100
    found = search_all(r"wird gesondert vergütet", text)
    assert len(found) == 1
    many = " ".join(["Bogen"] * 40)
    assert len(search_all(r"bogen", many, limit=5)) == 5
    assert search_all(r"x*", "abc") == []  # an empty match ends the search
