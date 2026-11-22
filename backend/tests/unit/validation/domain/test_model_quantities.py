"""domain.model_quantities: the bill's quantities against an attached model's takeoff."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from app.models.dataset import RowKind
from app.models.finding_category import FindingCategory
from app.models.issue import EvidenceClass, Severity
from app.models.model_takeoff import ModelTakeoff, PositionTakeoff
from app.validation.domain.model_quantities import (
    ROWS_COMPARED,
    RULE_MISMATCH,
    RULE_MISSING,
    RULE_RENUMBERED,
    RULE_TWICE,
    RULE_UNIT,
    ModelQuantitiesDetector,
)
from tests.support.builders import DatasetBuilder, make_context
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_well_formed,
    boq_dataset,
    run,
)

DETECTOR = ModelQuantitiesDetector
COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]


def position(code, name=None, **quantities):
    count = quantities.pop("count", 1)
    values = {k: Decimal(str(v)) for k, v in quantities.items()}
    return PositionTakeoff(
        item_code=code,
        elements=count,
        global_ids=tuple(f"g{code}/{i}" for i in range(count)),
        entity_types=("IFCPIPESEGMENT",),
        names=(),
        quantities={**values, "count": Decimal(count)},
        reference_name=name,
    )


def takeoff(*positions):
    return ModelTakeoff(
        sha256="0" * 64,
        filename="design.ifc",
        schema="IFC4X3_ADD2",
        project=None,
        elements=sum(p.elements for p in positions),
        unlinked_elements=0,
        positions={p.item_code: p for p in positions},
    )


def result(profile, model, rows):
    dataset = boq_dataset(profile, [[*r, "EUR"] for r in rows], columns=COLUMNS)
    context = dataclasses.replace(make_context(dataset, profile), model=model)
    return run(DETECTOR, dataset, profile, context=context)


def test_a_quantity_the_model_does_not_support_is_found_with_the_money_at_stake(
    boq_profile,
) -> None:
    model = takeoff(position("1.1", length=243.02), position("1.2", count=4))
    found = result(
        boq_profile,
        model,
        [
            ["01.1", "Rohr DN 250", "25", "m", "100.00", "2500.00"],  # 3.2.9 style numbers match
            ["1.2", "Bogen 90°", "3", "St", "50.00", "150.00"],  # pieces: any difference
        ],
    )
    pipe, bend = sorted(found.issues, key=lambda i: i.title)
    assert {pipe.rule_id, bend.rule_id} == {RULE_MISMATCH}
    assert pipe.title == "Bill says 25 m, model gives 243.02 m: 1.1"
    assert (pipe.severity, pipe.evidence_class) == (
        Severity.HIGH,
        EvidenceClass.CONFIRMED_RULE_VIOLATION,
    )
    assert pipe.finding_category is FindingCategory.INCONSISTENCY
    assert pipe.estimated_financial_impact is not None
    assert pipe.estimated_financial_impact.amount == Decimal("-21802.00")  # (25 − 243.02) × 100
    assert (bend.severity, bend.observed_value, bend.expected_value) == (Severity.MEDIUM, "3", "4")
    assert found.coverage[ROWS_COMPARED] == 2
    assert_well_formed(found.issues)


def test_rounding_within_the_tolerance_is_not_reported(boq_profile) -> None:
    model = takeoff(position("1.1", volume=1094.7), position("1.2", area=0.5))
    rows = [
        ["1.1", "Boden lösen", "1140", "m3", "10.00", "11400.00"],  # 4.1 % above the model
        ["1.2", "Planum", "0.5", "m2", "3.00", "1.50"],
        ["1.3", "Baustelle einrichten", "1", "psch", "900.00", "900.00"],  # not in the model
    ]
    assert result(boq_profile, model, rows).issues == []


def test_a_unit_the_model_does_not_measure_in(boq_profile) -> None:
    found = result(
        boq_profile,
        takeoff(position("1.1", area=52)),
        [["1.1", "Kabelortung", "52", "m", "2.00", "104.00"]],
    )
    [issue] = found.issues
    assert issue.rule_id == RULE_UNIT
    assert issue.title == "Bill measures 1.1 in m, the model in m²"


def test_moved_missing_and_doubled_work(boq_profile) -> None:
    lawn = "Rasen ansäen Parkplatzrasen RSM5.1 25g/m2"
    planum = "Planum Leitungsgraben, Abweichung +/-2cm EV2 45MPa"
    model = takeoff(
        position("3.4.2", lawn, area=48),
        position("3.2.14", planum, area=215),
        position("3.2.30", "Kies einbauen", volume=12),
    )
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", COLUMNS)
    section = [None, None, None, None, None]
    table.row(["03.02", "Erdarbeiten", *section], kind=RowKind.SECTION, level=1)
    table.row(["03.02.0014", planum, "220", "m2", "2.00", "440.00", "EUR"])
    table.row(["03.02.0029", planum, "220", "m2", "2.00", "440.00", "EUR"])
    table.row(["06.01", "Dokumentation", *section], kind=RowKind.SECTION, level=1)
    table.row(["06.01.0010", lawn, "50", "m2", "1.00", "50.00", "EUR"])
    # The planum again in another section, which the model does not link: not priced twice.
    table.row(["06.01.0011", planum, "30", "m2", "2.00", "60.00", "EUR"])
    dataset = builder.build()
    context = dataclasses.replace(make_context(dataset, boq_profile), model=model)
    found = run(DETECTOR, dataset, boq_profile, context=context)
    by_rule = {i.rule_id: i for i in found.issues}
    assert set(by_rule) == {RULE_TWICE, RULE_RENUMBERED, RULE_MISSING}
    twice = by_rule[RULE_TWICE]
    assert twice.title == "03.02.0029 prices the model's 3.2.14 a second time"
    assert twice.estimated_financial_impact is not None
    assert twice.estimated_financial_impact.amount == Decimal("440.00")
    assert by_rule[RULE_RENUMBERED].title == "Model's 3.4.2 is priced as 06.01.0010"
    missing = by_rule[RULE_MISSING]  # reported on its section
    assert missing.finding_category is FindingCategory.OMISSION
    assert "Section 03.02 has no position 3.2.30." in missing.explanation
    assert_well_formed(found.issues)


def test_without_a_model_the_check_does_not_apply(boq_profile) -> None:
    dataset = boq_dataset(boq_profile, [["1.1", "Rohr", "25", "m", "1.00", "25.00"]])
    verdict = applicability(DETECTOR, dataset, boq_profile)
    assert not verdict.applicable
    assert verdict.reasons == ("No model (IFC) is attached to this bill.",)
