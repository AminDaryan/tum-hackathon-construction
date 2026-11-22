"""machine_learning.near_duplicates: nearly identical positions in one Titel."""

from __future__ import annotations

from decimal import Decimal

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass
from app.validation.machine_learning.near_duplicates import (
    PAIRS_DIFFERENT_NUMBERS,
    PAIRS_DIFFERENT_WORDS,
    PAIRS_SAME_TEXT,
    RULE_ID,
    NearDuplicatesDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    run,
)

COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]
WALL = "Stahlbeton Wand C25/30, Dicke 24 cm, liefern und einbauen"


def item(code, text, qty="10.00", unit="m3", price="200.00"):
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total), "EUR"]


def bill(profile, *titels):
    """One table; each argument is the item rows of one Titel."""
    builder = DatasetBuilder(profile)
    table = builder.table("LV", COLUMNS)
    for n, rows in enumerate(titels, 1):
        table.row([f"{n:02d}", f"Titel {n}", None, None, None, None, None], kind=RowKind.SECTION)
        for values in rows:
            table.row(values)
    return builder.build()


def test_a_near_copy_at_the_end_of_the_titel_is_a_signal_on_the_copy(boq_profile) -> None:
    rows = [
        item("01.0010", WALL),
        item("01.0020", "Schalung Wand, glatt, liefern und einbauen", "40.00", "m2", "35.00"),
        # Abbreviated, 5 % more quantity.
        item("01.0030", "StB Wand C25/30, Dicke 24 cm, liefern und einbauen", "10.50"),
    ]
    found = run(NearDuplicatesDetector, bill(boq_profile, rows), boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.evidence_class == EvidenceClass.SUSPECTED_ANOMALY  # a signal, never confirmed
    assert {cell.source.row_number for cell in issue.affected_cells} == {5}  # the copy's row
    [comparison] = issue.evidence[:1]
    assert {cell.source.row_number for cell in comparison.cells} == {3, 5}  # both rows shown
    assert issue.anomaly_score is not None and not issue.anomaly_score.calibrated
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.kind == "potential_double_count"
    assert (impact.amount, impact.currency) == (Decimal("2100.00"), "EUR")
    assert_well_formed(found.issues)


def test_positions_that_differ_in_a_number_or_a_word_are_distinct_work(boq_profile) -> None:
    rows = [
        item("01.0010", "Rohrleitung PE-HD DN 100, liefern und verlegen", "50.00", "m", "40.00"),
        item("01.0020", "Rohrleitung PE-HD DN 125, liefern und verlegen", "50.00", "m", "40.00"),
        item("01.0030", "Dämmung für Vorlauf, Kennzeichnung Kälte", "50.00", "m", "40.00"),
        item("01.0040", "Dämmung für Rücklauf, Kennzeichnung Kälte", "50.00", "m", "40.00"),
    ]
    found = run(NearDuplicatesDetector, bill(boq_profile, rows), boq_profile)
    assert found.issues == []
    assert found.coverage[PAIRS_DIFFERENT_NUMBERS] >= 1
    assert found.coverage[PAIRS_DIFFERENT_WORDS] >= 1


def test_exact_copies_and_other_titels_are_left_alone(boq_profile) -> None:
    first = [item("01.0010", WALL), item("01.0020", f" {WALL.upper()} ")]  # exact_duplicates' job
    second = [item("02.0010", "StB Wand C25/30, Dicke 24 cm, liefern und einbauen")]
    found = run(NearDuplicatesDetector, bill(boq_profile, first, second), boq_profile)
    assert found.issues == []
    assert found.coverage[PAIRS_SAME_TEXT] == 1
