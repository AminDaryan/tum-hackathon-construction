"""semantic.section_fit: positions much closer to another Titel than to their own."""

from __future__ import annotations

from decimal import Decimal

from app.models.dataset import RowKind
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory
from app.validation.semantic.section_fit import RULE_ID, SectionFitDetector
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    run,
)

EARTH = "Baugrube ausheben, Boden der Klasse {} laden und abfahren, Tiefe bis {} m"
WALL = "Mauerwerk aus Kalksandstein KS {}, Wanddicke {} cm, liefern und mauern"


def item(code, text, unit="m3", qty="10", price="40.00"):
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total)]


def bill(profile, *titels):
    """One table; each argument is (Titel name, item rows)."""
    builder = DatasetBuilder(profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for n, (name, rows) in enumerate(titels, 1):
        table.row([f"{n:02d}", name, None, None, None, None], kind=RowKind.SECTION, code=f"{n:02d}")
        for values in rows:
            table.row(values)
    return builder.build()


EARTHWORKS = [
    item(f"01.{n}0", EARTH.format(c, d))
    for n, (c, d) in enumerate([(3, 1.5), (3, 2.0), (4, 1.5), (4, 2.0)], 1)
]
MASONRY = [
    item(f"02.{n}0", WALL.format(s, d), "m2")
    for n, (s, d) in enumerate([(12, 11.5), (12, 17.5), (20, 24), (20, 30)], 1)
]


def test_an_excavation_inside_the_masonry_titel_is_reported(boq_profile) -> None:
    moved = item("02.50", EARTH.format(5, 2.5))
    dataset = bill(boq_profile, ("Erdarbeiten", EARTHWORKS), ("Mauerarbeiten", [*MASONRY, moved]))
    found = run(SectionFitDetector, dataset, boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.issue_category == IssueCategory.SEMANTIC
    assert issue.evidence_class == EvidenceClass.SEMANTIC_WARNING
    assert "section 01 'Erdarbeiten'" in issue.title and "02 'Mauerarbeiten'" in issue.title
    assert issue.affected_cells[0].source.row_number == 12
    closer, own = issue.evidence
    assert closer.kind == own.kind == EvidenceKind.COMPARISON
    assert closer.detail.startswith("01.") and len(closer.cells) == 3  # the 3 closest shown
    assert own.detail.startswith("02.")
    assert issue.anomaly_score is not None and issue.anomaly_score.value >= 0.5
    assert issue.estimated_financial_impact is None
    assert_well_formed(found.issues)


PANEL = "Revisionsklappe {0}x{0} mm in Gipskartonbekleidung einbauen"
CEILING = "Abhangdecke aus Gipskarton, Abhaengehoehe {} cm, {}-lagig beplankt"


def test_a_position_with_a_close_match_in_its_own_titel_is_not_reported(boq_profile) -> None:
    """The walls Titel holds three access panels, the ceilings Titel two: each ceiling panel
    is closer to the walls, but its twin at home shows it belongs where it is."""
    walls = [
        *MASONRY,
        *(item(f"02.{n}0", PANEL.format(s), "St") for n, s in [(5, 200), (6, 300), (7, 600)]),
    ]
    ceilings = [
        *(
            item(f"01.{n}0", CEILING.format(h, k), "m2")
            for n, (h, k) in enumerate([(10, 1), (20, 1), (10, 2), (20, 2)], 1)
        ),
        item("01.50", PANEL.format(300), "St"),
        item("01.60", PANEL.format(400), "St"),
    ]
    dataset = bill(boq_profile, ("Decken", ceilings), ("Wände", walls))
    assert run(SectionFitDetector, dataset, boq_profile).issues == []
    # Without that rule the panel with an identical one in the walls Titel would be reported.
    lax = run(SectionFitDetector, dataset, boq_profile, {"max_own_similarity": 1.0})
    [issue] = lax.issues
    assert issue.affected_cells[0].source.row_number == 7
