"""End to end: the built-in profiles against the detector catalogue, and the sample bills from
raw cells through normalization, the baseline plan and every deterministic detector."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.core.clock import FixedClock
from app.core.config import BUILTIN_PROFILE_DIR, Settings, ValidationLimits
from app.core.ids import SequentialIdFactory
from app.models.dataset import Dataset
from app.models.issue import EvidenceClass
from app.models.plan import PlannerKind
from app.models.run import RunStatus
from app.profiles.loader import ProfileCatalog
from app.validation.pipeline import PipelineOutcome, ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.profile_check import check_profiles
from app.validation.registry.registry import DetectorRegistry
from tests.unit.normalization.raw_builders import (
    ENGLISH_BOQ,
    GERMAN_LV,
    Value,
    normalize,
    sheet,
    workbook,
)

pytestmark = pytest.mark.integration

CATALOG = ProfileCatalog.from_directories([BUILTIN_PROFILE_DIR])
REGISTRY = DetectorRegistry.from_packages(
    [
        "app.validation.deterministic",
        "app.validation.domain",
        "app.validation.statistical",
        "app.validation.machine_learning",
        "app.validation.semantic",
    ]
)


def _run(rows: list[list[Value]]) -> tuple[Dataset, PipelineOutcome]:
    profile = CATALOG.get("boq")
    dataset = normalize(workbook(sheet(rows)), profile)
    plan = BaselinePlanner(REGISTRY).plan(dataset, profile)
    pipeline = ValidationPipeline(
        REGISTRY, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
    )
    outcome = pipeline.execute(
        dataset=dataset,
        document_id=dataset.document_id,
        profile=profile,
        plan=plan,
        plan_source=PlannerKind.BASELINE,
        run_id="run_e2e",
    )
    return dataset, outcome


def _row(dataset: Dataset, source_row: int) -> str:
    [row] = [r for r in dataset.tables[0].rows if r.source_row_number == source_row]
    return row.row_id


def test_the_builtin_profiles_match_the_detector_catalogue() -> None:
    # Against every detector the application registers: the boq profile sets defaults of
    # domain checks (domain.boq_bid_prices) and plans statistical ones (the price context
    # checks), so REGISTRY holds the same detectors as the application.
    registry = DetectorRegistry.from_packages(Settings().detector_packages)
    assert set(REGISTRY.ids()) == set(registry.ids())
    check_profiles(CATALOG.list(), registry)  # raises ProfileError listing every problem


@pytest.mark.parametrize("rows", [GERMAN_LV, ENGLISH_BOQ], ids=["german_lv", "english_boq"])
def test_the_sample_bills_are_clean(rows: list[list[Value]]) -> None:
    _, outcome = _run(rows)
    assert outcome.status is RunStatus.COMPLETED
    # The domain checks run here since the tender review: the German sample's one finding lists
    # its contingency position ("Bedarfsposition Wasserhaltung", step B2's
    # domain.boq_position_types), a Risk note for the bidder, not an error.
    assert [(i.detector_id, i.rule_id) for i in outcome.issues] == (
        [("domain.boq_position_types", "contingency_and_hourly")] if rows is GERMAN_LV else []
    )
    reports = {report.detector_id: report for report in outcome.reports}
    grand = reports["deterministic.grand_total"].coverage
    assert grand["totals_consistent"] == 2 and grand["tax_rows_consistent"] == 1
    line_total = reports["deterministic.line_total"].coverage
    assert line_total["rows_consistent"] == 4 and "rows_inconsistent" not in line_total


def test_the_german_sample_keeps_its_deliberate_facts() -> None:
    dataset, outcome = _run(GERMAN_LV)
    table = dataset.tables[0]
    bedarf = table.row(_row(dataset, 13))  # "Bedarfsposition Wasserhaltung"
    nur_ep = table.row(_row(dataset, 14))  # "Bodenaustausch ... nur EP"
    assert bedarf.classification.counts_toward_totals is None  # undecided, never guessed
    assert nur_ep.classification.counts_toward_totals is False
    reports = {report.detector_id: report for report in outcome.reports}
    subtotal = reports["deterministic.subtotal"]
    assert subtotal.coverage["totals_consistent"] == 3
    assert any("not counted in this total: 'LV' row 14" in note for note in subtotal.notes)


def test_defects_in_the_german_sample_are_found() -> None:
    rows = deepcopy(GERMAN_LV)
    [tax_row] = [row for row in rows if len(row) > 1 and row[1] == "zzgl. 19 % MwSt."]
    tax_row[5] = "3.036,20"  # digits swapped: 19 % of 16.122,10 is 3.063,20
    dataset, outcome = _run(rows)
    by_rule = {issue.rule_id: issue for issue in outcome.issues}
    assert set(by_rule) == {"tax_mismatch", "gross_total_mismatch", "contingency_and_hourly"}
    errors = [issue for issue in outcome.issues if issue.rule_id != "contingency_and_hourly"]
    assert all(
        issue.effective_evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION for issue in errors
    )
    assert by_rule["tax_mismatch"].expected_value == "3063.20"
    assert by_rule["gross_total_mismatch"].expected_value == "19158.30"
    bedarf = _row(dataset, 13)  # no error reads the undecided contingency row
    assert all(
        bedarf != issue.row_id and all(cell.row_id != bedarf for cell in issue.input_cells)
        for issue in errors
    )
