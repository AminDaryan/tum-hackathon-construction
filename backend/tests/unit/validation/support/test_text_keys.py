"""Comparison keys and character n-grams of descriptions."""

from __future__ import annotations

import pytest

from app.validation.deterministic import unit_compatibility
from app.validation.support.text_keys import char_ngrams, description_key


class TestDescriptionKey:
    @pytest.mark.parametrize(
        ("text", "key"),
        [
            ("  Mauerwerk KS  ２４ cm ", "mauerwerk ks 24 cm"),  # NFKC folds full-width digits
            ("Beton\tC25/30\nfür Wände", "beton c25/30 für wände"),
            ("STRASSE", "strasse"),
            ("Straße", "strasse"),  # case folding, not lower-casing
            ("m²", "m2"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_key(self, text: str, key: str) -> None:
        assert description_key(text) == key

    def test_the_key_is_idempotent(self) -> None:
        for text in ("  Mauerwerk KS  ２４ cm ", "Straße", "a b"):
            assert description_key(description_key(text)) == description_key(text)

    def test_unit_compatibility_uses_the_moved_function(self) -> None:
        assert unit_compatibility.description_key is description_key


class TestCharNgrams:
    def test_one_word_padded_with_a_space(self) -> None:
        assert char_ngrams("Beton") == [
            " be", "bet", "eto", "ton", "on ",
            " bet", "beto", "eton", "ton ",
            " beto", "beton", "eton ",
        ]  # fmt: skip

    def test_no_ngram_spans_two_words(self) -> None:
        grams = char_ngrams("KS 24", n_min=3, n_max=3)
        assert grams == [" ks", "ks ", " 24", "24 "]
        assert all(" " not in gram.strip() for gram in grams)

    def test_a_short_word_yields_itself_once(self) -> None:
        assert char_ngrams("m3") == [" m3", "m3 ", " m3 "]
        assert char_ngrams("a") == [" a "]
        assert char_ngrams("a", n_min=1, n_max=2) == [" ", "a", " ", " a", "a "]

    def test_text_is_keyed_first(self) -> None:
        assert char_ngrams("  BETON  ") == char_ngrams("beton")
        assert char_ngrams("２４") == char_ngrams("24")

    def test_repeats_are_kept_for_counting(self) -> None:
        assert char_ngrams("aa aa", n_min=3, n_max=3) == [" aa", "aa ", " aa", "aa "]

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_blank_text_has_no_ngrams(self, text: str) -> None:
        assert char_ngrams(text) == []

    def test_counts_per_length(self) -> None:
        # A padded word of length L has L - n + 1 n-grams of each length n <= L.
        word = "mauerwerk"  # padded length 11
        grams = char_ngrams(word, n_min=2, n_max=6)
        assert [len(g) for g in grams].count(2) == 10
        assert [len(g) for g in grams].count(6) == 6

    @pytest.mark.parametrize(("n_min", "n_max"), [(0, 3), (4, 3), (-1, -1)])
    def test_invalid_lengths_are_refused(self, n_min: int, n_max: int) -> None:
        with pytest.raises(ValueError, match="n_min"):
            char_ngrams("beton", n_min=n_min, n_max=n_max)
