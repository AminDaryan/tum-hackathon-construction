"""Problems (B4): findings of one mistake become one problem; separate mistakes stay apart."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.clock import FixedClock
from app.core.config import ValidationLimits
from app.core.ids import SequentialIdFactory
from app.models.dataset import RowKind
from app.models.plan import PlannerKind, PlanStep
from app.models.problem import AnomalyType, ProblemLinkKind
from app.models.profile import DomainProfile
from app.services.problems import build_problems
from app.validation.deterministic.line_total import LineTotalDetector
from app.validation.deterministic.subtotal import SubtotalDetector
from app.validation.pipeline import ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry
from app.validation.statistical.peer_price import PeerPriceDetector
from tests.support.builders import DatasetBuilder, number_cell
from tests.unit.validation.deterministic.references_fixtures import BOQ_COLUMNS


def eur(value: str) -> Any:
    return number_cell(value, currency="EUR")


def item(code: str, qty: str, price: str, total: str) -> list[Any]:
    return [code, "Position", qty, "m2", eur(price), eur(total)]


def test_a_wrong_line_total_and_the_subtotal_it_throws_off_are_one_problem(
    boq_profile: DomainProfile,
) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(["01", "Titel 01", None, None, None, None], kind=RowKind.SECTION, level=1, code="01")
    table.row(item("01.0010", "10", "10.00", "1000.00"))  # 100.00 written as 1000.00
    table.row(item("01.0020", "5", "20.00", "100.00"))
    table.row([None, "Summe 01", None, None, None, eur("200.00")], kind=RowKind.SUBTOTAL, code="01")
    table.row(["02", "Titel 02", None, None, None, None], kind=RowKind.SECTION, level=1, code="02")
    table.row(item("02.0010", "4", "25.00", "90.00"))  # 100.00 written as 90.00
    table.row([None, "Summe 02", None, None, None, eur("90.00")], kind=RowKind.SUBTOTAL, code="02")
    dataset = builder.build()
    registry = DetectorRegistry([LineTotalDetector, SubtotalDetector])
    outcome = ValidationPipeline(
        registry, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
    ).execute(
        dataset=dataset,
        document_id=dataset.document_id,
        profile=boq_profile,
        plan=BaselinePlanner(registry).plan(dataset, boq_profile),
        plan_source=PlannerKind.BASELINE,
        run_id="run_test",
    )
    issues = outcome.issues
    assert sorted(i.detector_id for i in issues) == [
        "deterministic.line_total",
        "deterministic.line_total",
        "deterministic.subtotal",
    ]
    first, second = build_problems(issues)
    # The 900.00 slip and the subtotal it throws off: one problem, the line total shown first.
    assert len(first.issue_ids) == 2
    primary = next(i for i in issues if i.issue_id == first.primary_issue_id)
    assert primary.detector_id == "deterministic.line_total"
    assert [link.kind for link in first.links] == [ProblemLinkKind.CARRIED_DIFFERENCE]
    assert (first.money_at_stake, first.currency) == (Decimal("900.00"), "EUR")
    assert first.corrected_value == Decimal("100.00")
    assert first.anomaly_type is AnomalyType.LOGICAL
    # Titel 02's subtotal agrees with its wrong line total: a problem of its own.
    assert len(second.issue_ids) == 1 and second.money_at_stake == Decimal("-10.00")


def test_a_comparison_estimate_is_not_money_at_stake(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for n, price in enumerate(["78.00", "80.00", "82.00", "85.00"], 1):
        table.row(
            [
                "1." + str(n),
                "Facharbeiter Stundenlohn Tiefbau",
                "10",
                "h",
                eur(price),
                eur(str(Decimal(price) * 10)),
            ]
        )
    # 800.00 for 80.00 a hundred times: a large estimate, but only a comparison.
    table.row(
        ["1.5", "Facharbeiter Stundenlohn Tiefbau", "100", "h", eur("800.00"), eur("80000.00")]
    )
    table.row(item("2.1", "10", "10.00", "105.00"))  # an exact difference of 5.00
    dataset = builder.build()
    registry = DetectorRegistry([LineTotalDetector, PeerPriceDetector])
    plan = (
        BaselinePlanner(registry)
        .plan(dataset, boq_profile)
        .model_copy(update={"steps": [PlanStep(detector_id=d) for d in registry.ids()]})
    )
    issues = (
        ValidationPipeline(
            registry, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
        )
        .execute(
            dataset=dataset,
            document_id=dataset.document_id,
            profile=boq_profile,
            plan=plan,
            plan_source=PlannerKind.BASELINE,
            run_id="run_test",
        )
        .issues
    )
    first, second = build_problems(issues)
    assert (first.money_at_stake, first.anomaly_type) == (Decimal("5.00"), AnomalyType.LOGICAL)
    assert second.anomaly_type is AnomalyType.PRICE
    assert second.money_at_stake is None and second.currency is None
    assert second.reference_deviation == Decimal("71900.00")  # 100 × (800.00 − median 81.00)
    assert second.corrected_value is None
