"""Run limits of the validation pipeline, driven by a fake monotonic clock.

Pinned here: the per-detector time limit (checked by ``ValidationContext.rows`` every 256 rows
and by ``checkpoint()``), the run time limit (later steps skipped with a reason), the
content-digest tamper check, sanitized error texts, the run status of a run whose only detector
stopped (ADR 0006) and the per-detector and per-run finding caps.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

import pytest
from pydantic import Field

from app.core.clock import FixedClock
from app.core.config import ValidationLimits
from app.core.errors import NotFoundError, WorkbenchError
from app.core.ids import SequentialIdFactory
from app.models.dataset import Dataset, Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.models.profile import DomainProfile
from app.models.run import DetectorExecutionStatus, RunStatus
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.pipeline import PipelineOutcome, ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder

RUN_LIMIT_WARNING = "At least one check stopped at a run limit; its findings are incomplete."
TAMPER_ERROR = (
    "Detector returned issues that were not created by its issue factory for this run "
    "(or were modified afterwards)."
)

Behaviour = Callable[[DetectorSpec, ValidationContext], DetectorResult]


class FakeMonotonic:
    """Monotonic clock that only moves when a test (or a test detector) advances it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StrictConfig(DetectorConfig):
    threshold: int = Field(default=1, ge=0)  # profile-controlled


def _spec(detector_id: str) -> DetectorSpec:
    return DetectorSpec(
        detector_id=detector_id,
        name=detector_id,
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description="test detector",
        applicability="always",
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.CONSTRAINT,),
    )


def _detector(
    detector_id: str,
    behaviour: Behaviour,
    *,
    model: type[DetectorConfig] = DetectorConfig,
) -> type[Detector]:
    probe_spec = _spec(detector_id)

    class Probe(Detector[DetectorConfig]):
        spec: ClassVar[DetectorSpec] = probe_spec
        config_model = model

        def validate(self, context: ValidationContext, config: DetectorConfig) -> DetectorResult:
            return behaviour(self.spec, context)

    return Probe


def _flag(
    spec: DetectorSpec,
    context: ValidationContext,
    table: Table,
    row: Row | None,
    *,
    subject: str | None = None,
) -> ValidationIssue:
    return context.issues.create(
        spec,
        rule_id="probe",
        category=IssueCategory.CONSTRAINT,
        severity=Severity.LOW,
        evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
        title="Probe",
        explanation="Probe finding.",
        table=table,
        row=row,
        subject=subject,
        evidence=[EvidenceItem(kind=EvidenceKind.NOTE, label="n", detail="d", data={"k": "v"})],
    )


def _pipeline(
    detectors: list[type[Detector]], clock: FakeMonotonic, **limits: float
) -> ValidationPipeline:
    return ValidationPipeline(
        DetectorRegistry(detectors),
        ids=SequentialIdFactory(),
        clock=FixedClock(),
        limits=ValidationLimits(**limits),
        monotonic=clock,
    )


def _run(
    pipeline: ValidationPipeline,
    dataset: Dataset,
    profile: DomainProfile,
    detector_ids: list[str],
) -> PipelineOutcome:
    plan = ValidationPlan(
        planner=PlannerKind.USER, steps=[PlanStep(detector_id=d) for d in detector_ids]
    )
    return pipeline.execute(
        dataset=dataset,
        document_id="doc",
        profile=profile,
        plan=plan,
        plan_source=PlannerKind.USER,
        run_id="run_1",
    )


@pytest.fixture
def clock() -> FakeMonotonic:
    return FakeMonotonic()


@pytest.fixture
def dataset(boq_profile) -> Dataset:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", [("Item", "item_code"), ("Qty", "quantity")])
    for index in range(300):
        table.row([f"01.{index + 1:04d}", str(index + 1)])
    return builder.build()


def _busy(clock: FakeMonotonic, seconds: float, ran: list[str]) -> Behaviour:
    def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
        ran.append(spec.detector_id)
        clock.advance(seconds)
        return DetectorResult(coverage={"rows_checked": 1})

    return behaviour


def _checkpoint_loop(clock: FakeMonotonic, iterations: list[int]) -> Behaviour:
    """Heavy work outside ``rows()``: one finding, then a long loop that only checkpoints."""

    def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
        result = DetectorResult()
        table = context.tables()[0]
        # A confirmed finding needs a cell or a row (the evidence rule).
        result.add(_flag(spec, context, table, table.rows[0], subject="before_loop"))
        for index in range(1_000_000):
            clock.advance(0.5)
            iterations.append(index)
            context.checkpoint()
        return result

    return behaviour


class TestDetectorTimeLimit:
    def test_row_loop_stops_at_the_next_256_row_checkpoint_and_keeps_its_findings(
        self, clock, dataset, boq_profile
    ) -> None:
        seen: list[str] = []

        def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
            result = DetectorResult()
            table = context.tables()[0]
            for row in context.rows(table):
                if len(seen) % 50 == 0:
                    result.add(_flag(spec, context, table, row))
                seen.append(row.row_id)
                clock.advance(1.0)
            return result

        outcome = _run(
            _pipeline([_detector("test.slow_rows", behaviour)], clock, max_detector_seconds=10),
            dataset,
            boq_profile,
            ["test.slow_rows"],
        )
        [report] = outcome.reports
        rows = dataset.tables[0].rows
        # The limit passed after row 11, but rows() checks the deadline only every 256 rows.
        assert seen == [r.row_id for r in rows[:256]]
        assert report.status is DetectorExecutionStatus.STOPPED
        assert report.limit_reached == "time"
        assert report.issues_found == 6
        assert [i.row_id for i in outcome.issues] == [rows[i].row_id for i in range(0, 256, 50)]
        assert report.notes == [
            "Stopped after the time limit of 10 s. Rows after that point were not checked."
        ]
        assert RUN_LIMIT_WARNING in outcome.warnings

    def test_checkpoint_stops_a_loop_that_never_iterates_rows(
        self, clock, dataset, boq_profile
    ) -> None:
        iterations: list[int] = []
        outcome = _run(
            _pipeline(
                [_detector("test.loop", _checkpoint_loop(clock, iterations))],
                clock,
                max_detector_seconds=10,
            ),
            dataset,
            boq_profile,
            ["test.loop"],
        )
        [report] = outcome.reports
        assert len(iterations) == 21  # 21 × 0.5 s = 10.5 s is the first value past 10 s
        assert report.status is DetectorExecutionStatus.STOPPED
        assert report.limit_reached == "time"
        assert report.issues_found == 1
        assert [i.title for i in outcome.issues] == ["Probe"]

    def test_a_run_whose_only_detector_stopped_is_partial_not_failed(
        self, clock, dataset, boq_profile
    ) -> None:
        # ADR 0006: the stopped detector ran and its findings are kept.
        outcome = _run(
            _pipeline(
                [_detector("test.loop", _checkpoint_loop(clock, []))],
                clock,
                max_detector_seconds=10,
            ),
            dataset,
            boq_profile,
            ["test.loop"],
        )
        assert [r.status for r in outcome.reports] == [DetectorExecutionStatus.STOPPED]
        assert outcome.status is RunStatus.COMPLETED_WITH_ERRORS
        assert len(outcome.issues) == 1

    def test_each_detector_gets_a_fresh_deadline(self, clock, dataset, boq_profile) -> None:
        def quick(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
            result = DetectorResult()
            for _row in context.rows(context.tables()[0]):
                result.count("rows_checked")
            return result

        outcome = _run(
            _pipeline(
                [
                    _detector("test.loop", _checkpoint_loop(clock, [])),
                    _detector("test.quick", quick),
                ],
                clock,
                max_detector_seconds=10,
            ),
            dataset,
            boq_profile,
            ["test.loop", "test.quick"],
        )
        loop, after = outcome.reports
        assert loop.status is DetectorExecutionStatus.STOPPED
        assert after.status is DetectorExecutionStatus.COMPLETED
        assert after.limit_reached is None
        assert after.coverage == {"rows_checked": 300}


class TestRunTimeLimit:
    @pytest.mark.parametrize(("seconds", "third_runs"), [(7.5, True), (8.0, False)])
    def test_steps_after_the_run_limit_are_skipped_with_a_reason(
        self, clock, dataset, boq_profile, seconds, third_runs
    ) -> None:
        ran: list[str] = []
        pipeline = _pipeline(
            [
                _detector("test.first", _busy(clock, seconds, ran)),
                _detector("test.second", _busy(clock, seconds, ran)),
                _detector("test.third", _busy(clock, 1, ran)),
            ],
            clock,
            max_detector_seconds=10,
            max_run_seconds=15,
        )
        outcome = _run(pipeline, dataset, boq_profile, ["test.first", "test.second", "test.third"])
        first, second, third = outcome.reports
        assert first.status is second.status is DetectorExecutionStatus.COMPLETED
        if third_runs:  # exactly at the limit (15 s) is not past it
            assert ran == ["test.first", "test.second", "test.third"]
            assert third.status is DetectorExecutionStatus.COMPLETED
            assert RUN_LIMIT_WARNING not in outcome.warnings
            return
        assert ran == ["test.first", "test.second"]
        assert third.status is DetectorExecutionStatus.SKIPPED
        assert third.skipped_reasons == [
            "The run reached its time limit of 15 s before this check."
        ]
        assert third.limit_reached == "time"
        assert third.issues_found == 0
        # ADR 0006: skipped steps (here: run time limit) do not change the status; the
        # warning tells the user the results are incomplete.
        assert outcome.status is RunStatus.COMPLETED
        assert RUN_LIMIT_WARNING in outcome.warnings

    def test_invalid_profile_step_after_the_run_limit_is_still_reported(
        self, clock, dataset, boq_profile
    ) -> None:
        detectors = [
            _detector("test.a_slow", _busy(clock, 20, [])),
            _detector("test.b_strict", _busy(clock, 0, []), model=StrictConfig),
        ]
        profile = boq_profile.evolve(detector_defaults={"test.b_strict": {"threshold": -1}})
        pipeline = _pipeline(detectors, clock, max_detector_seconds=30, max_run_seconds=15)
        registry = DetectorRegistry(detectors)
        outcome = pipeline.execute(
            dataset=dataset,
            document_id="doc",
            profile=profile,
            plan=BaselinePlanner(registry).plan(dataset, profile),
            plan_source=PlannerKind.BASELINE,
            run_id="run_1",
        )
        reports = {r.detector_id: r for r in outcome.reports}
        assert reports["test.a_slow"].status is DetectorExecutionStatus.COMPLETED
        assert reports["test.b_strict"].status is DetectorExecutionStatus.FAILED
        assert "threshold" in reports["test.b_strict"].error


def _append_evidence(issue: ValidationIssue, context: ValidationContext, table: Table) -> None:
    issue.evidence.append(EvidenceItem(kind=EvidenceKind.NOTE, label="added", detail="later"))


def _edit_evidence_data(issue: ValidationIssue, context: ValidationContext, table: Table) -> None:
    issue.evidence[0].data["k"] = "changed"


def _append_affected_cell(issue: ValidationIssue, context: ValidationContext, table: Table) -> None:
    issue.affected_cells.append(context.cell_ref(table, table.rows[2], "quantity"))


class TestTamperCheck:
    @pytest.mark.parametrize("edit", [_append_evidence, _edit_evidence_data, _append_affected_cell])
    def test_an_issue_edited_in_place_fails_its_detector(
        self, clock, dataset, boq_profile, edit
    ) -> None:
        def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
            table = context.tables()[0]
            untouched = _flag(spec, context, table, table.rows[0])
            edited = _flag(spec, context, table, table.rows[1])
            edit(edited, context, table)  # same object, so the identity check alone passes
            return DetectorResult(issues=[untouched, edited])

        outcome = _run(
            _pipeline([_detector("test.edit", behaviour)], clock),
            dataset,
            boq_profile,
            ["test.edit"],
        )
        [report] = outcome.reports
        assert report.status is DetectorExecutionStatus.FAILED
        assert report.error == TAMPER_ERROR
        assert report.issues_found == 0
        assert outcome.issues == []  # the unmodified finding is not stored either

    def test_unedited_issues_pass_the_tamper_check(self, clock, dataset, boq_profile) -> None:
        def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
            table = context.tables()[0]
            return DetectorResult(
                issues=[_flag(spec, context, table, row) for row in table.rows[:2]]
            )

        outcome = _run(
            _pipeline([_detector("test.clean", behaviour)], clock),
            dataset,
            boq_profile,
            ["test.clean"],
        )
        assert outcome.reports[0].status is DetectorExecutionStatus.COMPLETED
        assert len(outcome.issues) == 2

    def test_a_stopped_detector_keeps_only_its_unmodified_findings(
        self, clock, dataset, boq_profile
    ) -> None:
        def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
            table = context.tables()[0]
            edited = _flag(spec, context, table, table.rows[0])
            kept = _flag(spec, context, table, table.rows[1])
            _append_evidence(edited, context, table)
            assert kept is not edited
            while True:
                clock.advance(1)
                context.checkpoint()

        outcome = _run(
            _pipeline([_detector("test.edit_then_stop", behaviour)], clock, max_detector_seconds=5),
            dataset,
            boq_profile,
            ["test.edit_then_stop"],
        )
        [report] = outcome.reports
        assert report.status is DetectorExecutionStatus.STOPPED
        assert report.issues_found == 1
        assert [i.row_id for i in outcome.issues] == [dataset.tables[0].rows[1].row_id]


def _raises(exc: Exception) -> Behaviour:
    def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
        raise exc

    return behaviour


class TestSanitizedErrors:
    def test_workbench_messages_are_kept_other_exception_text_is_not(
        self, clock, dataset, boq_profile, caplog
    ) -> None:
        leak = ValueError("invalid literal for int() with base 10: 'Geheimer Text 12,50'")
        detectors = [
            _detector(
                "test.readable",
                _raises(NotFoundError("Column 'Menge' is not mapped in table 'LV'.")),
            ),
            _detector("test.leaky", _raises(leak)),
        ]
        with caplog.at_level(logging.ERROR, logger="app.validation.pipeline"):
            outcome = _run(
                _pipeline(detectors, clock),
                dataset,
                boq_profile,
                ["test.readable", "test.leaky"],
            )
        readable, leaky = outcome.reports
        assert readable.status is leaky.status is DetectorExecutionStatus.FAILED
        assert (
            readable.error == "Column 'Menge' is not mapped in table 'LV'. (reference err_000001)"
        )
        assert leaky.error == "ValueError (reference err_000002; details are in the server log)"
        assert "Geheimer" not in leaky.error
        # The full exception goes to the server log under the same reference.
        [record] = [r for r in caplog.records if "err_000002" in r.getMessage()]
        assert record.exc_info is not None and record.exc_info[1] is leak
        assert outcome.status is RunStatus.FAILED  # every detector that executed failed

    def test_a_long_workbench_message_keeps_its_log_reference(
        self, clock, dataset, boq_profile
    ) -> None:
        message = "The profile parameters for this check cannot be applied. " * 12
        outcome = _run(
            _pipeline([_detector("test.long", _raises(WorkbenchError(message)))], clock),
            dataset,
            boq_profile,
            ["test.long"],
        )
        error = outcome.reports[0].error
        assert len(error) <= 500
        assert error.endswith("(reference err_000001)")


def _flag_rows(count: int) -> Behaviour:
    def behaviour(spec: DetectorSpec, context: ValidationContext) -> DetectorResult:
        result = DetectorResult()
        table = context.tables()[0]
        for row in list(context.rows(table))[:count]:
            result.add(_flag(spec, context, table, row))
        return result

    return behaviour


class TestIssueCaps:
    def test_per_detector_cap_stops_only_that_detector(self, clock, dataset, boq_profile) -> None:
        pipeline = _pipeline(
            [_detector("test.many", _flag_rows(10)), _detector("test.after", _flag_rows(2))],
            clock,
            max_issues_per_detector=3,
            max_issues_per_run=100,
        )
        outcome = _run(pipeline, dataset, boq_profile, ["test.many", "test.after"])
        many, after = outcome.reports
        rows = dataset.tables[0].rows
        assert many.status is DetectorExecutionStatus.COMPLETED
        assert many.limit_reached == "issues"
        assert (many.issues_found, many.issues_dropped) == (3, 0)
        assert many.notes == [
            "Stopped at the limit of 3 findings for this check. Further findings were not computed."
        ]
        assert after.status is DetectorExecutionStatus.COMPLETED
        assert after.limit_reached is None and after.issues_found == 2
        by_detector = [(i.detector_id, i.row_id) for i in outcome.issues]
        assert by_detector == [("test.many", r.row_id) for r in rows[:3]] + [
            ("test.after", r.row_id) for r in rows[:2]
        ]
        # Caps are not a failure: only a time stop makes the run partial (ADR 0006).
        assert outcome.status is RunStatus.COMPLETED
        assert RUN_LIMIT_WARNING in outcome.warnings

    def test_per_run_cap_counts_across_detectors(self, clock, dataset, boq_profile) -> None:
        pipeline = _pipeline(
            [
                _detector("test.first", _flag_rows(3)),
                _detector("test.second", _flag_rows(10)),
                _detector("test.third", _flag_rows(1)),
            ],
            clock,
            max_issues_per_detector=4,
            max_issues_per_run=6,
        )
        outcome = _run(pipeline, dataset, boq_profile, ["test.first", "test.second", "test.third"])
        first, second, third = outcome.reports
        assert (first.issues_found, first.limit_reached) == (3, None)
        assert (second.issues_found, second.limit_reached) == (3, "issues")
        assert second.notes == [
            "Stopped at the limit of 6 findings for the whole run. Further findings were not "
            "computed."
        ]
        assert (third.issues_found, third.limit_reached) == (0, "issues")
        assert all(r.status is DetectorExecutionStatus.COMPLETED for r in outcome.reports)
        assert [i.detector_id for i in outcome.issues] == ["test.first"] * 3 + ["test.second"] * 3
        assert RUN_LIMIT_WARNING in outcome.warnings
