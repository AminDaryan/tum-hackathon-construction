"""domain.boq_contradictions: an item's texts, unit, quantity and type against each other."""

from __future__ import annotations

from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.contradictions import (
    RULE_BILLING,
    RULE_QUANTITY,
    RULE_SPEC,
    RULE_TYPE,
    BoqContradictionsDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    boq_dataset,
    run,
)

DETECTOR = BoqContradictionsDetector
COLUMNS = [*BOQ_COLUMNS, ("Langtext", "long_description")]


def item(code, short, long=None, quantity="10", unit="m"):
    return [code, short, quantity, unit, "25.00", None, long]


def result(profile, rows):
    return run(DETECTOR, boq_dataset(profile, rows, columns=COLUMNS), profile)


def test_short_and_long_text_naming_different_diameters(boq_profile) -> None:
    found = result(boq_profile, [item("1.1", "PVC-Rohr DN 125", "KG-Rohr DN 100 verlegen")])
    [issue] = found.issues
    assert issue.rule_id == RULE_SPEC and issue.issue_category == "contradiction"
    assert (issue.evidence_class, issue.severity) == (
        EvidenceClass.SEMANTIC_WARNING,
        Severity.MEDIUM,
    )
    assert issue.title == "Item 1.1: Short text says DN 125, long text says DN 100"
    assert issue.affected_cells[0].source.a1 == "B2"
    assert_well_formed(found.issues)


def test_each_kind_of_specification_is_compared(boq_profile) -> None:
    rows = [
        item("1.1", "Beton C20/25", "Ortbeton C 25/30, XC1"),
        item("1.2", "Stahlträger S235", "Baustahl S355 J2"),
        item("1.3", "Tür T30", "Feuerschutztür T 90"),
        item("1.4", "Anstrich RAL 7016", "Farbton RAL 9010"),
    ]
    issues = result(boq_profile, rows).issues
    assert [i.rule_id for i in issues] == [RULE_SPEC] * 4
    assert [i.affected_cells[0].source.a1 for i in issues] == ["B2", "B3", "B4", "B5"]


def test_the_same_conflict_on_several_items_is_one_finding(boq_profile) -> None:
    # A long text copied to several positions repeats one conflict; another value is another.
    rows = [
        item("3.1", "Beton C20/25", "Ortbeton C25/30"),
        item("3.2", "Beton C20/25 Fundament", "Ortbeton C 25/30"),
        item("3.3", "Beton C20/25 Sohle", "Ortbeton C25/30"),
        item("3.4", "Beton C20/25 Wand", "Ortbeton C30/37"),
    ]
    first, second = result(boq_profile, rows).issues
    assert first.title == "Item 3.1: Short text says C20/25, long text says C25/30 (and 2 more)"
    assert [c.source.a1 for c in first.affected_cells] == ["B2", "B3", "B4"]
    assert "3.2, 3.3" in first.explanation
    assert second.title == "Item 3.4: Short text says C20/25, long text says C30/37"


def test_a_long_text_repeating_the_short_value_is_consistent(boq_profile) -> None:
    rows = [
        item("1.1", "Übergang DN 150", "Übergangsstück von DN 150 auf DN 100"),
        item("1.2", "Beton C25/30", "Beton c 25 / 30"),  # spacing and case do not matter
        item("1.3", "Rohr DN 100"),  # no long text: nothing to compare
    ]
    assert result(boq_profile, rows).issues == []


def test_values_in_other_notations_are_compared(boq_profile) -> None:
    rows = [
        item("1.1", "T-Stück PE DN/OD75 SDR11", "T-Stück aus PE, 90 Grad, DN/OD 63, SDR 11"),
        item("1.2", "Reduzierung DN 125 / DN 50", "Reduzierung DN 100 / 50 bis PN 16"),
        item("1.3", "Absperrklappe DN250 PN6", "Absperrklappe, DN 250, Nenndruck 1,6 MPa (16 bar)"),
        item("1.4", "T-Stück AD 273mm 6 bar", "max. Betriebsüberdruck 2,5 MPa (25 bar)"),
        item("1.5", "Bogen DN 80, 15 - 30 Grad", "Bogen DN 80 PN 10, 88,9 x 2,0, 45 - 90 Grad"),
        item(
            "1.6", "Pflasterdecke gebraucht seitl. lagernd", "fabrikneue Steine, seitlich lagernd"
        ),
    ]
    issues = result(boq_profile, rows).issues
    assert [i.rule_id for i in issues] == [RULE_SPEC] * 6
    assert [i.title.split(": ", 1)[1] for i in issues] == [
        "Short text says DN/OD75, long text says DN/OD 63",
        "Short text says DN 125 / DN 50, long text says DN 100 / 50",
        "Short text says PN6, long text says Nenndruck 1,6 MPa (16 bar)",
        "Short text says 6 bar, long text says 25 bar",
        "Short text says 15 - 30 Grad, long text says 45 - 90 Grad",
        "Short text says gebraucht, long text says fabrikneue",
    ]
    assert_well_formed(issues)


def test_the_same_value_in_another_notation_is_consistent(boq_profile) -> None:
    rows = [
        item("1.1", "Ventil 1 bar", "Sicherheitsventil, Ansprechdruck 1,0 bar"),
        item("1.2", "Schieber PN 16", "Schieber, Nenndruck 1,6 MPa (16 bar), Prüfdruck 24 bar"),
        item("1.3", "Bogen 90°", "Bogen 90 Grad, Medientemperatur bis 60 Grad C"),
        item("1.4", "Rohr DN 100", "Rohr DN 100 mit Abzweig DN 50, Bögen 45 Grad und 90 Grad"),
        item("1.5", "Pflaster gebraucht", "gebrauchte oder fabrikneue Steine nach Wahl des AG"),
        item("1.6", "Reduzierung DN 125 / DN 50", "Reduzierung, großes Ende DN 125"),
    ]
    assert result(boq_profile, rows).issues == []


def test_a_text_measuring_the_item_in_another_unit(boq_profile) -> None:
    rows = [
        item("1.1", "Pflaster", "Abrechnung nach m² verlegter Fläche", unit="St"),
        item("1.2", "Pflaster", "Abrechnung nach qm", unit="m2"),  # the same unit, other name
        item("1.3", "Gerüst", "Abrechnung nach m² x Woche", unit="m2"),  # a compound: skipped
    ]
    [issue] = result(boq_profile, rows).issues
    assert issue.rule_id == RULE_BILLING and issue.severity is Severity.MEDIUM
    assert "1.1" in issue.title and "St" in issue.title
    assert {c.source.a1 for c in issue.affected_cells} == {"B2", "D2"}


def test_a_contingency_item_counted_in_the_total(boq_profile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", COLUMNS)
    table.row(item("1.1", "Bedarfsposition: Wasserhaltung"))
    table.row(item("1.2", "Bedarfsposition: Pumpe"), in_totals=False)  # marked: fine
    table.row(item("1.3", "Bedarfsposition mit GB: Verbau"))  # counted on purpose
    [issue] = run(DETECTOR, builder.build(), boq_profile).issues
    assert issue.rule_id == RULE_TYPE and issue.severity is Severity.MEDIUM
    assert "Bedarfsposition" in issue.title and "1.1" in issue.title


def test_a_quantity_in_the_text_that_differs(boq_profile) -> None:
    rows = [
        item("1.1", "Bordstein", "Menge: 25 m", quantity="20"),
        item("1.2", "Bordstein", "Menge: 25 m", quantity="25.000"),
        item("1.3", "Bordstein", "Anzahl: 3 St", quantity="20"),  # another dimension
    ]
    [issue] = result(boq_profile, rows).issues
    assert issue.rule_id == RULE_QUANTITY and issue.severity is Severity.LOW
    assert issue.title == "Item 1.1: Text states Menge: 25 m, quantity is 20"


def test_units_with_digits_and_compound_units_are_read_whole(boq_profile) -> None:
    rows = [
        item("1.1", "Estrich", "Menge: 30 m2", quantity="20", unit="m2"),
        item("1.2", "Geruest", "Menge: 30 m2 x Wo", quantity="20", unit="m2"),  # compound
        item("1.3", "Geruest", "Abrechnung je m2 x Woche", unit="m2"),
    ]
    [issue] = result(boq_profile, rows).issues
    assert issue.rule_id == RULE_QUANTITY and "1.1" in issue.title
