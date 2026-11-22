"""domain.boq_companion_work: work a bill describes without the work that goes with it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.boq_companion_work import (
    DEFAULT_PAIRS,
    RULE_BACKFILL,
    RULE_PENETRATION,
    RULE_PRESSURE_TEST,
    RULE_SITE_EQUIPMENT,
    TABLES_SKIPPED_NO_LONG_TEXTS,
    TRIGGERS_SATISFIED_ELSEWHERE,
    TRIGGERS_SATISFIED_OWN_TEXT,
    CompanionWorkConfig,
    CompanionWorkDetector,
)
from tests.unit.validation.deterministic.references_fixtures import (
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    by_rule,
    run,
    run_pipeline,
)
from tests.unit.validation.domain.boq_text_fixtures import (
    SHORT_ONLY,
    bill,
    continuation,
    item,
    long_text,
    note,
)

DETECTOR = CompanionWorkDetector
TEXT = "Leistung nach Plan."  # a Langtext, so the bill counts as one with long texts


def result(profile, lines, **kwargs):
    return run(DETECTOR, bill(profile, lines, **kwargs), profile)


# ------------------------------------------------------------------ penetration_without_seal
def test_wall_penetrations_without_a_seal(boq_profile) -> None:
    lines = [
        item("05.01.0060", "Wandblende für Kernbohrungen DN 150", TEXT),
        item("05.01.0061", "Rohrleitungswanddurchführung DN 80", TEXT),
        item("05.01.0062", "Futterrohr DN 200 einbauen", TEXT),
        item("05.01.0070", "Rohr PE 100 DN 150 liefern und verlegen", TEXT),
    ]
    (issue,) = by_rule(result(boq_profile, lines).issues, RULE_PENETRATION)
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence_class is EvidenceClass.SEMANTIC_WARNING
    assert issue.title == "Wall penetrations without a seal: 3 positions"
    assert "05.01.0060" in issue.explanation and "05.01.0062" in issue.explanation
    assert "no position seals them" in issue.explanation
    assert issue.evidence[0].detail.startswith("05.01.0060, 05.01.0061, 05.01.0062")
    assert {c.source.a1 for c in issue.affected_cells} == {"B2", "B3", "B4"}
    assert "Do not add a position to the bill" in (issue.suggested_action or "")
    assert_well_formed([issue])


def test_a_seal_in_the_own_text_or_in_another_position_satisfies(boq_profile) -> None:
    own = [
        item("1.1", "Kernbohrung DN 150", "Ringraum gas- und wasserdicht verschließen."),
        item("1.2", "Hauseinführung DN 50", "Gas- u. druckwasserdicht einbauen."),
    ]
    found = result(boq_profile, own)
    assert not found.issues
    assert found.coverage[TRIGGERS_SATISFIED_OWN_TEXT] == 2
    elsewhere = [
        item("1.1", "Kernbohrung DN 150", TEXT),
        item("1.2", "Ringraumdichtung Link-Seal für DN 150", TEXT),
    ]
    found = result(boq_profile, elsewhere)
    assert not found.issues
    assert found.coverage[TRIGGERS_SATISFIED_ELSEWHERE] == 1


def test_a_seal_named_in_a_continuation_line_counts_as_own_text(boq_profile) -> None:
    lines = [
        item("1.1", "Kernbohrung DN 150", TEXT),
        continuation("Einschließlich Dichtungseinsatz."),
    ]
    assert not result(boq_profile, lines).issues


def test_removal_closing_and_the_core_drill_are_not_penetrations(boq_profile) -> None:
    lines = [
        item("1.1", "Kernbohrung verschließen", TEXT),
        item("1.2", "Futterrohr ausbauen", TEXT),
        item("1.3", "Kernbohrung mit Kernbohrgerät", TEXT),
        item("1.4", "Wanddurchführung abdichten", TEXT),
    ]
    assert not result(boq_profile, lines).issues


# ------------------------------------------------------------------ site_equipment_without_upkeep
def test_site_equipment_set_up_and_cleared_without_upkeep(boq_profile) -> None:
    lines = [
        item("01.02.0001", "Bauzaun aufstellen und räumen", TEXT),
        item("01.02.0002", "Bürocontainer aufstellen, räumen", TEXT),
        # Kept on site in another top-level section: not the same equipment's upkeep here.
        item("05.04.0005", "Bauzaun vorhalten", TEXT, unit="mWo"),
    ]
    (issue,) = by_rule(result(boq_profile, lines).issues, RULE_SITE_EQUIPMENT)
    assert issue.evidence[0].detail == "01.02.0001, 01.02.0002 (Bauzaun, Container)"
    assert "vorhalten" in issue.explanation
    # Plan 5a: each Omission notes that it may become a change order after award.
    assert (issue.suggested_action or "").endswith(
        "If none pays for it, this may become a change order after award, subject to the contract."
    )


def test_every_omission_notes_the_change_order(boq_profile) -> None:
    """Plan 5a: each Omission notes that it may become a change order after award."""
    for pair in DEFAULT_PAIRS:
        assert "may become a change order after award, subject to the contract" in (
            pair.recommendation
        ), pair.rule_id


@pytest.mark.parametrize(
    "upkeep",
    [
        item("01.02.0009", "Bauzaun vorhalten", TEXT, unit="psch"),
        item("01.02.0009", "Bauzaun, Standzeit", TEXT, unit="Wo"),  # a unit of time
        item("01.02.0009", "Bauzaun", TEXT, unit="mWo"),  # a time unit the profile lacks
    ],
)
def test_upkeep_of_the_same_equipment_in_the_same_section_satisfies(boq_profile, upkeep) -> None:
    lines = [item("01.02.0001", "Bauzaun aufstellen und räumen", TEXT), upkeep]
    assert not result(boq_profile, lines).issues


def test_upkeep_of_other_equipment_does_not_satisfy(boq_profile) -> None:
    lines = [
        item("01.02.0001", "Bauzaun aufstellen und räumen", TEXT),
        item("01.02.0002", "Container vorhalten", TEXT),
    ]
    assert by_rule(result(boq_profile, lines).issues, RULE_SITE_EQUIPMENT)


def test_equipment_kept_by_its_own_position_is_fine(boq_profile) -> None:
    lines = [
        item("1.1", "Bauzaun aufstellen, vorhalten und räumen", TEXT),
        item("1.2", "Absperrschieber DN 100 einbauen", TEXT),  # a valve, not a barrier
        item("1.3", "Container liefern", TEXT),  # not set up and cleared
    ]
    assert not result(boq_profile, lines).issues


# ------------------------------------------------------------------ pressure test, backfill
def test_pressure_pipes_without_a_pressure_test(boq_profile) -> None:
    lines = [item("2.1", "Druckrohr PE 100 DN 150 liefern und verlegen", TEXT)]
    (issue,) = by_rule(result(boq_profile, lines).issues, RULE_PRESSURE_TEST)
    assert issue.title == "Pressure pipes without a pressure test: 1 position"
    assert "1 position of this bill describes" in issue.explanation


def test_a_pressure_test_in_a_note_satisfies(boq_profile) -> None:
    lines = [
        item("2.1", "Druckrohr PE 100 DN 150 liefern und verlegen", TEXT),
        note("Hinweis", "Die Druckprüfung nach DIN EN 805 ist in die Preise einzurechnen."),
    ]
    assert not result(boq_profile, lines).issues


def test_trench_excavation_without_backfill(boq_profile) -> None:
    lines = [
        item("3.1", "Rohrgraben ausheben, Tiefe bis 2 m", TEXT),
        item("3.2", "Baugrube herstellen", TEXT),
    ]
    (issue,) = by_rule(result(boq_profile, lines).issues, RULE_BACKFILL)
    assert issue.evidence[0].detail == "3.1, 3.2 (Graben)"


@pytest.mark.parametrize(
    "backfill",
    [
        "Rohrgraben verfüllen und verdichten",
        "Leitungszone herstellen",
        "Boden seitlich lagern und wieder einbauen",
    ],
)
def test_backfill_anywhere_in_the_bill_satisfies(boq_profile, backfill) -> None:
    lines = [item("3.1", "Rohrgraben ausheben", TEXT), item("3.9", backfill, TEXT)]
    assert not result(boq_profile, lines).issues


# ------------------------------------------------------------------ bills, tokens, limits
def test_a_bill_without_long_texts_is_not_checked(boq_profile) -> None:
    lines = [item("1.1", "Kernbohrung DN 150"), item("1.2", "Rohrgraben ausheben")]
    for columns in (SHORT_ONLY, None):
        found = result(boq_profile, lines, **({"columns": columns} if columns else {}))
        assert not found.issues
        assert found.coverage[TABLES_SKIPPED_NO_LONG_TEXTS] == 1
        assert "no item has a Langtext" in found.notes[0]


def test_tokens_neither_trigger_nor_satisfy(boq_profile) -> None:
    lines = [
        item("1.1", "Kernbohrung DN 150 für [PERSON_074]", "Abstimmung mit TEL00009 vorab."),
        item("1.2", "[FIRMA_031] Leistung", "Ansprechpartner PER89."),
    ]
    (issue,) = by_rule(result(boq_profile, lines).issues, RULE_PENETRATION)
    assert issue.evidence[0].detail == "1.1 (Wanddurchführung)"


def test_a_seal_deep_in_a_long_text_is_found(boq_profile) -> None:
    lines = [item("1.1", "Kernbohrung DN 150", long_text("Ringraumdichtung einbauen.", 30_000))]
    assert not result(boq_profile, lines).issues


def test_long_lists_are_capped_and_counted(boq_profile) -> None:
    lines = [item(f"1.{i}", "Kernbohrung DN 100", TEXT) for i in range(1, 31)]
    found = run(DETECTOR, bill(boq_profile, lines), boq_profile, {"max_cells_per_issue": 5})
    (issue,) = found.issues
    assert len(issue.affected_cells) == 5
    assert "(all 30: 1.1, 1.2" in issue.explanation
    assert issue.explanation.count('"Kernbohrung DN 100"') == 3


def test_not_applicable_without_a_description(boq_profile) -> None:
    dataset = bill(boq_profile, [item("1.1", "x")], columns=[("OZ", "item_code")])
    assert not applicability(DETECTOR, dataset, boq_profile).applicable
    no_pairs = applicability(
        DETECTOR, bill(boq_profile, [item("1.1", "x")]), boq_profile, {"pairs": []}
    )
    assert not no_pairs.applicable


def test_the_profile_can_replace_the_pairs() -> None:
    pair = {
        "rule_id": "tiles_without_grout",
        "title": "Tiles without grout",
        "described": "tiling",
        "missing": "no position grouts them",
        "companion_words": "verfugen",
        "triggers": [{"name": "Fliesen", "pattern": r"fliesen\s+verlegen"}],
        "companion_pattern": r"verfug",
        "recommendation": "Ask a bidder question.",
    }
    config = CompanionWorkConfig.model_validate({"pairs": [pair]})
    assert config.pairs[0].rule_id == "tiles_without_grout"
    with pytest.raises(ValidationError):
        CompanionWorkConfig.model_validate({"pairs": [pair, pair]})
    with pytest.raises(ValidationError):
        CompanionWorkConfig.model_validate({"pairs": [{**pair, "companion_pattern": "x*"}]})
    with pytest.raises(ValidationError):
        CompanionWorkConfig.model_validate(
            {"pairs": [{**pair, "triggers": [pair["triggers"][0], pair["triggers"][0]]}]}
        )
    assert CompanionWorkConfig.model_validate({"time_unit_texts": ["m Wo"]}).time_unit_texts == (
        "mwo",
    )


def test_findings_pass_the_pipeline_evidence_policy(boq_profile) -> None:
    lines = [
        item("01.01.0010", "Kernbohrung DN 150", TEXT),
        item("01.01.0020", "Bauzaun aufstellen und räumen", TEXT),
        item("01.01.0030", "Druckrohr DN 100 verlegen", TEXT),
        item("01.01.0040", "Rohrgraben ausheben", TEXT),
    ]
    outcome = run_pipeline(DETECTOR, bill(boq_profile, lines), boq_profile)
    assert sorted(i.rule_id for i in outcome.issues) == sorted(
        [RULE_PENETRATION, RULE_SITE_EQUIPMENT, RULE_PRESSURE_TEST, RULE_BACKFILL]
    )
    assert_unique_fingerprints(outcome.issues)
    assert_well_formed(outcome.issues)
