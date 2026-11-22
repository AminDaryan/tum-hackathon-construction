"""domain.boq_position_types: contingency positions and hourly work, listed once per bill."""

from __future__ import annotations

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, Severity
from app.validation.domain.boq.position_types import (
    CONTINGENCY_ITEMS,
    HOURLY_ITEMS,
    RULE,
    BoqPositionTypesDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    applicability,
    assert_well_formed,
    run,
    run_pipeline,
)

DETECTOR = BoqPositionTypesDetector
COLUMNS = [
    ("Pos.", "item_code"),
    ("Kurztext", "description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
    ("EP", "unit_price"),
    ("Positionsart", "item_type"),
]


def dataset(profile, rows, columns=COLUMNS, in_totals=None):
    builder = DatasetBuilder(profile)
    table = builder.table("LV", columns)
    for index, values in enumerate(rows):
        table.row(values, in_totals=(in_totals or {}).get(index, True))
    return builder.build()


def test_contingency_positions_and_hourly_work_from_the_item_type(boq_profile) -> None:
    rows = [
        ["01.0010", "Boden lösen", "100", "m3", "9.00", "Normalposition"],
        ["01.0020", "Bodenaustausch", "20", "m3", "30.00", "Bedarfsposition mit GB"],
        ["01.0030", "Wasserhaltung", "10", "d", "80.00", "Bedarfsposition ohne GB"],
        ["01.0040", "Facharbeiter", "20", "h", "60.00", "Bedarfsposition ohne GB"],
        ["01.0050", "Helfer", "20", "h", "45.00", "Stundenlohnarbeiten"],
        ["01.0060", "Container", "30", "Std", "4.00", "Normalposition"],  # hire, not labour
    ]
    found = run(DETECTOR, dataset(boq_profile, rows, in_totals={2: False, 3: False}), boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE
    assert (issue.severity, issue.evidence_class) == (Severity.LOW, EvidenceClass.SEMANTIC_WARNING)
    assert issue.title == (
        "3 contingency positions and 2 positions of hourly work to price at rates that cover cost"
    )
    assert issue.explanation.startswith(
        "3 contingency positions (1 with total, 2 without total); 1 count toward the totals, "
        "2 do not: 01.0020, 01.0030 and 01.0040. Hourly work in 2 positions: 01.0040 and "
        "01.0050."
    )
    assert {c.source.a1 for c in issue.affected_cells} == {"F3", "F4", "F5", "D5", "F6"}
    assert "§ 7 (1) Nr. 4 VOB/A" in (issue.suggested_action or "")
    [rule, *_] = issue.evidence
    assert rule.data["contingency_with_total"] == 1 and rule.data["contingency_without_total"] == 2
    assert (found.coverage[CONTINGENCY_ITEMS], found.coverage[HOURLY_ITEMS]) == (3, 2)
    assert_well_formed(found.issues)


def test_an_english_item_type_column_names_contingency_positions(boq_profile) -> None:
    """The totals rules read the English code "contingency" (type_contingency); the list reads
    it too. English wording in the texts is not read (the totals rules name none)."""
    columns = [
        ("Item", "item_code"),
        ("Description", "description"),
        ("Qty", "quantity"),
        ("Unit", "unit"),
        ("Rate", "unit_price"),
        ("Type", "item_type"),
    ]
    rows = [
        ["1.1", "Excavation", "100", "m3", "9.00", "Base"],
        ["1.2", "Dewatering", "10", "d", "80.00", "Contingency"],
        ["1.3", "Soil exchange, provisional item", "20", "m3", "30.00", "Base"],
        ["1.4", "Daywork labourer", "20", "h", "45.00", "Base"],
    ]
    rule = boq_profile.row_classification.match_totals({"category": ["Contingency"]})
    assert rule is not None and rule.rule_id == "type_contingency"  # the same code
    built = dataset(boq_profile, rows, columns=columns)
    [issue] = run(DETECTOR, built, boq_profile).issues
    assert issue.title.startswith("1 contingency position to price")
    assert {c.source.a1 for c in issue.affected_cells} == {"F3"}


def test_the_item_type_codes_of_spreadsheet_bills(boq_profile) -> None:
    rows = [
        ["01.0010", "Boden lösen", "100", "m3", "9.00", "N"],
        ["01.0020", "Bodenaustausch", "20", "m3", "30.00", "BmGB"],
        ["01.0030", "Wasserhaltung", "10", "d", "80.00", "BoGB"],
        ["01.0040", "Mehrtiefe", "10", "m3", "12.00", "B"],
        ["01.0050", "Pflaster", "10", "m2", "40.00", "Wahl"],
    ]
    [issue] = run(DETECTOR, dataset(boq_profile, rows), boq_profile).issues
    assert issue.title.startswith("3 contingency positions to price")
    assert "(1 with total, 1 without total, 1 not marked)" in issue.explanation


def test_contingency_positions_from_the_text(boq_profile) -> None:
    columns = COLUMNS[:5]
    rows = [
        ["01.0010", "Bodenaustausch, Bedarfsposition ohne GB", "20", "m3", "30.00"],
        ["01.0020", "Eventualposition: Wasserhaltung", "10", "d", "80.00"],
        ["01.0030", "Mehrtiefe, nur auf Anordnung des AG", "5", "m3", "12.00"],
        ["01.0040", "Leitung nach besonderer Anordnung umlegen", "5", "m", "50.00"],
        ["01.0050", "Boden nach Anordnung der Bauleitung lagern", "5", "m3", "5.00"],
    ]
    [issue] = run(DETECTOR, dataset(boq_profile, rows, columns), boq_profile).issues
    assert issue.title.startswith("4 contingency positions to price")
    assert "(1 without total, 3 not marked)" in issue.explanation
    assert "they count toward the totals" in issue.explanation
    assert "01.0050" not in issue.explanation
    assert {c.source.a1 for c in issue.affected_cells} == {"B2", "B3", "B4", "B5"}


def test_hourly_work_only_is_info(boq_profile) -> None:
    rows = [["01.0010", "Baufacharbeiter", "10", "h", "58.00", "Normalposition"]]
    [issue] = run(DETECTOR, dataset(boq_profile, rows), boq_profile).issues
    assert issue.severity is Severity.INFO
    assert issue.title == "1 position of hourly work to price at rates that cover cost"


def test_a_bill_without_them_has_no_finding(boq_profile) -> None:
    rows = [
        ["01.0010", "Boden lösen", "100", "m3", "9.00", "Normalposition"],
        ["01.0020", "Baustelleneinrichtung", "1", "psch", "900.00", "Pauschalposition"],
        ["01.0030", "Bagger mit Fahrer", "8", "d", "900.00", "Normalposition"],
    ]
    found = run(DETECTOR, dataset(boq_profile, rows), boq_profile)
    assert found.issues == []
    assert (found.coverage[CONTINGENCY_ITEMS], found.coverage[HOURLY_ITEMS]) == (0, 0)


def test_a_tender_without_prices_and_with_continuation_lines(boq_profile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table(
        "LV", [("Pos.", "item_code"), ("Kurztext", "description"), ("ME", "unit")]
    )
    table.row(["01.0010", "Stunden", "h"])
    table.row([None, "Vorarbeiter für Arbeiten", None], kind=RowKind.TEXT, belongs_to=0)
    table.row([None, "nur auf Anordnung des Auftraggebers", None], kind=RowKind.TEXT, belongs_to=0)
    [issue] = run(DETECTOR, builder.build(), boq_profile).issues
    assert issue.title.startswith("1 contingency position and 1 position of hourly work")
    assert issue.explanation.startswith(
        "1 contingency position (1 not marked); it counts toward the totals: 01.0010."
    )
    assert {c.source.a1 for c in issue.affected_cells} == {"B4", "C2"}


def test_a_note_attached_to_an_item_is_not_read(boq_profile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", [*COLUMNS[:2], ("ME", "unit"), ("Positionsart", "item_type")])
    table.row(["01.0010", "Pumpe vorhalten", "d", "Normalposition"])
    table.row(
        [None, "Bedarfspositionen nur auf Anordnung des AG", None, "Hinweis"],
        kind=RowKind.TEXT,
        belongs_to=0,
    )
    assert run(DETECTOR, builder.build(), boq_profile).issues == []


def test_not_applicable_without_texts_or_types(boq_profile) -> None:
    builder = DatasetBuilder(boq_profile)
    builder.table("LV", [("Pos.", "item_code"), ("Menge", "quantity")]).row(["01", "1"])
    assert not applicability(DETECTOR, builder.build(), boq_profile).applicable


def test_the_evidence_lists_every_position_beyond_the_highlighted_cells(boq_profile) -> None:
    """The highlighted cells stop at max_cells_per_issue; the evidence names every position,
    so a reader of the finding (and the benchmark's scorer) sees the whole list."""
    rows = [
        [f"01.{n:04d}", "Bodenaustausch", "20", "m3", "30.00", "Bedarfsposition ohne GB"]
        for n in range(1, 26)
    ]
    [issue] = run(DETECTOR, dataset(boq_profile, rows), boq_profile).issues
    assert len(issue.affected_cells) == 20
    listed = next(e for e in issue.evidence if e.label == "Contingency positions")
    assert len(listed.cells) == 25 and listed.data == {"positions": 25}
    assert {c.source.a1 for c in listed.cells} == {f"F{n}" for n in range(2, 27)}


def test_findings_pass_the_pipeline_evidence_policy(boq_profile) -> None:
    rows = [["01.0010", "Facharbeiter", "20", "h", "60.00", "Bedarfsposition ohne GB"]]
    outcome = run_pipeline(DETECTOR, dataset(boq_profile, rows, in_totals={0: False}), boq_profile)
    assert [i.rule_id for i in outcome.issues] == [RULE]
    assert_well_formed(outcome.issues)
