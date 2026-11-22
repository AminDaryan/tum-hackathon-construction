"""domain.boq_description_clarity: descriptions a tender estimator cannot price as written."""

from __future__ import annotations

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.description_clarity import (
    ITEMS_READ,
    RULE_BIDDER_INPUT,
    RULE_CATCH_ALL,
    RULE_OPEN_DECISION,
    RULE_OPEN_SCOPE,
    RULE_PLACEHOLDER,
    RULE_RELATIVE,
    RULE_SHORT_ONLY,
    BoqDescriptionClarityDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    by_rule,
    run,
)

DETECTOR = BoqDescriptionClarityDetector
LONG_COLUMNS = [*BOQ_COLUMNS, ("Langtext", "long_description")]
LONG = (
    "Mauerwerk der Innenwände aus Kalksandstein-Plansteinen KS L-P 12-1,4, Dicke 17,5 cm, "
    "in Dünnbettmörtel nach DIN EN 1996, einschließlich Anpassen an die Bauteile."
)


def item(code, text, unit="m2", long=None, columns=BOQ_COLUMNS):
    values = [code, text, "10", unit, "25.00", None]
    return [*values, long] if columns is LONG_COLUMNS else values


def result(profile, rows, columns=BOQ_COLUMNS, overrides=None):
    return run(DETECTOR, boq_dataset(profile, rows, columns=columns), profile, overrides)


def test_text_left_to_be_filled_in_is_a_placeholder(boq_profile) -> None:
    found = result(boq_profile, [item("1.1", "Fliesen Format ???"), item("1.2", "Estrich")])
    [issue] = found.issues
    assert issue.rule_id == RULE_PLACEHOLDER and issue.issue_category == "unclear_description"
    assert (issue.evidence_class, issue.severity) == (
        EvidenceClass.SEMANTIC_WARNING,
        Severity.MEDIUM,
    )
    assert "???" in issue.explanation
    assert issue.affected_cells[0].source.a1 == "B2"
    assert found.coverage[ITEMS_READ] == 2
    assert_well_formed(found.issues)


def test_phrases_match_whole_words_in_any_case(boq_profile) -> None:
    rows = [item("1.1", "Taxxxi-Gelb"), item("1.2", "Farbton NOCH FESTZULEGEN")]
    [issue] = result(boq_profile, rows).issues
    assert issue.rule_id == RULE_PLACEHOLDER
    assert issue.affected_cells[0].source.a1 == "B3"  # "xxx" inside a word is no placeholder


def test_a_back_reference_with_nothing_before_it_is_unclear(boq_profile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(["1", "Mauerarbeiten", None, None, None, None], kind=RowKind.SECTION)
    table.row(item("1.1", "Wie vor, jedoch 24 cm"))  # the first item of its section
    table.row(item("1.2", "wie vor, jedoch 30 cm"))  # refers to 1.1: fine
    found = run(DETECTOR, builder.build(), boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE_RELATIVE and issue.severity is Severity.MEDIUM
    assert "1.1" in issue.title


def test_open_scope_is_reported_only_on_items_counted_in_the_total(boq_profile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(item("1.1", "Wasserhaltung bei Bedarf"))
    table.row(item("1.2", "Pumpe bei Bedarf vorhalten"), in_totals=False)  # a contingency item
    [issue] = run(DETECTOR, builder.build(), boq_profile).issues
    assert issue.rule_id == RULE_OPEN_SCOPE and issue.severity is Severity.LOW
    assert "bei Bedarf" in issue.explanation and "1.1" in issue.title


def test_open_scope_leaves_the_wording_of_the_clause_check_to_it(boq_profile) -> None:
    # domain.boq_clauses reports "nach Bedarf" and "nach (örtlichem) Erfordernis" (vague_wording)
    # and, in a lump sum, "nach Aufwand" (open_lump_sum): one condition, one finding.
    rows = [
        item("1.1", "Wasserhaltung nach Bedarf"),
        item("1.2", "Verbau je nach Erfordernis"),
        item("1.3", "Pumpen vorhalten, Abrechnung nach Aufwand", unit="psch"),
        item("1.4", "Boden abfahren, Menge nach Aufwand", unit="m3"),
        item("1.5", "Wasserhaltung nach Erfordernissen"),
    ]
    found = result(boq_profile, rows)
    reported = {issue.title.split()[1].rstrip(":"): issue.explanation for issue in found.issues}
    assert sorted(reported) == ["1.4", "1.5"]
    assert all(issue.rule_id == RULE_OPEN_SCOPE for issue in found.issues)
    assert "nach Aufwand" in reported["1.4"] and "nach Erfordernissen" in reported["1.5"]


def test_catch_all_leaves_required_inclusions_to_the_clause_check(boq_profile) -> None:
    # "einschl. aller erforderlichen ..." is domain.boq_clauses' vague_wording, which leaves
    # small material out on purpose; other catch-all wording stays here.
    rows = [
        item("1.1", "Rohre verlegen, einschl. aller erforderlichen Formstücke"),
        item("1.2", "Geländer montieren, inkl. sämtlicher notwendigen Befestigungsmittel"),
        item("1.3", "Rinne einbauen, einschl. aller Nebenarbeiten"),
        item("1.4", "Pumpe komplett einschl. aller erforderlichen Armaturen"),
    ]
    [catch_all] = by_rule(result(boq_profile, rows).issues, RULE_CATCH_ALL)
    assert "1.3" in catch_all.explanation and "1.4" in catch_all.explanation
    assert "1.1" not in catch_all.explanation and "1.2" not in catch_all.explanation
    assert "komplett" in catch_all.explanation


def test_a_decision_left_to_the_site_manager_is_open(boq_profile) -> None:
    [issue] = result(
        boq_profile, [item("1.1", "Anstrich, Farbe nach Angabe der Bauleitung")]
    ).issues
    assert issue.rule_id == RULE_OPEN_DECISION and issue.severity is Severity.LOW


def test_a_bare_short_text_in_a_bill_of_long_texts(boq_profile) -> None:
    rows = [
        item(f"1.{n}", "Mauerwerk KS", long=LONG, columns=LONG_COLUMNS) for n in range(1, 4)
    ] + [
        item("1.4", "Kleinteile", columns=LONG_COLUMNS),
        item("1.5", "Vorarbeiter", unit="h", columns=LONG_COLUMNS),  # daywork: short by nature
    ]
    found = result(boq_profile, rows, columns=LONG_COLUMNS)
    [issue] = found.issues
    assert issue.rule_id == RULE_SHORT_ONLY and issue.severity is Severity.LOW
    assert "1.4" in issue.title


def test_short_texts_in_a_bill_of_short_texts_are_normal(boq_profile) -> None:
    rows = [item(f"1.{n}", "Mauerwerk KS 17,5 cm", columns=LONG_COLUMNS) for n in range(1, 5)]
    assert result(boq_profile, rows, columns=LONG_COLUMNS).issues == []


def test_catch_all_wording_and_bidder_input_are_one_summary_each(boq_profile) -> None:
    rows = [
        item("1.1", "Türdrücker Edelstahl o.ä."),
        item("1.2", "Dübel, Schrauben etc."),
        item("1.3", "Fliesenkleber, angebotenes Fabrikat: ..."),
        item("1.4", "Fugenmörtel"),
    ]
    found = result(boq_profile, rows)
    [catch_all] = by_rule(found.issues, RULE_CATCH_ALL)
    [bidder] = by_rule(found.issues, RULE_BIDDER_INPUT)
    assert (catch_all.severity, catch_all.evidence_class) == (
        Severity.INFO,
        EvidenceClass.SEMANTIC_WARNING,
    )
    assert "1.1" in catch_all.explanation and "1.2" in catch_all.explanation
    assert (bidder.severity, bidder.evidence_class) == (
        Severity.INFO,
        EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
    )
    assert bidder.issue_category == "bidder_input"
    assert len(found.issues) == 2
    assert_unique_fingerprints(found.issues)
    assert_well_formed(found.issues)


def test_the_profile_can_replace_the_wording(boq_profile) -> None:
    rows = [item("1.1", "Fliesen Format ???"), item("1.2", "Farbe: TODO")]
    [issue] = result(boq_profile, rows, overrides={"placeholder_phrases": ["todo"]}).issues
    assert "TODO" in issue.explanation


def test_clear_descriptions_report_nothing(boq_profile) -> None:
    rows = [item("1.1", "Estrich CT-C25-F4, 50 mm"), item("1.2", "Fliesen 30 x 60 cm, R10")]
    assert result(boq_profile, rows).issues == []
