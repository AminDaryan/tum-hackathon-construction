"""domain.boq_separate_payment: "wird gesondert vergütet" without a paying position."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.boq_separate_payment import (
    CLAUSES_ON_TOKENS,
    CLAUSES_PAID,
    CLAUSES_SKIPPED_NO_HEAD,
    RULE_NO_PAYER,
    SeparatePaymentConfig,
    SeparatePaymentDetector,
)
from tests.unit.validation.deterministic.references_fixtures import (
    applicability,
    assert_well_formed,
    run,
)
from tests.unit.validation.domain.boq_text_fixtures import bill, item, note

DETECTOR = SeparatePaymentDetector


def found(profile, lines, overrides=None):
    return run(DETECTOR, bill(profile, lines), profile, overrides)


def test_work_paid_separately_without_a_paying_position(boq_profile) -> None:
    lines = [
        item("02.05.0007", "Geländer montieren", "Die Edelstahlstützen werden gesondert vergütet."),
        item(
            "02.05.0008",
            "Rohr verlegen",
            "Reinigen und Anspritzen der Unterlage werden gesondert vergütet.",
        ),
        item("02.05.0009", "Asphalt einbauen", "Leistung nach Plan."),
    ]
    (issue,) = found(boq_profile, lines).issues
    assert issue.rule_id == RULE_NO_PAYER
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence_class is EvidenceClass.SEMANTIC_WARNING
    assert issue.title == "Paid separately, but no position names it: 2 clauses"
    assert issue.evidence[0].detail == "Edelstahlstützen (02.05.0007); Anspritzen (02.05.0008)"
    assert '02.05.0007 "Die Edelstahlstützen werden gesondert vergütet."' in issue.explanation
    assert "BGH, X ZB 7/04" in (issue.suggested_action or "")
    assert_well_formed([issue])


@pytest.mark.parametrize(
    "payer",
    [
        "Edelstahlstütze liefern und montieren",  # the stem
        "Stützen aus Edelstahl",  # not the stem: still unpaid
    ],
)
def test_a_position_naming_the_work_pays_for_it(boq_profile, payer) -> None:
    lines = [
        item("1.1", "Geländer montieren", "Die Edelstahlstützen werden gesondert vergütet."),
        item("1.2", payer, "Leistung."),
    ]
    result = found(boq_profile, lines)
    paid = payer.startswith("Edelstahlstütze ")
    assert bool(result.issues) is not paid
    assert result.coverage.get(CLAUSES_PAID, 0) == int(paid)


def test_synonyms_name_the_paying_position(boq_profile) -> None:
    lines = [
        item("1.1", "Rohr verlegen", "Die Bettung wird gesondert vergütet."),
        item("1.2", "Leitungszone herstellen", "Leistung."),
        item("1.3", "Schacht setzen", "Form- und Verbindungsstücke werden separat vergütet."),
        item("1.4", "Bogen 45 Grad DN 100", "Leistung."),
    ]
    assert not found(boq_profile, lines).issues
    custom = found(boq_profile, [lines[0], item("1.2", "Splitt 2/5", "x")], {"synonyms": {}})
    assert custom.issues
    with_synonym = found(
        boq_profile,
        [lines[0], item("1.2", "Splitt 2/5", "x")],
        {"synonyms": {"Bettung": ["Splitt"]}},
    )
    assert not with_synonym.issues


def test_the_clause_itself_in_another_position_does_not_pay(boq_profile) -> None:
    lines = [
        item("1.1", "Rohr DN 100 verlegen", "Die Bettung wird gesondert vergütet."),
        item("1.2", "Rohr DN 150 verlegen", "Die Bettung wird gesondert vergütet."),
    ]
    (issue,) = found(boq_profile, lines, {"synonyms": {}}).issues
    assert issue.evidence[0].detail == "Bettung (1.1, 1.2)"


def test_the_work_before_a_bracketed_clause(boq_profile) -> None:
    lines = [
        item("1.1", "Rohr verlegen", "Einschließlich Rohrbefestigungen (wird gesondert vergütet).")
    ]
    (issue,) = found(boq_profile, lines).issues
    assert issue.evidence[0].detail == "Rohrbefestigungen (1.1)"


@pytest.mark.parametrize(
    "clause",
    [
        "Dies wird in Pos. 3 gesondert vergütet.",  # no work named before "wird"
        "Im Abschnitt 5 wird gesondert vergütet.",  # a place after a preposition
        "Der Zaun wird gesondert vergütet.",  # head noun too short for a stem
        "Nach [PERSON_125] des AN wird gesondert vergütet.",  # a token is not a noun
    ],
)
def test_clauses_without_a_usable_head_noun_are_skipped(boq_profile, clause) -> None:
    result = found(boq_profile, [item("1.1", "Rohr verlegen", clause)])
    assert not result.issues


@pytest.mark.parametrize(
    "clause", ["Das [PERSON_093] wird gesondert vergütet.", "Die PER0033 (wird gesondert vergütet)"]
)
def test_work_named_by_a_token_is_listed(boq_profile, clause) -> None:
    """Plan 5a: when the work is a token, no position can be shown to pay for it, so the
    clause is an Omission and the bidder question is asked."""
    lines = [
        item("01.0010", "Rohr verlegen", clause),
        item("01.0020", "Bettung", "Die Bettung wird gesondert vergütet."),
    ]
    result = found(boq_profile, lines)
    (issue,) = result.issues
    token = clause.split()[1]
    assert issue.evidence[0].detail == f"{token} (01.0010); Bettung (01.0020)"
    assert "Ask a bidder question" in (issue.suggested_action or "")
    assert result.coverage[CLAUSES_ON_TOKENS] == 1
    assert CLAUSES_SKIPPED_NO_HEAD not in result.coverage


def test_counts_skipped_clauses(boq_profile) -> None:
    result = found(boq_profile, [item("1.1", "Rohr", "Der Zaun wird gesondert vergütet.")])
    assert result.coverage[CLAUSES_SKIPPED_NO_HEAD] == 1


def test_notes_are_neither_clauses_nor_payers(boq_profile) -> None:
    lines = [
        note("Hinweis", "Die Wasserhaltung wird gesondert vergütet."),
        item("1.1", "Rohr verlegen", "Das Gerüst wird gesondert vergütet."),
        note("Hinweis", "Gerüste stellt der Auftraggeber."),
    ]
    (issue,) = found(boq_profile, lines).issues
    assert issue.evidence[0].detail == "Gerüst (1.1)"


def test_a_clause_deep_in_a_long_text(boq_profile) -> None:
    text = "Die Leistung ist nach Plan auszuführen. " * 500 + (
        "Die Edelstahlstützen werden gesondert vergütet."
    )
    assert found(boq_profile, [item("1.1", "Geländer", text)]).issues


def test_config_is_validated(boq_profile) -> None:
    config = SeparatePaymentConfig.model_validate({"synonyms": {" Verbau ": [" Spundwand ", ""]}})
    assert config.synonyms == {"verbau": ("spundwand",)}
    with pytest.raises(ValidationError):
        SeparatePaymentConfig.model_validate({"synonyms": {" ": ["x"]}})
    with pytest.raises(ValidationError):
        SeparatePaymentConfig.model_validate({"clause_pattern": "(?:)"})
    dataset = bill(boq_profile, [item("1.1", "x")], columns=[("OZ", "item_code")])
    assert not applicability(DETECTOR, dataset, boq_profile).applicable
