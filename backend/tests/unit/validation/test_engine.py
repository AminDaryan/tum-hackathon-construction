"""Registry, plan validation, baseline planner, issue factory and pipeline isolation."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import Field

from app.core.clock import FixedClock
from app.core.config import ValidationLimits
from app.core.errors import (
    DetectorConfigError,
    NotFoundError,
    PlanValidationError,
    RegistryError,
    UnknownDetectorError,
)
from app.core.ids import SequentialIdFactory
from app.models.dataset import ExtractionQuality, RowKind
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
)
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.models.run import DetectorExecutionStatus, RunStatus
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.contracts.issue_factory import IssuePolicyError
from app.validation.pipeline import ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, make_context, number_cell

# Every finding needs evidence (the evidence rule of the issue factory).
EVIDENCE = [EvidenceItem(kind=EvidenceKind.NOTE, label="Test", detail="Test evidence.")]


def _spec(detector_id: str, **overrides) -> DetectorSpec:
    data = dict(
        detector_id=detector_id,
        name=detector_id,
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description="test detector",
        applicability="always",
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.CONSTRAINT,),
    )
    data.update(overrides)
    return DetectorSpec(**data)


class FlagFirstRowConfig(DetectorConfig):
    severity: Severity = Severity.LOW
    limit: int = plannable(10, ge=1)
    threshold: int = Field(default=5, ge=0)  # profile-controlled (not plannable)


class FlagFirstRow(Detector[FlagFirstRowConfig]):
    spec: ClassVar[DetectorSpec] = _spec("test.flag_first_row", required_fields=("quantity",))
    config_model = FlagFirstRowConfig

    def validate(self, context: ValidationContext, config: FlagFirstRowConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            row = next(context.rows(table))
            result.add(
                context.issues.create(
                    self.spec,
                    rule_id="first_row",
                    category=IssueCategory.CONSTRAINT,
                    severity=config.severity,
                    evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                    title="First row flagged",
                    explanation="Test finding.",
                    evidence=EVIDENCE,
                    table=table,
                    row=row,
                    cells=[context.cell_ref(table, row, "quantity")],
                )
            )
            result.count("rows_checked")
        return result


class Exploding(Detector[DetectorConfig]):
    spec: ClassVar[DetectorSpec] = _spec("test.exploding")

    def validate(self, context: ValidationContext, config: DetectorConfig) -> DetectorResult:
        raise RuntimeError("boom")


class NeedsMissingField(Detector[DetectorConfig]):
    spec: ClassVar[DetectorSpec] = _spec("test.needs_price", required_fields=("unit_price",))

    def validate(
        self, context: ValidationContext, config: DetectorConfig
    ) -> DetectorResult:  # pragma: no cover
        raise AssertionError("must not run when not applicable")


class NeedsPackage(Detector[DetectorConfig]):
    spec: ClassVar[DetectorSpec] = _spec(
        "test.needs_package", dependencies=("package_that_does_not_exist_xyz",)
    )

    def validate(
        self, context: ValidationContext, config: DetectorConfig
    ) -> DetectorResult:  # pragma: no cover
        raise AssertionError("must not run without its dependency")


class Quiet(Detector[DetectorConfig]):
    spec: ClassVar[DetectorSpec] = _spec("test.quiet")

    def validate(self, context: ValidationContext, config: DetectorConfig) -> DetectorResult:
        return DetectorResult()


@pytest.fixture
def dataset(boq_profile):
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", [("Qty", "quantity"), ("Unit", "unit")])
    table.row(["2", "m"])
    table.row(["3", "m"])
    return builder.build()


@pytest.fixture
def registry() -> DetectorRegistry:
    return DetectorRegistry([FlagFirstRow, Exploding, NeedsMissingField, NeedsPackage, Quiet])


class _TestPipeline:
    """Test convenience: unless a test says otherwise, the plan's declared planner is taken as
    the trusted source (production callers always pass the source of their code path)."""

    def __init__(self, pipeline: ValidationPipeline) -> None:
        self.pipeline = pipeline

    def execute(self, **kwargs):
        kwargs.setdefault("plan_source", kwargs["plan"].planner)
        return self.pipeline.execute(**kwargs)


def _pipeline(registry: DetectorRegistry, **limits) -> _TestPipeline:
    return _TestPipeline(
        ValidationPipeline(
            registry,
            ids=SequentialIdFactory(),
            clock=FixedClock(),
            limits=ValidationLimits(**limits),
        )
    )


class TestRegistry:
    def test_duplicate_ids_rejected(self) -> None:
        with pytest.raises(RegistryError):
            DetectorRegistry([FlagFirstRow, FlagFirstRow])

    def test_config_without_defaults_rejected(self) -> None:
        class NoDefault(DetectorConfig):
            threshold: int

        class Bad(Detector[NoDefault]):
            spec: ClassVar[DetectorSpec] = _spec("test.bad")
            config_model = NoDefault

            def validate(self, context, config):  # pragma: no cover
                return DetectorResult()

        with pytest.raises(RegistryError):
            DetectorRegistry([Bad])

    def test_catalogue_exposes_schema_and_defaults(self, registry: DetectorRegistry) -> None:
        entry = registry.describe("test.flag_first_row")
        assert entry.default_config == {"severity": "low", "limit": 10, "threshold": 5}
        assert "limit" in entry.parameters_schema["properties"]

    def test_unknown_detector(self, registry: DetectorRegistry) -> None:
        with pytest.raises(UnknownDetectorError):
            registry.get("test.nope")

    def test_config_validation_is_strict(self, registry: DetectorRegistry) -> None:
        with pytest.raises(DetectorConfigError) as excinfo:
            registry.resolve_config("test.flag_first_row", [{"limit": 0}])
        assert excinfo.value.details["errors"][0]["loc"] == ["limit"]
        with pytest.raises(DetectorConfigError):
            registry.resolve_config("test.flag_first_row", [{"unknown_param": True}])

    def test_later_layers_override_earlier(self, registry: DetectorRegistry) -> None:
        config = registry.resolve_config("test.flag_first_row", [{"limit": 3}, {"limit": 5}])
        assert config.limit == 5

    def test_nested_layers_merge_instead_of_resetting(self) -> None:
        from app.validation.registry import deep_merge

        merged = deep_merge(
            {"tolerance": {"absolute": "0.01", "per_term_absolute": "0.005"}, "fields": ["a"]},
            {"tolerance": {"absolute": "0.05"}, "fields": ["b"]},
        )
        assert merged == {
            "tolerance": {"absolute": "0.05", "per_term_absolute": "0.005"},
            "fields": ["b"],
        }

    def test_statistical_detectors_cannot_declare_confirmed_violations(self) -> None:
        with pytest.raises(ValueError, match="statistical detectors may not emit"):
            _spec("test.stat", category=DetectorCategory.STATISTICAL)

    def test_missing_optional_dependency_marks_module_unavailable(
        self, tmp_path, monkeypatch
    ) -> None:
        package = tmp_path / "twb_optional_detectors"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "uses_missing.py").write_text("import package_that_is_not_installed_xyz\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        registry = DetectorRegistry.from_packages(["twb_optional_detectors"])
        assert len(registry) == 0
        [entry] = registry.unavailable()
        assert entry.missing_package == "package_that_is_not_installed_xyz"

    def test_builtin_packages_discover_without_errors(self) -> None:
        from app.core.config import Settings

        registry = DetectorRegistry.from_packages(Settings().detector_packages)
        assert registry.ids() == sorted(registry.ids())


class TestPlanValidation:
    def test_rejects_unknown_and_invalid_steps_together(
        self, registry, dataset, boq_profile
    ) -> None:
        plan = ValidationPlan(
            planner=PlannerKind.USER,
            steps=[
                PlanStep(detector_id="test.nope"),
                PlanStep(detector_id="test.flag_first_row", config={"limit": "many"}),
            ],
        )
        with pytest.raises(PlanValidationError) as excinfo:
            _pipeline(registry).execute(
                dataset=dataset, document_id="doc", profile=boq_profile, plan=plan, run_id="run_1"
            )
        codes = [e["code"] for e in excinfo.value.details["errors"]]
        assert codes == ["unknown_detector", "invalid_detector_config"]

    def test_plans_cannot_set_profile_controlled_parameters(
        self, registry, dataset, boq_profile
    ) -> None:
        plan = ValidationPlan(
            planner=PlannerKind.USER,
            steps=[PlanStep(detector_id="test.flag_first_row", config={"threshold": 0})],
        )
        with pytest.raises(PlanValidationError) as excinfo:
            _pipeline(registry).execute(
                dataset=dataset, document_id="doc", profile=boq_profile, plan=plan, run_id="run_1"
            )
        [error] = excinfo.value.details["errors"]
        assert error["code"] == "parameter_not_plannable"
        assert error["parameters"] == ["threshold"]

    def test_rejects_oversized_plans(self, registry, dataset, boq_profile) -> None:
        plan = ValidationPlan(
            planner=PlannerKind.LLM,
            steps=[
                PlanStep(detector_id="test.flag_first_row", config={"limit": i + 1})
                for i in range(3)
            ],
        )
        with pytest.raises(PlanValidationError):
            _pipeline(registry, max_plan_steps=2).execute(
                dataset=dataset, document_id="doc", profile=boq_profile, plan=plan, run_id="run_1"
            )

    def test_rejects_repeated_identical_steps(self, registry, dataset, boq_profile) -> None:
        plan = ValidationPlan(
            planner=PlannerKind.USER,
            steps=[
                PlanStep(detector_id="test.flag_first_row"),
                PlanStep(detector_id="test.flag_first_row"),
            ],
        )
        with pytest.raises(PlanValidationError) as excinfo:
            _pipeline(registry).execute(
                dataset=dataset, document_id="doc", profile=boq_profile, plan=plan, run_id="run_1"
            )
        assert excinfo.value.details["errors"][0]["code"] == "duplicate_step"

    def test_rejects_empty_plan(self, registry, dataset, boq_profile) -> None:
        with pytest.raises(PlanValidationError):
            _pipeline(registry).execute(
                dataset=dataset,
                document_id="doc",
                profile=boq_profile,
                plan=ValidationPlan(planner=PlannerKind.USER, steps=[]),
                run_id="run_1",
            )


class TestPipeline:
    def test_baseline_plan_and_isolation(self, registry, dataset, boq_profile) -> None:
        plan = BaselinePlanner(registry).plan(dataset, boq_profile)
        assert plan.planner is PlannerKind.BASELINE
        assert plan.notes[0].startswith(
            "Adaptive AI planning is not available in this version; every registered check runs"
        )
        assert [s.detector_id for s in plan.steps] == registry.ids()
        outcome = _pipeline(registry).execute(
            dataset=dataset, document_id="doc", profile=boq_profile, plan=plan, run_id="run_1"
        )
        reports = {r.detector_id: r for r in outcome.reports}
        assert reports["test.flag_first_row"].status is DetectorExecutionStatus.COMPLETED
        assert reports["test.flag_first_row"].coverage == {"rows_checked": 1}
        assert reports["test.exploding"].status is DetectorExecutionStatus.FAILED
        error = reports["test.exploding"].error
        # Exception text can carry document content: only the type and a log reference show.
        assert error.startswith("RuntimeError (reference err_")
        assert "boom" not in error
        assert reports["test.needs_price"].status is DetectorExecutionStatus.SKIPPED
        assert "unit_price" in reports["test.needs_price"].skipped_reasons[0]
        assert reports["test.needs_package"].status is DetectorExecutionStatus.SKIPPED
        assert outcome.status is RunStatus.COMPLETED_WITH_ERRORS
        assert len(outcome.issues) == 1
        issue = outcome.issues[0]
        assert issue.validation_run_id == "run_1"
        assert issue.affected_cells[0].source.a1 == "A2"

    def test_issue_cap_is_reported_not_silent(self, dataset, boq_profile) -> None:
        class Many(Detector[DetectorConfig]):
            spec: ClassVar[DetectorSpec] = _spec("test.many")

            def validate(self, context, config):
                result = DetectorResult()
                table = context.tables()[0]
                for row in context.rows(table):
                    result.add(
                        context.issues.create(
                            self.spec,
                            rule_id="many",
                            category="constraint",
                            severity=Severity.INFO,
                            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                            title="x",
                            explanation="x",
                            evidence=EVIDENCE,
                            table=table,
                            row=row,
                        )
                    )
                return result

        outcome = _pipeline(DetectorRegistry([Many]), max_issues_per_detector=1).execute(
            dataset=dataset,
            document_id="doc",
            profile=boq_profile,
            plan=ValidationPlan(
                planner=PlannerKind.USER, steps=[PlanStep(detector_id="test.many")]
            ),
            run_id="run_1",
        )
        report = outcome.reports[0]
        # The cap stops the detector when the next issue would be created (bounded memory),
        # keeps what was made and says so.
        assert report.status is DetectorExecutionStatus.COMPLETED
        assert report.issues_found == 1 and len(outcome.issues) == 1
        assert report.limit_reached == "issues"
        assert "limit of 1" in report.notes[-1]
        assert any("run limit" in w for w in outcome.warnings)

    def test_issues_not_created_by_the_factory_fail_the_detector(
        self, dataset, boq_profile
    ) -> None:
        class Tamper(Detector[DetectorConfig]):
            spec: ClassVar[DetectorSpec] = _spec("test.tamper")

            def validate(self, context, config):
                table = context.tables()[0]
                row = table.rows[0]
                issue = context.issues.create(
                    self.spec,
                    rule_id="tamper",
                    category="constraint",
                    severity=Severity.LOW,
                    evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                    title="x",
                    explanation="x",
                    evidence=EVIDENCE,
                    table=table,
                    row=row,
                )
                return DetectorResult(issues=[issue.model_copy(update={"title": "edited"})])

        outcome = _pipeline(DetectorRegistry([Tamper])).execute(
            dataset=dataset,
            document_id="doc",
            profile=boq_profile,
            plan=ValidationPlan(
                planner=PlannerKind.USER, steps=[PlanStep(detector_id="test.tamper")]
            ),
            run_id="run_1",
        )
        assert outcome.reports[0].status is DetectorExecutionStatus.FAILED
        assert outcome.issues == []

    def test_failed_extraction_is_not_validated(self, registry, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile, quality=ExtractionQuality.FAILED)
        builder.table("LV", [("Qty", "quantity")]).row(["1"])
        outcome = _pipeline(registry).execute(
            dataset=builder.build(),
            document_id="doc",
            profile=boq_profile,
            plan=ValidationPlan(
                planner=PlannerKind.USER, steps=[PlanStep(detector_id="test.flag_first_row")]
            ),
            run_id="run_1",
        )
        assert outcome.status is RunStatus.FAILED
        assert outcome.reports == [] and outcome.issues == []

    def test_warns_when_extraction_needs_review(self, registry, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile, quality=ExtractionQuality.NEEDS_REVIEW)
        builder.table("LV", [("Qty", "quantity")]).row(["1"])
        outcome = _pipeline(registry).execute(
            dataset=builder.build(),
            document_id="doc",
            profile=boq_profile,
            plan=ValidationPlan(
                planner=PlannerKind.USER, steps=[PlanStep(detector_id="test.flag_first_row")]
            ),
            run_id="run_1",
        )
        assert outcome.warnings and "needs review" in outcome.warnings[0]


class TestIssueFactory:
    def _create(self, context, table, row, column_field="quantity"):
        return context.issues.create(
            FlagFirstRow.spec,
            rule_id="first_row",
            category=IssueCategory.CONSTRAINT,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title="t",
            explanation="e",
            evidence=EVIDENCE,
            table=table,
            row=row,
            cells=[context.cell_ref(table, row, column_field)],
        )

    def test_low_confidence_inputs_downgrade_confirmed_violations(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("Scan", [("Qty", "quantity")]).row([number_cell("7", confidence=0.55)])
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        issue = self._create(context, table, table.rows[0])
        assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
        assert issue.extraction_confidence == 0.55
        assert issue.evidence[-1].label == "Evidence downgraded"

    def test_high_confidence_stays_confirmed(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        issue = self._create(context, table, table.rows[0])
        assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION

    def test_fingerprint_is_stable_across_runs_and_ids(self, dataset, boq_profile) -> None:
        table = dataset.tables[0]
        first = self._create(
            make_context(dataset, boq_profile, run_id="run_a"), table, table.rows[0]
        )
        second = self._create(
            make_context(dataset, boq_profile, run_id="run_b"), table, table.rows[0]
        )
        other_row = self._create(make_context(dataset, boq_profile), table, table.rows[1])
        assert first.fingerprint == second.fingerprint
        assert first.fingerprint != other_row.fingerprint
        assert first.evidence_digest == second.evidence_digest

    def test_fingerprint_survives_renormalization_with_new_ids(self, boq_profile) -> None:
        def build(offset: int):
            builder = DatasetBuilder(boq_profile)
            for _ in range(offset):  # shift every generated id
                builder.ids.new("row"), builder.ids.new("col"), builder.ids.new("tbl")
            builder.table("LV", [("Qty", "quantity"), ("Unit", "unit")]).row(["2", "m"])
            return builder.build()

        a, b = build(0), build(7)
        assert a.tables[0].rows[0].row_id != b.tables[0].rows[0].row_id
        issue_a = self._create(make_context(a, boq_profile), a.tables[0], a.tables[0].rows[0])
        issue_b = self._create(make_context(b, boq_profile), b.tables[0], b.tables[0].rows[0])
        assert issue_a.fingerprint == issue_b.fingerprint

    def test_input_cells_are_checked_by_the_evidence_policy(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("Scan", [("Qty", "quantity"), ("Rate", "unit_price")]).row(
            ["2", number_cell("7", confidence=0.4)]
        )
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        issue = context.issues.create(
            FlagFirstRow.spec,
            rule_id="first_row",
            category=IssueCategory.CONSTRAINT,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title="t",
            explanation="e",
            evidence=EVIDENCE,
            table=table,
            row=row,
            cells=[context.cell_ref(table, row, "quantity")],
            inputs=[context.cell_ref(table, row, "unit_price")],
        )
        assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
        assert issue.input_cells[0].column_id == table.column_for_field("unit_price").column_id

    def test_digital_cells_have_no_invented_confidence(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        issue = self._create(context, table, table.rows[0])
        assert issue.extraction_confidence is None

    def test_undeclared_evidence_class_or_category_is_rejected(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        common = dict(
            rule_id="r",
            severity=Severity.LOW,
            title="t",
            explanation="e",
            row=row,
            evidence=EVIDENCE,
        )
        with pytest.raises(IssuePolicyError):
            context.issues.create(
                FlagFirstRow.spec,
                category=IssueCategory.CONSTRAINT,
                evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
                **common,
            )
        with pytest.raises(IssuePolicyError):
            context.issues.create(
                FlagFirstRow.spec,
                category=IssueCategory.ARITHMETIC,
                evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                **common,
            )

    def test_caller_supplied_source_is_replaced_by_the_dataset(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        row = table.rows[0]
        ref = context.cell_ref(table, row, "quantity")
        forged = ref.evolve(source=ref.source.evolve(row_number=999))
        issue = context.issues.create(
            FlagFirstRow.spec,
            rule_id="first_row",
            category=IssueCategory.CONSTRAINT,
            severity=Severity.LOW,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title="t",
            explanation="e",
            evidence=EVIDENCE,
            cells=[forged],
        )
        assert issue.affected_cells[0].source.row_number == row.source_row_number
        assert issue.row_id == row.row_id  # derived from the highlighted cells

    def test_rejects_references_to_unknown_cells(self, dataset, boq_profile) -> None:
        context = make_context(dataset, boq_profile)
        table = dataset.tables[0]
        ref = context.cell_ref(table, table.rows[0], "quantity").evolve(row_id="row_missing")
        with pytest.raises(NotFoundError):
            context.issues.create(
                FlagFirstRow.spec,
                rule_id="first_row",
                category="constraint",
                severity=Severity.LOW,
                evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
                title="t",
                explanation="e",
                evidence=EVIDENCE,
                cells=[ref],
            )


class TestContext:
    def test_rows_filter_by_kind_and_exclusion(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [("Qty", "quantity")])
        table.row(["1"]).row(["2"], kind=RowKind.SUBTOTAL).row(["3"], excluded=True)
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        tbl = dataset.tables[0]
        assert [context.number(tbl, r, "quantity") for r in context.rows(tbl)] == [1]
        assert len(list(context.rows(tbl, None))) == 2
        assert len(list(context.rows(tbl, None, include_excluded=True))) == 3

    def test_number_accessor_abstains_on_unusable_cells(self, boq_profile) -> None:
        from tests.support.builders import ambiguous_cell, failed_number_cell

        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [("Qty", "quantity")])
        table.row([ambiguous_cell("1,234")]).row([failed_number_cell("approx. 5")]).row([None])
        dataset = builder.build()
        context = make_context(dataset, boq_profile)
        tbl = dataset.tables[0]
        assert [context.number(tbl, r, "quantity") for r in tbl.rows] == [None, None, None]
        assert context.number(tbl, tbl.rows[0], "unit_price") is None  # unmapped field
