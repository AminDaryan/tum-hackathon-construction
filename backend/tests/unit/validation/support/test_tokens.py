"""Anonymisation tokens: found, so that no check reads them as words."""

from __future__ import annotations

import time

import pytest

from app.validation.support.tokens import is_token, mask_tokens, overlaps_token, token_spans


@pytest.mark.parametrize(
    "token",
    [
        "[PERSON_074]",
        "[ORT_030]",
        "[PERSON_00000000083]",
        "[ORT_00030]",
        "[PROJEKT_001]",
        "[NUMMER_001]",
        "[PERSON_000000000000000000000030]",
        "ORT_030",
        "PER89",
        "PER029",
        "PER0033",
        "TEL00009",
        "FIR62",
        "P125",
        "###",
        "##",
    ],
)
def test_tokens_of_the_sample_bills(token: str) -> None:
    assert is_token(token)
    assert is_token(f"{token},")
    assert token_spans(f"vor {token} nach") == [(4, 4 + len(token))]


@pytest.mark.parametrize(
    "word",
    ["Verbau", "DN300", "PE100", "C25/30", "SDR11", "EV2", "P12", "#", "[TA11", "Pos.", "per89"],
)
def test_words_and_codes_are_not_tokens(word: str) -> None:
    assert not is_token(word)


def test_tokens_are_masked_with_spaces_of_the_same_length() -> None:
    text = "Ansprechpartner [PERSON_074] in ORT_030, Tel. TEL00009, Firma FIR62, Nr. ###"
    masked = mask_tokens(text)
    assert len(masked) == len(text)
    for token in ("[PERSON_074]", "ORT_030", "TEL00009", "FIR62", "###", "PERSON"):
        assert token not in masked
    assert "Ansprechpartner" in masked and "Firma" in masked
    # Ordinary words, codes and markers are not tokens.
    kept = "DN 150, PE100-RC, DIN EN 1610, [TA11 Zusatztext ], PER-Folie"
    assert mask_tokens(kept) == kept


def test_a_token_inside_a_word() -> None:
    text = "Bodengruppe 1 SU DIN 18196 (Sand-PER0033-Gemisch)"
    [(start, end)] = token_spans(text)
    assert text[start:end] == "PER0033"


def test_a_match_that_touches_a_token_overlaps_it() -> None:
    text = "nach [PERSON_125] des AN"
    assert overlaps_token(text, 0, 10)  # "nach [PERS"
    assert overlaps_token(text, 5, 17)
    assert not overlaps_token(text, 0, 5)  # "nach "
    assert not overlaps_token(text, 17, len(text))  # " des AN"
    assert not overlaps_token("nach Wahl des AN", 0, 16)


def test_long_texts_are_scanned_in_linear_time() -> None:
    for text in ("[" * 32_000, "[PERSON_" * 4_000, "PER" * 10_000, "#" * 32_000, "P1 " * 10_000):
        started = time.perf_counter()
        token_spans(text)
        assert time.perf_counter() - started < 0.5
