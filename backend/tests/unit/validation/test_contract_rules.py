"""Contract rules from the maintainability triage: issue subjects and fingerprint uniqueness,
cell conditions, unit and currency accessors, financial impact currency, review versions,
profile checks, baseline isolation of invalid profile parameters and the run status rule."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import Field, ValidationError

from app.core.clock import FixedClock
from app.core.config import ValidationLimits
from app.core.errors import PlanValidationError, ProfileError, ReviewTransitionError
from app.core.ids import SequentialIdFactory
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    FinancialImpact,
    IssueCategory,
    ReviewStatus,
    Severity,
    ValidationIssue,
)
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.models.run import DetectorExecutionStatus, DetectorRunReport, RunStatus
from app.models.values import ValueMarker
from app.validation.contracts.conditions import (
    CONDITION_OWNERS,
    CellCondition,
    Coverage,
    cell_condition,
    skip_key,
)
from app.validation.contracts.detector import (
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.contracts.issue_factory import (
    CONFIRMED_WITHOUT_PLACE,
    NO_EVIDENCE,
    IssuePolicyError,
    evidence_rule_problem,
    money_impact,
)
from app.validation.contracts.limits import IssueLimitReached
from app.validation.pipeline import ValidationPipeline, run_status
from app.validation.planner import BaselinePlanner
from app.validation.profile_check import check_profiles, profile_problems
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import (
    TEST_LIMITS,
    DatasetBuilder,
    ambiguous_cell,
    empty_cell,
    error_cell,
    failed_number_cell,
    make_context,
    marker_cell,
    number_cell,
    text_cell,
    unavailable_formula_cell,
)

COLUMNS = [
    ("Item", "item_code"),
    ("Description", "description"),
    ("Qty", "quantity"),
    ("Unit", "unit"),
    ("Rate", "unit_price"),
    ("Amount", "line_total"),
]


def _spec(detector_id: str = "test.probe", **overrides) -> DetectorSpec:
    data = dict(
        detector_id=detector_id,
        name=detector_id,
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description="test detector",
        applicability="always",
        evidence_classes=(
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
            EvidenceClass.EXTRACTION_UNCERTAINTY,
        ),
        issue_categories=(IssueCategory.CONSTRAINT, IssueCategory.MISSING_VALUE),
    )
    data.update(overrides)
    return DetectorSpec(**data)


PROBE = _spec()
EVIDENCE = [EvidenceItem(kind=EvidenceKind.NOTE, label="Probe", detail="Probe evidence.")]


@pytest.fixture
def dataset(boq_profile):
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", COLUMNS)
    table.row(["01.0010", "Aushub", "10", "m3", "12.50", "125.00"])
    table.row(["01.0020", "Beton", "2", "100 St", "3.00", "6.00"])
    return builder.build()


def _create(context, table, row=None, cells=(), **kwargs):
    return context.issues.create(
        PROBE,
        rule_id=kwargs.pop("rule_id", "probe"),
        category=kwargs.pop("category", IssueCategory.CONSTRAINT),
        severity=Severity.LOW,
        evidence_class=kwargs.pop("evidence_class", EvidenceClass.CONFIRMED_RULE_VIOLATION),
        title="Probe",
        explanation="Probe finding.",
        table=table,
        row=row,
        cells=list(cells),
        evidence=kwargs.pop("evidence", EVIDENCE),
        **kwargs,
    )


class TestSubjectsAndFingerprints:
    def test_table_level_findings_need_a_subject(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        signal = EvidenceClass.EXTRACTION_UNCERTAINTY  # confirmed ones need a cell or a row
        with pytest.raises(IssuePolicyError, match="need a subject"):
            _create(context, table, evidence_class=signal)
        first = _create(context, table, subject="unit_price", evidence_class=signal)
        second = _create(context, table, subject="quantity", evidence_class=signal)
        assert first.fingerprint != second.fingerprint
        assert first.evidence_digest != second.evidence_digest

    def test_a_second_finding_at_the_same_place_is_a_detector_defect(
        self, dataset, boq_profile
    ) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        cell = context.cell_ref(table, row, "quantity")
        _create(context, table, row, [cell])
        with pytest.raises(IssuePolicyError, match="distinguishing subject"):
            _create(context, table, row, [cell])
        # A subject distinguishes two checks on the same cell.
        _create(context, table, row, [cell], subject="quantity:minimum")
        # Released issues still count: fingerprints are unique per run.
        context.issues.release(PROBE.detector_id)
        with pytest.raises(IssuePolicyError):
            _create(context, table, row, [cell], subject="quantity:minimum")

    def test_fingerprints_are_stable_and_subject_sensitive(self, dataset, boq_profile) -> None:
        table = dataset.tables[0]
        row = table.rows[0]

        def make(subject):
            context = make_context(dataset, boq_profile)
            return _create(
                context, table, row, [context.cell_ref(table, row, "quantity")], subject=subject
            )

        assert make("a").fingerprint == make("a").fingerprint
        assert make("a").fingerprint != make("b").fingerprint


class TestEvidenceRule:
    """Every finding carries evidence; a confirmed rule violation points at a cell or a row."""

    def test_findings_without_evidence_are_refused(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        cell = context.cell_ref(table, row, "quantity")
        with pytest.raises(IssuePolicyError, match="has no evidence") as refused:
            _create(context, table, row, [cell], evidence=[])
        assert refused.value.reason == NO_EVIDENCE
        signal = EvidenceClass.EXTRACTION_UNCERTAINTY  # signals need evidence too
        with pytest.raises(IssuePolicyError, match="has no evidence"):
            _create(context, table, subject="unit_price", evidence=[], evidence_class=signal)

    def test_notes_the_factory_adds_are_not_evidence(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("Scan", [("Qty", "quantity")]).row([number_cell("7", confidence=0.4)])
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        cell = context.cell_ref(table, row, "quantity")
        with pytest.raises(IssuePolicyError, match="has no evidence"):
            _create(context, table, row, [cell], evidence=[])  # would get a downgrade note
        downgraded = _create(context, table, row, [cell])
        assert downgraded.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
        assert [item.label for item in downgraded.evidence] == ["Probe", "Evidence downgraded"]

    def test_confirmed_violations_need_a_cell_or_a_row(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        with pytest.raises(IssuePolicyError, match="points at no cell and no row") as refused:
            _create(context, table, subject="unit_price")
        assert refused.value.reason == CONFIRMED_WITHOUT_PLACE
        rate = context.cell_ref(table, row, "unit_price")
        with pytest.raises(IssuePolicyError, match="points at no cell and no row"):
            _create(context, table, subject="rate", inputs=[rate])  # inputs do not place it
        assert _create(context, table, row, subject="by_row").row_id == row.row_id
        assert _create(context, table, cells=[rate], subject="by_cell").affected_cells
        signal = _create(
            context,
            table,
            subject="unit_price",
            evidence_class=EvidenceClass.EXTRACTION_UNCERTAINTY,
        )
        assert signal.row_id is None and not signal.affected_cells
        assert evidence_rule_problem(signal) is None

    def test_the_rule_on_finished_issues(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        issue = _create(context, table, row, [context.cell_ref(table, row, "quantity")])
        assert evidence_rule_problem(issue) is None
        assert evidence_rule_problem(issue.evolve(evidence=[])) == NO_EVIDENCE
        unplaced = issue.evolve(affected_cells=[], row_id=None)
        assert evidence_rule_problem(unplaced) == CONFIRMED_WITHOUT_PLACE
        signal = unplaced.evolve(evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT)
        assert evidence_rule_problem(signal) is None

    def test_one_shot_iterables_are_read_before_the_rule(self, boq_profile) -> None:
        """An empty generator is truthy: the factory must not take it for evidence (the
        finding would carry only the factory's own downgrade note) or for a place."""
        builder = DatasetBuilder(boq_profile)
        builder.table("Scan", [("Qty", "quantity")]).row([number_cell("7", confidence=0.4)])
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        cell = context.cell_ref(table, row, "quantity")
        with pytest.raises(IssuePolicyError, match="has no evidence"):
            _create(context, table, row, [cell], evidence=iter(()))
        with pytest.raises(IssuePolicyError, match="points at no cell and no row"):
            context.issues.create(
                PROBE,
                rule_id="nowhere",
                category=IssueCategory.CONSTRAINT,
                severity=Severity.LOW,
                evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                title="Probe",
                explanation="Probe finding.",
                table=table,
                cells=iter(()),
                evidence=EVIDENCE,
            )
        kept = _create(context, table, row, [cell], evidence=iter(EVIDENCE))
        assert [item.label for item in kept.evidence] == ["Probe", "Evidence downgraded"]

    @pytest.mark.parametrize("cap", ["max_issues_per_detector", "max_issues_per_run"])
    def test_the_rule_comes_before_the_caps(self, dataset, boq_profile, cap) -> None:
        """At a cap, a finding that breaks the evidence rule is refused for the rule, never
        reported as the cap (which would keep the check's status clean)."""
        limits = TEST_LIMITS.model_copy(update={cap: 1})
        context = make_context(dataset, boq_profile, limits=limits)
        table = dataset.tables[0]
        row = table.rows[0]
        _create(context, table, row, [context.cell_ref(table, row, "quantity")])
        rate = context.cell_ref(table, row, "unit_price")
        with pytest.raises(IssuePolicyError, match="has no evidence"):
            _create(context, table, row, [rate], evidence=[])
        with pytest.raises(IssuePolicyError, match="points at no cell and no row"):
            _create(context, table, subject="unit_price")
        with pytest.raises(IssueLimitReached):  # a finding that breaks no rule meets the cap
            _create(context, table, row, [rate])

    def test_the_factory_counts_each_refusal_per_detector(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        cell = context.cell_ref(table, row, "quantity")
        for subject in ("a", "b"):
            with pytest.raises(IssuePolicyError):
                _create(context, table, row, [cell], evidence=[], subject=subject)
        with pytest.raises(IssuePolicyError):
            _create(context, table, subject="unit_price")
        _create(context, table, row, [cell])  # accepted findings are not counted
        assert context.issues.refusals(PROBE.detector_id) == {
            NO_EVIDENCE: 2,
            CONFIRMED_WITHOUT_PLACE: 1,
        }
        assert context.issues.refusals("test.other") == {}
        context.issues.release(PROBE.detector_id)  # the pipeline releases after each step
        assert context.issues.refusals(PROBE.detector_id) == {}


class Probe(Detector[DetectorConfig]):
    """A well-behaved check: one confirmed finding on a cell, with evidence."""

    spec: ClassVar[DetectorSpec] = PROBE

    def validate(self, context, config) -> DetectorResult:
        table = context.tables()[0]
        row = table.rows[0]
        return DetectorResult(
            issues=[_create(context, table, row, [context.cell_ref(table, row, "quantity")])]
        )


def _outside_check(detector_id: str, **extra: Any) -> type[Detector[DetectorConfig]]:
    """An outside check that reports one table-level confirmed finding through the factory."""

    class OutsideCheck(Detector[DetectorConfig]):
        spec: ClassVar[DetectorSpec] = _spec(detector_id)

        def validate(self, context, config) -> DetectorResult:
            issue = context.issues.create(
                self.spec,
                rule_id="bare",
                category=IssueCategory.CONSTRAINT,
                severity=Severity.HIGH,
                evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                title="Bare finding",
                explanation="Reported without support.",
                table=context.tables()[0],
                subject="everything",
                **extra,
            )
            return DetectorResult(issues=[issue])

    return OutsideCheck


class Forged(Detector[DetectorConfig]):
    """An outside check that builds a bare confirmed finding itself, bypassing the factory."""

    spec: ClassVar[DetectorSpec] = _spec("test.forged")

    def validate(self, context, config) -> DetectorResult:
        forged = ValidationIssue(
            issue_id="iss_forged",
            fingerprint="f" * 32,
            validation_run_id=context.run_id,
            document_id=context.document_id,
            dataset_id=context.dataset.dataset_id,
            dataset_revision=context.dataset.revision,
            detector_id=self.spec.detector_id,
            detector_version=self.spec.version,
            issue_category=IssueCategory.CONSTRAINT,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title="Forged finding",
            explanation="Built without the issue factory.",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        return DetectorResult(issues=[forged])


def _hiding_check(
    detector_id: str, *, valid: int = 1, bare: int = 2
) -> type[Detector[DetectorConfig]]:
    """An outside check that catches the factory's refusal itself: it tries ``bare`` findings
    without evidence (refused) between ``valid`` findings with evidence, one per row."""

    class HidingCheck(Detector[DetectorConfig]):
        spec: ClassVar[DetectorSpec] = _spec(detector_id)

        def _finding(self, context, row, evidence, subject) -> ValidationIssue:
            table = context.tables()[0]
            return context.issues.create(
                self.spec,
                rule_id="hidden",
                category=IssueCategory.CONSTRAINT,
                severity=Severity.HIGH,
                evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                title="Finding",
                explanation="A finding of the hiding check.",
                table=table,
                row=row,
                evidence=evidence,
                subject=subject,
            )

        def validate(self, context, config) -> DetectorResult:
            result = DetectorResult()
            rows = context.tables()[0].rows
            for index in range(bare):
                try:
                    self._finding(context, rows[0], [], f"bare-{index}")
                except IssuePolicyError:
                    result.notes.append("A finding could not be reported.")  # and goes on
            for index in range(valid):
                result.add(self._finding(context, rows[index % len(rows)], EVIDENCE, f"v{index}"))
            return result

    return HidingCheck


def _run(dataset, profile, *detectors: type[Detector[DetectorConfig]], limits=None):
    pipeline = ValidationPipeline(
        DetectorRegistry(list(detectors)),
        ids=SequentialIdFactory(),
        clock=FixedClock(),
        limits=limits or ValidationLimits(),
    )
    return pipeline.execute(
        dataset=dataset,
        document_id="doc",
        profile=profile,
        plan=ValidationPlan(
            planner=PlannerKind.USER,
            steps=[PlanStep(detector_id=d.spec.detector_id) for d in detectors],
        ),
        plan_source=PlannerKind.USER,
        run_id="run_1",
    )


class TestEvidenceRuleInRuns:
    @pytest.mark.parametrize(
        ("extra", "reason"),
        [
            ({}, NO_EVIDENCE),
            ({"evidence": EVIDENCE}, CONFIRMED_WITHOUT_PLACE),
        ],
    )
    def test_a_bare_confirmed_finding_fails_its_check_visibly(
        self, dataset, boq_profile, extra, reason
    ) -> None:
        outcome = _run(dataset, boq_profile, _outside_check("test.outside", **extra), Probe)
        reports = {r.detector_id: r for r in outcome.reports}
        outside = reports["test.outside"]
        assert outside.status is DetectorExecutionStatus.FAILED
        assert outside.error.startswith(f"The issue policy rejected {reason}")
        assert "reference err_" in outside.error and outside.issues_found == 0
        assert reports["test.probe"].status is DetectorExecutionStatus.COMPLETED
        assert [i.detector_id for i in outcome.issues] == ["test.probe"]
        assert outcome.status is RunStatus.COMPLETED_WITH_ERRORS

    def test_a_check_that_hides_refusals_fails_and_keeps_its_valid_findings(
        self, dataset, boq_profile
    ) -> None:
        outcome = _run(dataset, boq_profile, _hiding_check("test.hiding"), Probe)
        reports = {r.detector_id: r for r in outcome.reports}
        hiding = reports["test.hiding"]
        assert hiding.status is DetectorExecutionStatus.FAILED
        assert hiding.error == (
            f"The issue policy refused 2 findings of this check: 2 × {NO_EVIDENCE}. The check "
            "went on without them, so it is reported as failed; the findings it was allowed "
            "to make are kept."
        )
        assert hiding.issues_found == 1 and hiding.limit_reached is None
        assert hiding.notes == ["A finding could not be reported."] * 2
        assert sorted(i.detector_id for i in outcome.issues) == ["test.hiding", "test.probe"]
        assert all(evidence_rule_problem(i) is None for i in outcome.issues)
        assert reports["test.probe"].status is DetectorExecutionStatus.COMPLETED
        assert outcome.status is RunStatus.COMPLETED_WITH_ERRORS

    def test_one_hidden_refusal_is_named_too(self, dataset, boq_profile) -> None:
        [report] = _run(dataset, boq_profile, _hiding_check("test.hiding", bare=1)).reports
        assert report.status is DetectorExecutionStatus.FAILED
        assert report.error.startswith(
            f"The issue policy refused 1 finding of this check: 1 × {NO_EVIDENCE}. The check "
            "went on without it,"
        )

    def test_a_rule_breaking_finding_at_the_run_cap_fails_its_check(
        self, dataset, boq_profile
    ) -> None:
        """The run cap is reached by the first check; the second check's bare finding is still
        refused for the evidence rule and fails it, instead of reading "limit reached"."""
        limits = ValidationLimits(max_issues_per_run=1)
        outcome = _run(dataset, boq_profile, Probe, _outside_check("test.outside"), limits=limits)
        reports = {r.detector_id: r for r in outcome.reports}
        outside = reports["test.outside"]
        assert outside.status is DetectorExecutionStatus.FAILED
        assert outside.error.startswith(f"The issue policy rejected {NO_EVIDENCE}")
        assert outside.limit_reached is None and outside.issues_found == 0
        assert reports["test.probe"].status is DetectorExecutionStatus.COMPLETED
        assert [i.detector_id for i in outcome.issues] == ["test.probe"]

    def test_hidden_refusals_fail_a_check_that_a_cap_stopped(self, dataset, boq_profile) -> None:
        limits = ValidationLimits(max_issues_per_detector=1)
        hiding = _hiding_check("test.hiding", valid=2, bare=1)
        [report] = _run(dataset, boq_profile, hiding, limits=limits).reports
        assert report.status is DetectorExecutionStatus.FAILED
        assert report.error.startswith(
            f"The issue policy refused 1 finding of this check: 1 × {NO_EVIDENCE}."
        )
        assert report.limit_reached == "issues" and report.issues_found == 1
        assert "limit of 1" in report.notes[-1]

    def test_a_finding_built_outside_the_factory_cannot_enter_the_run(
        self, dataset, boq_profile
    ) -> None:
        outcome = _run(dataset, boq_profile, Forged, Probe)
        reports = {r.detector_id: r for r in outcome.reports}
        assert reports["test.forged"].status is DetectorExecutionStatus.FAILED
        assert "not created by its issue factory" in reports["test.forged"].error
        assert reports["test.probe"].status is DetectorExecutionStatus.COMPLETED
        assert [i.detector_id for i in outcome.issues] == ["test.probe"]


class TestValueAccess:
    def test_value_accessors_return_the_typed_value(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [("Qty", "quantity"), ("Description", "description")])
        table.row([number_cell("12.5"), text_cell("Aushub")])
        table.row([error_cell("#DIV/0!"), empty_cell("  ")])
        table.row([ambiguous_cell("1.234"), unavailable_formula_cell()])
        table.row([marker_cell("Incl.", ValueMarker.INCLUDED_ELSEWHERE), None])
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        bill = dataset.tables[0]
        first, second, third, fourth = bill.rows
        quantity = bill.column_for_field("quantity").column_id
        assert context.value(bill, first, "quantity").value == Decimal("12.5")
        assert context.value_at(first, quantity) == context.value(bill, first, "quantity")
        assert context.value(bill, first, "description").value == "Aushub"
        assert context.value(bill, second, "quantity").code == "#DIV/0!"
        assert context.value(bill, second, "description") is None  # blank
        assert context.value(bill, third, "quantity") is None  # ambiguous
        assert context.value(bill, third, "description") is None  # no cached result
        assert context.value(bill, fourth, "quantity").value == "Incl."  # a marker, as written
        assert context.value(bill, fourth, "unit") is None  # field not mapped

    def test_detectors_read_values_only_through_the_context(self) -> None:
        """docs/architecture/validation-engine.md: detectors never read
        ``cell.normalized_value`` directly; the context's accessors do. The support modules
        the checks share (the item frame) follow the same rule."""
        packages = Path(__file__).resolve().parents[3] / "app" / "validation"
        modules = [
            path
            for package in ("deterministic", "statistical", "semantic", "domain", "support")
            for path in sorted((packages / package).glob("*.py"))
        ]
        assert packages / "support" / "items.py" in modules
        assert len(modules) > 14
        offenders = [p.name for p in modules if "normalized_value" in p.read_text("utf-8")]
        assert offenders == []


class TestCellConditions:
    @pytest.mark.parametrize(
        ("cell", "condition"),
        [
            (None, CellCondition.EMPTY),
            (empty_cell(), CellCondition.EMPTY),
            (number_cell("1"), CellCondition.USABLE),
            (number_cell("1", status="inferred"), CellCondition.INFERRED),
            (text_cell("abc"), CellCondition.TEXT),
            (marker_cell("Incl.", ValueMarker.INCLUDED_ELSEWHERE), CellCondition.MARKER),
            (ambiguous_cell("1.234"), CellCondition.AMBIGUOUS),
            (failed_number_cell("approx. 5"), CellCondition.FAILED),
            (unavailable_formula_cell(), CellCondition.UNAVAILABLE),
            (error_cell("#DIV/0!"), CellCondition.ERROR),
        ],
    )
    def test_classification(self, cell, condition) -> None:
        assert cell_condition(cell) is condition

    def test_every_finding_condition_has_exactly_one_owner(self) -> None:
        assert set(CONDITION_OWNERS) == {
            CellCondition.ERROR,
            CellCondition.UNAVAILABLE,
            CellCondition.AMBIGUOUS,
            CellCondition.FAILED,
        }

    def test_skip_keys(self) -> None:
        assert skip_key(CellCondition.USABLE) is None
        assert skip_key(CellCondition.INFERRED) is None
        assert skip_key(CellCondition.EMPTY) == Coverage.ROWS_SKIPPED_MISSING_INPUTS
        assert skip_key(CellCondition.MARKER) == Coverage.ROWS_SKIPPED_MARKER
        for condition in CONDITION_OWNERS:
            assert skip_key(condition) == Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS


class TestUnitAndCurrencyAccessors:
    def test_unit_with_and_without_multiplier(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        plain = context.unit(table, table.rows[0])
        assert plain.unit.unit_id == "m3" and plain.multiplier is None
        scaled = context.unit(table, table.rows[1])
        assert scaled.unit.unit_id == "pcs" and scaled.multiplier == Decimal(100)

    def test_unit_from_a_reviewer_alias_and_unknown_units(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", COLUMNS)
        # A reviewer aliased "VE" to pcs: normalization stores the unit id as normalized value.
        table.row(["1", "a", "1", text_cell("VE", normalized="pcs"), "1", "1"])
        table.row(["2", "b", "1", "VE", "1", "1"])
        table.row(["3", "c", "1", None, "1", "1"])
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        rows = dataset.tables[0].rows
        assert context.unit(dataset.tables[0], rows[0]).unit.unit_id == "pcs"
        assert context.unit(dataset.tables[0], rows[1]) is None
        assert context.unit(dataset.tables[0], rows[2]) is None

    def test_currency_evidence(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [*COLUMNS, ("Currency", "currency")])
        table.row(["1", "a", "1", "m", number_cell("2", currency="EUR"), "2", None])
        table.row(["2", "b", "1", "m", "2", "2", "EUR"])
        table.row(["3", "c", "1", "m", number_cell("2", currency="GBP"), "2", "EUR"])
        table.row(["4", "d", "1", "m", "2", "2", "Pesos?"])
        table.row(["5", "e", "1", "m", "2", "2", None])
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        t = dataset.tables[0]
        money = ["unit_price", "line_total"]
        assert context.currency_evidence(t, t.rows[0], money) == "EUR"  # cell marker
        assert context.currency_evidence(t, t.rows[1], money) == "EUR"  # currency column
        assert context.currency_evidence(t, t.rows[2], money) is None  # conflict
        assert context.currency_evidence(t, t.rows[3], money) is None  # unreadable column
        assert context.currency_evidence(t, t.rows[4], money) is None  # nothing marked

    def test_financial_impact_needs_an_explicit_currency(self) -> None:
        with pytest.raises(ValidationError):
            FinancialImpact(amount=Decimal(1), basis="x")  # type: ignore[call-arg]
        impact = money_impact(Decimal("-4.50"), "EUR", "stated - recomputed")
        assert impact.currency == "EUR"


class TestReviewVersions:
    def test_review_increments_the_version(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        issue = _create(context, table, table.rows[0], subject="x")
        assert issue.version == 1
        at = datetime(2026, 2, 1, tzinfo=UTC)
        confirmed = issue.with_review(ReviewStatus.CONFIRMED_ERROR, "checked", at=at)
        assert (confirmed.version, confirmed.review_status) == (2, ReviewStatus.CONFIRMED_ERROR)
        assert confirmed.effective_evidence_class is EvidenceClass.HUMAN_CONFIRMED_ERROR
        assert confirmed.reviewed_at == at
        with pytest.raises(ReviewTransitionError):
            confirmed.with_review(ReviewStatus.FALSE_POSITIVE, None, at=at)
        with pytest.raises(ReviewTransitionError, match="correction workflow"):
            issue.with_review(ReviewStatus.CORRECTED, None, at=at)


class StrictConfig(DetectorConfig):
    threshold: int = Field(default=1, ge=0)


class Strict(Detector[StrictConfig]):
    spec: ClassVar[DetectorSpec] = _spec("test.strict")
    config_model = StrictConfig

    def validate(self, context, config) -> DetectorResult:
        result = DetectorResult()
        result.count("rows_checked")
        return result


class Other(Detector[DetectorConfig]):
    spec: ClassVar[DetectorSpec] = _spec("test.other")

    def validate(self, context, config) -> DetectorResult:
        result = DetectorResult()
        result.count("rows_checked")
        return result


def _with_defaults(profile, defaults):
    return profile.evolve(detector_defaults=defaults)


class TestProfileParameters:
    def test_profile_problems(self, boq_profile) -> None:
        registry = DetectorRegistry([Strict, Other])
        profile = boq_profile.evolve(
            detector_defaults={
                "test.strict": {"threshold": -1},
                "test.typo": {},
            },
        )
        problems = profile_problems(profile, registry)
        assert any("unknown detector 'test.typo'" in p for p in problems)
        assert any("'test.strict' are invalid" in p and "threshold" in p for p in problems)
        with pytest.raises(ProfileError):
            check_profiles([profile], registry)
        check_profiles([boq_profile.evolve(detector_defaults={})], registry)

    def test_invalid_profile_parameters_fail_only_their_baseline_step(
        self, dataset, boq_profile
    ) -> None:
        registry = DetectorRegistry([Strict, Other])
        profile = _with_defaults(boq_profile, {"test.strict": {"threshold": -1}})
        plan = BaselinePlanner(registry).plan(dataset, profile)
        pipeline = ValidationPipeline(
            registry, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
        )
        outcome = pipeline.execute(
            dataset=dataset,
            document_id="doc",
            profile=profile,
            plan=plan,
            plan_source=PlannerKind.BASELINE,
            run_id="run_1",
        )
        reports = {r.detector_id: r for r in outcome.reports}
        assert reports["test.strict"].status is DetectorExecutionStatus.FAILED
        assert "threshold" in reports["test.strict"].error
        assert reports["test.other"].status is DetectorExecutionStatus.COMPLETED
        assert outcome.status is RunStatus.COMPLETED_WITH_ERRORS

    def test_user_plans_with_invalid_parameters_are_still_rejected(
        self, dataset, boq_profile
    ) -> None:
        registry = DetectorRegistry([Strict, Other])
        profile = _with_defaults(boq_profile, {"test.strict": {"threshold": -1}})
        pipeline = ValidationPipeline(
            registry, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
        )
        with pytest.raises(PlanValidationError):
            pipeline.execute(
                dataset=dataset,
                document_id="doc",
                profile=profile,
                plan=ValidationPlan(
                    planner=PlannerKind.USER, steps=[PlanStep(detector_id="test.strict")]
                ),
                plan_source=PlannerKind.USER,
                run_id="run_1",
            )


def _report(status: DetectorExecutionStatus, issues: int = 0) -> DetectorRunReport:
    return DetectorRunReport(
        detector_id="test.x", detector_version="1.0.0", status=status, issues_found=issues
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], RunStatus.COMPLETED),
        ([DetectorExecutionStatus.SKIPPED], RunStatus.COMPLETED),
        ([DetectorExecutionStatus.COMPLETED], RunStatus.COMPLETED),
        ([DetectorExecutionStatus.FAILED], RunStatus.FAILED),
        ([DetectorExecutionStatus.FAILED, DetectorExecutionStatus.SKIPPED], RunStatus.FAILED),
        (
            [DetectorExecutionStatus.FAILED, DetectorExecutionStatus.COMPLETED],
            RunStatus.COMPLETED_WITH_ERRORS,
        ),
        # A stopped detector ran and keeps its findings: the run is partial, not failed.
        ([DetectorExecutionStatus.STOPPED], RunStatus.COMPLETED_WITH_ERRORS),
        (
            [DetectorExecutionStatus.STOPPED, DetectorExecutionStatus.FAILED],
            RunStatus.COMPLETED_WITH_ERRORS,
        ),
    ],
)
def test_run_status_rule(statuses, expected) -> None:
    assert run_status([_report(s) for s in statuses]) is expected
