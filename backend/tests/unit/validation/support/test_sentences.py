"""Sentences of German bill text: the splitter of the clause checks."""

from __future__ import annotations

import time

import pytest

from app.validation.support.sentences import ABBREVIATIONS, sentences, split_sentences


class TestSplitting:
    def test_sentence_ends(self) -> None:
        text = "Verbau ist mit einzukalkulieren! Wird das geprüft? Ja; 3 Lagen. Ende."
        assert sentences(text) == [
            "Verbau ist mit einzukalkulieren!",
            "Wird das geprüft?",
            "Ja;",
            "3 Lagen.",
            "Ende.",
        ]

    def test_a_mark_followed_by_lower_case_does_not_end_a_sentence(self) -> None:
        assert sentences("Boden lösen. laden, fördern; lagern") == [
            "Boden lösen. laden, fördern; lagern"
        ]

    def test_a_mark_needs_whitespace_after_it(self) -> None:
        assert sentences("Rohr DN/OD 63.Neu und 1,5.Weiter") == ["Rohr DN/OD 63.Neu und 1,5.Weiter"]

    @pytest.mark.parametrize(
        "text",
        [
            "Kies ca. 5 m tief",
            "Stützschichten, z. B. Quarzkies",
            "Stützschichten, z.B. Quarzkies",
            "Stützschichten, z.  B. Quarzkies",
            "Leistung wie Pos. 3 und Nr. 4 ausführen",
            "Kosten gem. Vertrag",
            "Einbau lt. Plan",
            "Dämmung bzw. Abdichtung",
            "Pumpen evtl. Grundwasser",
            "Pumpen ggf. Grundwasser",
            "Pumpen, d. h. Grundwasser",
            "Pumpen u. a. Grundwasser",
            "Pumpen usw. Grundwasser",
            "Abrechnung nach Std. Facharbeiter",
            "Rohre 5 St. Formstücke",
            "Abrechnung lfd. Meter",
            "Preis zzgl. Material",
            "Beton o. ä. Baustoff",
            "Beton u. ä. Baustoff",
            "gemäß Abs. 2 und Art. 3, Kap. 4, Ziff. 5",
            "Ausführung vgl. Detail",
            "Ausführung s. Plan",
            "max. 20 t, min. 5 t, mind. 3 Lagen",
            "Gew. 12 kg, Pkt. 4",
            "Leitungen einschl. Formstücke und inkl. Dichtungen",
        ],
    )
    def test_no_sentence_ends_after_an_abbreviation(self, text: str) -> None:
        assert sentences(text) == [text]

    def test_abbreviations_are_matched_without_regard_to_case(self) -> None:
        assert sentences("Länge CA. 5 m, Z. B. Kies") == ["Länge CA. 5 m, Z. B. Kies"]

    def test_an_abbreviation_starts_a_word(self) -> None:
        # "s." is an abbreviation; the s that ends "Maßes" is not.
        assert sentences("Länge des Maßes. Dann") == ["Länge des Maßes.", "Dann"]
        assert sentences("Ausführung s. Plan. Dann") == ["Ausführung s. Plan.", "Dann"]

    def test_a_dot_between_two_numbers_does_not_end_a_sentence(self) -> None:
        assert sentences("Wie Position 5. 4. 17., jedoch Bauwerker") == [
            "Wie Position 5. 4. 17., jedoch Bauwerker"
        ]
        assert sentences("Beginn am 1. 2. 2026. Dann") == ["Beginn am 1. 2. 2026.", "Dann"]
        # After a word, a number starts the next sentence.
        assert sentences("Tiefe 2 m. 3 Lagen") == ["Tiefe 2 m.", "3 Lagen"]

    def test_every_abbreviation_of_the_list_is_honoured(self) -> None:
        for abbreviation in ABBREVIATIONS:
            text = f"Leistung {abbreviation} Beton"
            assert sentences(text) == [text], abbreviation

    def test_offsets_point_into_the_text(self) -> None:
        text = "  Erster Satz.   Zweiter Satz!  "
        found = split_sentences(text)
        assert [(s.text, s.start, s.end) for s in found] == [
            ("Erster Satz.", 2, 14),
            ("Zweiter Satz!", 17, 30),
        ]
        assert all(text[s.start : s.end] == s.text for s in found)

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_blank_text_has_no_sentences(self, text: str) -> None:
        assert split_sentences(text) == []

    def test_text_without_an_end_is_one_sentence(self) -> None:
        assert sentences("Verbau einbringen und beseitigen") == ["Verbau einbringen und beseitigen"]

    def test_anonymisation_tokens_and_blanks_stay_inside_their_sentence(self) -> None:
        text = (
            "Anlage nach [PERSON_125] des AN, [TB11 Anlage [ ..... ] ] vom Bieter einzutragen. "
            "Sand-PER0033-Gemisch."
        )
        assert sentences(text) == [
            "Anlage nach [PERSON_125] des AN, [TB11 Anlage [ ..... ] ] vom Bieter einzutragen.",
            "Sand-PER0033-Gemisch.",
        ]


class TestSpeed:
    @pytest.mark.parametrize(
        "text",
        [
            "a. " * 11_000,
            "Ca. " * 8_000,
            "z. " * 11_000,
            "5. " * 11_000,
            "." * 32_000,
            " " * 32_000,
            "Verbau ist einzukalkulieren. " * 1_100,
        ],
    )
    def test_long_texts_are_split_in_linear_time(self, text: str) -> None:
        started = time.perf_counter()
        found = split_sentences(text)
        assert time.perf_counter() - started < 0.5
        assert all(text[s.start : s.end] == s.text for s in found)
