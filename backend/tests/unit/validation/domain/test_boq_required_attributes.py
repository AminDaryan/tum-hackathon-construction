"""domain.boq_required_attributes: positions whose price needs a property the text omits."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.boq_required_attributes import (
    RULE_PIPE_DIMENSION,
    RULE_STRENGTH_CLASS,
    RULE_WASTE_CLASS,
    TRIGGERS_EXCLUDED,
    TRIGGERS_WITH_ATTRIBUTE,
    RequiredAttributesConfig,
    RequiredAttributesDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    by_rule,
    run,
    run_pipeline,
)
from tests.unit.validation.domain.boq_text_fixtures import (
    COLUMNS,
    SHORT_ONLY,
    bill,
    item,
    long_text,
)

DETECTOR = RequiredAttributesDetector


def issues(profile, lines, rule, **kwargs):
    return by_rule(run(DETECTOR, bill(profile, lines, **kwargs), profile).issues, rule)


# ------------------------------------------------------------------ disposal_waste_class
def test_disposal_without_a_waste_class(boq_profile) -> None:
    lines = [
        item("02.02.0001", "Ausbau und Entsorgung Filterfüllung", "Filterkies ausbauen.", "m3"),
        item("02.02.0002", "Boden laden und entsorgen", None, "t"),
    ]
    (issue,) = issues(boq_profile, lines, RULE_WASTE_CLASS)
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence_class is EvidenceClass.SEMANTIC_WARNING
    assert issue.title == "Disposal without a waste class: 2 positions"
    assert '02.02.0001 "Ausbau und Entsorgung Filterfüllung"' in issue.explanation
    assert issue.evidence[0].detail == "02.02.0001, 02.02.0002"
    assert "Ersatzbaustoffverordnung" in (issue.suggested_action or "")
    assert_well_formed([issue])


@pytest.mark.parametrize(
    "stated",
    [
        "Zuordnung Z 1.1 nach LAGA",
        "Abfallschlüssel AVV 17 05 04",
        "AVV170504",
        "Boden 17 05 03* (gefährlich)",
        "Klasse BM-F1 nach Ersatzbaustoffverordnung",
        "Deponieklasse DK I",
        "Der Boden ist unbelastet.",
        "Analyse liegt bei (Deklarationsanalyse).",
    ],
)
def test_a_stated_waste_class_satisfies(boq_profile, stated) -> None:
    lines = [item("2.1", "Boden laden und entsorgen", stated, "t")]
    assert not issues(boq_profile, lines, RULE_WASTE_CLASS)


@pytest.mark.parametrize(
    "still_open",
    [
        "AVV und LAGA-Klasse noch festzulegen.",
        "Die Zuordnung Z 1.1 oder Z 2 wird noch festgelegt.",
        "Einstufung nach Beprobung festzulegen.",
    ],
)
def test_a_class_said_to_be_still_open_is_no_class(boq_profile, still_open) -> None:
    # Moved from the risk table's D30 on 2026-11-21.
    lines = [
        item("2.1", "Aushub laden und entsorgen", still_open, "t"),
        item("2.2", "Aushub laden und entsorgen", "Zuordnung LAGA Z 1.1", "t"),
    ]
    (issue,) = issues(boq_profile, lines, RULE_WASTE_CLASS)
    assert issue.evidence[0].detail == "2.1"


@pytest.mark.parametrize(
    "short",
    [
        "Ver- und Entsorgungsleitung umverlegen",
        "Rohrleitungen ausbauen und entsorgen",
        "Schacht reinigen, Schlamm entsorgen",
        "Kabel entsorgen",
    ],
)
def test_sewers_metal_and_cleaning_are_not_mineral_waste(boq_profile, short) -> None:
    lines = [item("2.1", short, "Boden und Bauschutt.", "St")]
    assert not issues(boq_profile, lines, RULE_WASTE_CLASS)


def test_digits_in_a_token_are_not_a_waste_code(boq_profile) -> None:
    lines = [item("2.1", "Bauschutt entsorgen", "Deponie [PERSON_170504] nach Wahl.", "t")]
    assert issues(boq_profile, lines, RULE_WASTE_CLASS)


# ------------------------------------------------------------------ concrete_strength_class
def test_concrete_without_a_strength_class(boq_profile) -> None:
    lines = [
        item("03.01.0001", "Fundament-Sickerstein Normalbeton", "Nach DIN EN 206/ DIN 1045."),
        item("03.01.0002", "Magerbeton als Sauberkeitsschicht", "Dicke 5 cm."),
        item("03.01.0003", "Fundament aus Beton C 20/25 herstellen", "Ortbeton."),
    ]
    (issue,) = issues(boq_profile, lines, RULE_STRENGTH_CLASS)
    assert issue.evidence[0].detail == "03.01.0001, 03.01.0002"
    action = issue.suggested_action or ""
    assert action.startswith("Ask a bidder question for the missing strength class")
    assert 'Neighbouring positions state it, for example 03.01.0003 "' in action
    assert "C 20/25" in action


def test_reinforced_and_ready_mixed_concrete_need_a_strength_class(boq_profile) -> None:
    # Read since 2026-11-21, when the risk table's A01 left the strength class to this check:
    # Stahlbeton and Transportbeton with a verb of placing in the Kurztext.
    lines = [
        item("03.02.0001", "Stahlbetonwand W1 herstellen", "Wand d = 24 cm."),
        item("03.02.0002", "Transportbeton liefern", "Für Bodenplatte."),
        item("03.02.0003", "Stahlbetonwand W2, C30/37, herstellen", "Wand d = 24 cm."),
        item("03.02.0004", "Stahlbetonrohre DN 800 liefern", "Nach EN 1916."),
        item("03.02.0005", "Oberfläche Stahlbetondecke glätten", "Flügelglätter."),
        item("03.02.0006", "Fugenblech in Stahlbetonwand", "Arbeitsfuge."),
    ]
    (issue,) = issues(boq_profile, lines, RULE_STRENGTH_CLASS)
    assert issue.evidence[0].detail == "03.02.0001, 03.02.0002"


@pytest.mark.parametrize(
    "short",
    [
        "Schalung für Stahlbetonwand herstellen",
        "Bewehrung für Ortbetonfundament liefern und einbauen",
        "Betonstahl BSt 500 für Stahlbetondecke liefern",
        "Beschichtung auf Stahlbetonboden herstellen",
        "Durchbruch in Stahlbetonwand herstellen",
        "Stahlbetondecke sägen, Öffnung herstellen",
    ],
)
def test_work_on_concrete_needs_no_strength_class(boq_profile, short) -> None:
    lines = [item("3.1", short, "Leistung nach Plan.")]
    assert not issues(boq_profile, lines, RULE_STRENGTH_CLASS)


def test_formwork_named_after_the_concrete_does_not_exclude_it(boq_profile) -> None:
    lines = [item("3.1", "Ortbeton für Streifenfundament einschl. Schalung herstellen", "")]
    assert issues(boq_profile, lines, RULE_STRENGTH_CLASS)


@pytest.mark.parametrize(
    "short",
    [
        "Betonfundament abbrechen",
        "Bordstein aus Beton setzen, Rückenstütze Beton einbauen",
        "Schachtunterteil aus Beton einbauen",
        "Betonplatten liefern",
        "Transportbeton-Pumpe liefern und vorhalten",  # "ortbeton" inside a word
    ],
)
def test_precast_demolition_and_other_words_are_not_concrete_work(boq_profile, short) -> None:
    assert not issues(boq_profile, [item("3.1", short, "Leistung nach Plan.")], RULE_STRENGTH_CLASS)


def test_concrete_named_only_in_the_long_text(boq_profile) -> None:
    lines = [item("3.1", "Fundament herstellen", "Aus Ortbeton, Abmessungen nach Plan.")]
    assert issues(boq_profile, lines, RULE_STRENGTH_CLASS)
    stated = [item("3.1", "Fundament herstellen", "Aus Ortbeton C25/30.")]
    assert not issues(boq_profile, stated, RULE_STRENGTH_CLASS)


# ------------------------------------------------------------------ pipe_dimension
def test_pipes_and_fittings_without_a_dimension(boq_profile) -> None:
    lines = [
        item("04.01.0001", "Rohr PE 100 SDR 11 DN/OD 63 liefern und verlegen", "PE-Rohr."),
        item("04.01.0002", "Winkel PE 45Grad", "Formstück aus PE 100, schweißbar."),
        item("04.01.0003", "Muffe aus Guss einbauen", "Nach Herstellerangabe."),
    ]
    (issue,) = issues(boq_profile, lines, RULE_PIPE_DIMENSION)
    assert issue.evidence[0].detail == "04.01.0002, 04.01.0003"
    action = issue.suggested_action or ""
    assert "missing dimension (DN, OD or diameter)" in action
    assert "for example 04.01.0001" in action


@pytest.mark.parametrize(
    "text",
    [
        "Rohr AD bis 100mm",
        "Rohr da 110 x 6,6",
        "Bogen 30 Grad, Durchmesser 160",
        "Flansch Nennweite 150",
        "Kappe Ø 50",
        "Rohr d = 90",
    ],
)
def test_a_stated_dimension_satisfies(boq_profile, text) -> None:
    assert not issues(boq_profile, [item("4.1", text, "Liefern.")], RULE_PIPE_DIMENSION)


@pytest.mark.parametrize(
    "short",
    [
        "Trassenwarnband über Rohr verlegen",
        "Rohr in Sandbettung verlegen",
        "Rohrleitung ausbauen",
        "Straßenkappe für Schieber anpassen",
        "Schutzrohr verlegen",
        "Rohrgraben ausheben",
        "Inspektion Rohrleitung mit TV-Kamera",
    ],
)
def test_marking_bedding_protection_and_removal_are_not_pipe_supply(boq_profile, short) -> None:
    assert not issues(boq_profile, [item("4.1", short, "Leistung.")], RULE_PIPE_DIMENSION)


def test_a_pipe_word_later_in_the_text_needs_a_verb(boq_profile) -> None:
    named = [item("4.1", "Anschluss an vorhandenes Rohr", "Leistung.")]
    assert not issues(boq_profile, named, RULE_PIPE_DIMENSION)
    laid = [item("4.1", "Anschluss an Rohr herstellen", "Leistung.")]
    assert issues(boq_profile, laid, RULE_PIPE_DIMENSION)


def test_a_dimension_deep_in_a_long_text_is_found(boq_profile) -> None:
    lines = [item("4.1", "Rohr liefern und verlegen", long_text("Abmessung DN 150.", 20_000))]
    assert not issues(boq_profile, lines, RULE_PIPE_DIMENSION)


def test_neighbours_come_from_the_same_section(boq_profile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", COLUMNS)
    table.row([None, "Titel 1", None, None, None, None], kind=RowKind.SECTION, in_totals=None)
    table.row(["1.1", "Bogen PE 45 Grad", "Liefern.", "1", "St", None])
    table.row([None, "Titel 2", None, None, None, None], kind=RowKind.SECTION, in_totals=None)
    table.row(["2.1", "Bogen PE 45 Grad DN 100", "Liefern.", "1", "St", None])
    dataset = builder.build()
    (issue,) = by_rule(run(DETECTOR, dataset, boq_profile).issues, RULE_PIPE_DIMENSION)
    assert "Neighbouring" not in (issue.suggested_action or "")


# ------------------------------------------------------------------ bills, config
def test_kurztext_only_bills_are_checked(boq_profile) -> None:
    dataset = bill(boq_profile, [item("1.1", "Boden entsorgen")], columns=SHORT_ONLY)
    found = run(DETECTOR, dataset, boq_profile)
    assert by_rule(found.issues, RULE_WASTE_CLASS)


def test_coverage_counts_excluded_and_satisfied_triggers(boq_profile) -> None:
    lines = [
        item("1.1", "Boden entsorgen", "Z 2"),
        item("1.2", "Betonrohr DN 300 Beton einbauen", "Leistung."),
    ]
    found = run(DETECTOR, bill(boq_profile, lines), boq_profile)
    assert found.coverage[TRIGGERS_WITH_ATTRIBUTE] == 2  # the waste class, the pipe's DN
    assert found.coverage[TRIGGERS_EXCLUDED] == 1  # a precast concrete pipe


def test_not_applicable_without_a_description_or_rules(boq_profile) -> None:
    dataset = bill(boq_profile, [item("1.1", "x")], columns=[("OZ", "item_code")])
    assert not applicability(DETECTOR, dataset, boq_profile).applicable
    no_rules = applicability(
        DETECTOR, bill(boq_profile, [item("1.1", "x")]), boq_profile, {"rules": []}
    )
    assert not no_rules.applicable


def test_rules_are_validated() -> None:
    rule = {
        "rule_id": "paint_colour",
        "title": "Paint without a colour",
        "described": "painting",
        "attribute": "colour",
        "triggers": [[{"pattern": r"anstrich"}]],
        "attribute_pattern": r"\bRAL\s?\d{4}",
        "recommendation": "Ask a bidder question.",
    }
    assert RequiredAttributesConfig.model_validate({"rules": [rule]}).rules[0].attribute == "colour"
    with pytest.raises(ValidationError):
        RequiredAttributesConfig.model_validate({"rules": [rule, rule]})
    with pytest.raises(ValidationError):
        RequiredAttributesConfig.model_validate({"rules": [{**rule, "triggers": [[]]}]})
    with pytest.raises(ValidationError):
        RequiredAttributesConfig.model_validate({"rules": [{**rule, "attribute_pattern": "("}]})


def test_findings_pass_the_pipeline_evidence_policy(boq_profile) -> None:
    lines = [
        item("01.01.0010", "Boden entsorgen", "Leistung."),
        item("01.01.0020", "Ortbeton für Fundamente", "Leistung."),
        item("01.01.0030", "Rohr PE liefern und verlegen", "Leistung."),
    ]
    outcome = run_pipeline(DETECTOR, bill(boq_profile, lines), boq_profile)
    assert sorted(i.rule_id for i in outcome.issues) == sorted(
        [RULE_WASTE_CLASS, RULE_STRENGTH_CLASS, RULE_PIPE_DIMENSION]
    )
    assert_unique_fingerprints(outcome.issues)
    assert_well_formed(outcome.issues)
