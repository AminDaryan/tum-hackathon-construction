"""domain.boq_typos: repeated words, known misspellings and one-off variants of frequent words."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.typos import (
    PAIRS_IGNORED,
    RULE_KNOWN,
    RULE_REPEATED,
    RULE_VARIANT,
    WORDS_READ,
    BoqTyposDetector,
    TyposConfig,
    _levenshtein_one,
    _osa_one,
)
from tests.unit.validation.deterministic.references_fixtures import (
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    run,
)

DETECTOR = BoqTyposDetector


def item(code, text):
    return [code, text, "1", "St", "10.00", None]


def result(profile, texts, overrides=None):
    rows = [item(f"1.{n}", text) for n, text in enumerate(texts, start=1)]
    return run(DETECTOR, boq_dataset(profile, rows), profile, overrides)


def test_a_repeated_word_is_a_slip_but_a_doubled_article_is_not(boq_profile) -> None:
    found = result(boq_profile, ["Rohre und und Formstücke", "Das, was das das Gerät kann"])
    [issue] = found.issues
    assert issue.rule_id == RULE_REPEATED and issue.issue_category == "spelling"
    assert (issue.evidence_class, issue.severity) == (
        EvidenceClass.SEMANTIC_WARNING,
        Severity.LOW,
    )
    assert issue.title == "1.1: 'und und' repeats a word"
    assert issue.expected_value is None
    assert found.coverage[WORDS_READ] > 0
    assert_well_formed(found.issues)


def test_a_known_misspelling_names_the_correct_form(boq_profile) -> None:
    [issue] = result(boq_profile, ["Kabel seperat verlegen"]).issues
    assert issue.rule_id == RULE_KNOWN
    assert (issue.observed_value, issue.expected_value) == ("seperat", "separat")


def test_a_one_off_variant_of_a_frequent_word_names_both_spellings(boq_profile) -> None:
    texts = [
        "Der Auftragnehmer liefert",
        "Der Auftragnehmer prüft",
        "Der Auftragnehmer montiert",
        "Der Auftragnehemer entsorgt",
    ]
    found = result(boq_profile, texts)
    [issue] = found.issues
    assert issue.rule_id == RULE_VARIANT
    assert issue.title == "1.4: 'Auftragnehemer' or 'Auftragnehmer'?"
    assert "3 times" in issue.explanation
    assert issue.affected_cells[0].source.a1 == "B5"


def test_inflections_joints_and_real_words_are_not_variants(boq_profile) -> None:
    texts = [
        "Mauerwerk beschrieben anzulegen",
        "Mauerwerk beschrieben anzulegen",
        "Mauerwerk beschrieben anzulegen",
        "Mauerwerks beschreiben abzulegen",  # joining s, ie/ei, a replaced letter
        "Mauerwerken",  # an inflected form
    ]
    assert result(boq_profile, texts).issues == []


def test_findings_are_capped_per_table(boq_profile) -> None:
    texts = ["seperat und und", "Standart wiederrum"]
    found = result(boq_profile, texts, {"max_findings": 2})
    assert len(found.issues) == 2
    assert_unique_fingerprints(found.issues)


def test_the_profile_can_add_misspellings(boq_profile) -> None:
    [issue] = result(
        boq_profile,
        ["Abdichtung gegen Bodenfeutigkeit"],
        {"misspellings": {"bodenfeutigkeit": "Bodenfeuchtigkeit"}},
    ).issues
    assert issue.expected_value == "Bodenfeuchtigkeit"


# The matcher of step B2 (2026-11-21): one edit, likely real-word pairs left out.
def frequent(word: str, times: int = 3) -> list[str]:
    return [f"{word} gemäß Plan"] * times


@pytest.mark.parametrize(
    ("rare", "common"),
    [
        ("Einschießlich", "Einschließlich"),  # a letter dropped
        ("Untergrundverbessserung", "Untergrundverbesserung"),  # a letter added
        ("Untergrundverbessarung", "Untergrundverbesserung"),  # a letter replaced
        ("Inbetriebnhame", "Inbetriebnahme"),  # two letters swapped
    ],
)
def test_one_edit_away(boq_profile, rare, common) -> None:
    [issue] = result(boq_profile, [*frequent(common), f"{rare} beachten"]).issues
    assert issue.rule_id == RULE_VARIANT
    assert (issue.observed_value, issue.expected_value) == (rare, common)


def test_swaps_are_not_counted_without_transpositions(boq_profile) -> None:
    texts = [*frequent("Inbetriebnahme"), "Inbetriebnhame"]
    assert not result(boq_profile, texts, {"transpositions": False}).issues


@pytest.mark.parametrize(
    ("rare", "common"),
    [
        ("Abschnitten", "Abschnitte"),  # the ending
        ("Verfüllung", "Erfüllung"),  # the first letter
        ("Schachtböden", "Schachtboden"),  # an umlaut
        ("verschweißten", "verschweißen"),  # a past participle
        ("Hausanschlussleitungen", "Hausanschlussleistungen"),  # an excluded pair inside
        ("Schächten", "Schichten"),
        ("Abtransport", "Antransport"),  # separable prefixes ab- and an-
        ("Ausbauten", "Aufbauten"),  # auf- and aus-
        ("Aufnahmen", "aufnehmen"),  # the noun and the verb
        ("Probeentnahmen", "Probeentnehmen"),  # an excluded pair inside
    ],
)
def test_likely_real_word_pairs_are_ignored(boq_profile, rare, common) -> None:
    found = result(boq_profile, [*frequent(common), f"{rare} prüfen"])
    assert not found.issues
    assert found.coverage[PAIRS_IGNORED] >= 1


def test_short_words_rare_references_and_codes_are_skipped(boq_profile) -> None:
    texts = [
        *frequent("Pflaster"),
        "Pflastre",  # 8 letters: too short to report
        *frequent("Kanalisation", times=2),
        "Kanalisatoin",  # the reference is used twice only
        *frequent("BETONSTAHL"),
        "BETONSTAHLL",  # capitals: a code
    ]
    assert not result(boq_profile, texts).issues


def test_a_prefix_pair_counts_only_at_the_start_of_the_word(boq_profile) -> None:
    """ab-/an- inside a word is no prefix, and a prefix pair the profile removes counts."""
    assert result(boq_profile, [*frequent("Grabenabdeckung"), "Grabenandeckung prüfen"]).issues
    texts = [*frequent("Antransport"), "Abtransport prüfen"]
    assert not result(boq_profile, texts).issues
    assert result(boq_profile, texts, {"excluded_prefixes": []}).issues


def test_distance_helpers() -> None:
    assert _osa_one("abcd", "abdc") and not _levenshtein_one("abcd", "abdc")
    assert _osa_one("abcd", "abd") and _levenshtein_one("abd", "abcd")
    assert _osa_one("abcd", "abxd") and _levenshtein_one("abcd", "abxd")
    assert not _osa_one("abcd", "abcd") and not _levenshtein_one("abcd", "abcd")
    assert not _osa_one("abcd", "badc") and not _osa_one("abcd", "ab")
    assert not _levenshtein_one("abcd", "axyd") and not _levenshtein_one("abcd", "ab")


def test_config_is_validated() -> None:
    assert TyposConfig.model_validate({"excluded_pairs": [["Ober", "Unter"]]}).excluded_pairs == (
        ("ober", "unter"),
    )
    assert TyposConfig.model_validate({"excluded_prefixes": [["Ab", "An"]]}).excluded_prefixes == (
        ("ab", "an"),
    )
    with pytest.raises(ValidationError):
        TyposConfig.model_validate({"excluded_pairs": [["gleich", "Gleich"]]})
    with pytest.raises(ValidationError):
        TyposConfig.model_validate({"excluded_prefixes": [["ab", ""]]})
    with pytest.raises(ValidationError):
        TyposConfig.model_validate({"min_length": 2})
