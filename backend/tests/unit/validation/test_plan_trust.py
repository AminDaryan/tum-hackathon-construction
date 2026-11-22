"""Plan trust: the code path decides who produced a plan, baseline plans carry no parameters,
LLM plans keep every registered check, per-detector step limits, plannable parameters only, the
deep merge of plan parameters over profile defaults, and whole-plan rejection of user and LLM
plans with invalid parameters."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.core.clock import FixedClock
from app.core.config import ValidationLimits
from app.core.errors import PlanValidationError
from app.core.ids import SequentialIdFactory
from app.models.issue import EvidenceClass, IssueCategory, Severity
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.validation.contracts.detector import (
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.pipeline import ValidationPipeline
from app.validation.plan_validation import PlanValidator, ResolvedStep
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder


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


class ChecksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Severity = Severity.LOW
    fields: list[str] = Field(default_factory=lambda: ["quantity"])


class TunableConfig(DetectorConfig):
    limit: int = plannable(10, ge=1)
    checks: ChecksConfig = plannable(ChecksConfig())
    threshold: int = Field(default=5, ge=0)  # profile-controlled
    pattern: str = r"^\d+$"  # profile-controlled


class _Quiet(Detector[DetectorConfig]):
    def validate(self, context, config) -> DetectorResult:
        result = DetectorResult()
        result.count("rows_checked")
        return result


class Base(_Quiet):
    spec: ClassVar[DetectorSpec] = _spec("test.base")


class Extra(_Quiet):
    spec: ClassVar[DetectorSpec] = _spec("test.extra")


class Tunable(_Quiet):
    spec: ClassVar[DetectorSpec] = _spec("test.tunable")
    config_model = TunableConfig


@pytest.fixture
def registry() -> DetectorRegistry:
    return DetectorRegistry([Base, Extra, Tunable])


def _plan(planner: PlannerKind, *steps: tuple[str, dict]) -> ValidationPlan:
    return ValidationPlan(
        planner=planner,
        steps=[PlanStep(detector_id=detector_id, config=config) for detector_id, config in steps],
    )


def _validate(
    registry: DetectorRegistry,
    plan: ValidationPlan,
    profile,
    *,
    source: PlannerKind | None = None,
    **limits,
) -> list[ResolvedStep]:
    validator = PlanValidator(registry, ValidationLimits(**limits))
    return validator.validate(plan, profile, source=source or plan.planner)


def _errors(excinfo: pytest.ExceptionInfo[PlanValidationError]) -> list[dict]:
    return excinfo.value.details["errors"]


BASELINE_STEPS = (("test.base", {}), ("test.extra", {}))


class TestPlannerProvenance:
    @pytest.mark.parametrize(
        ("declared", "source"),
        [
            (PlannerKind.BASELINE, PlannerKind.USER),  # a client labelling its plan "baseline"
            (PlannerKind.USER, PlannerKind.LLM),
            (PlannerKind.LLM, PlannerKind.BASELINE),
        ],
    )
    def test_declared_planner_must_match_the_code_path(
        self, registry, boq_profile, declared, source
    ) -> None:
        plan = _plan(declared, *BASELINE_STEPS)
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, plan, boq_profile, source=source)
        assert excinfo.value.code == "invalid_validation_plan"
        assert excinfo.value.details == {"declared": declared.value, "source": source.value}

    def test_provenance_is_checked_before_anything_else(self, registry, boq_profile) -> None:
        empty = ValidationPlan(planner=PlannerKind.BASELINE, steps=[])
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, empty, boq_profile, source=PlannerKind.USER)
        assert excinfo.value.details == {"declared": "baseline", "source": "user"}


class TestBaselinePlans:
    def test_baseline_steps_cannot_carry_parameters(self, registry, boq_profile) -> None:
        # Even a plannable, valid value: the baseline planner never sets parameters.
        plan = _plan(PlannerKind.BASELINE, ("test.base", {}), ("test.tunable", {"limit": 3}))
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, plan, boq_profile)
        [error] = _errors(excinfo)
        assert error["code"] == "baseline_step_with_parameters"
        assert error["step"] == 1

    def test_profile_controlled_parameters_cannot_be_smuggled_in_as_baseline(
        self, registry, boq_profile
    ) -> None:
        plan = _plan(PlannerKind.BASELINE, ("test.tunable", {"threshold": 0, "pattern": ".*"}))
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, plan, boq_profile)
        assert [e["code"] for e in _errors(excinfo)] == ["baseline_step_with_parameters"]


class TestLlmPlansKeepEveryCheck:
    def test_missing_checks_are_listed(self, registry, boq_profile) -> None:
        plan = _plan(PlannerKind.LLM, ("test.tunable", {}))
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, plan, boq_profile)
        [error] = _errors(excinfo)
        assert error["code"] == "check_missing"
        assert error["detector_ids"] == ["test.base", "test.extra"]

    def test_a_complete_llm_plan_may_set_plannable_parameters(self, registry, boq_profile) -> None:
        plan = _plan(PlannerKind.LLM, *BASELINE_STEPS, ("test.tunable", {"limit": 2}))
        resolved = _validate(registry, plan, boq_profile)
        assert [r.step.detector_id for r in resolved] == ["test.base", "test.extra", "test.tunable"]
        assert resolved[2].config.limit == 2


class TestStepsPerDetector:
    def test_a_detector_listed_too_often_is_rejected(self, registry, boq_profile) -> None:
        steps = [("test.tunable", {"limit": n}) for n in range(1, 5)]
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, _plan(PlannerKind.USER, *steps), boq_profile)
        [error] = _errors(excinfo)
        assert error == {
            "code": "too_many_steps_for_detector",
            "message": "Detector 'test.tunable' appears 4 times; the limit is 3.",
            "detector_id": "test.tunable",
        }

    def test_up_to_the_limit_is_accepted(self, registry, boq_profile) -> None:
        steps = [("test.tunable", {"limit": n}) for n in range(1, 4)]
        resolved = _validate(registry, _plan(PlannerKind.USER, *steps), boq_profile)
        assert [r.config.limit for r in resolved] == [1, 2, 3]
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(
                registry, _plan(PlannerKind.USER, *steps[:2]), boq_profile, max_steps_per_detector=1
            )
        assert [e["code"] for e in _errors(excinfo)] == ["too_many_steps_for_detector"]

    def test_steps_that_resolve_to_the_same_parameters_are_duplicates(
        self, registry, boq_profile
    ) -> None:
        # {"limit": 10} is the default, so both steps would run the identical check.
        plan = _plan(PlannerKind.USER, ("test.tunable", {}), ("test.tunable", {"limit": 10}))
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, plan, boq_profile)
        [error] = _errors(excinfo)
        assert (error["code"], error["step"]) == ("duplicate_step", 1)


class TestPlannableParameters:
    @pytest.mark.parametrize("source", [PlannerKind.USER, PlannerKind.LLM])
    def test_profile_controlled_parameters_are_listed(self, registry, boq_profile, source) -> None:
        plan = _plan(
            source,
            *BASELINE_STEPS,
            ("test.tunable", {"limit": 2, "threshold": 0, "pattern": ".*", "typo": 1}),
        )
        with pytest.raises(PlanValidationError) as excinfo:
            _validate(registry, plan, boq_profile)
        [error] = _errors(excinfo)
        assert error["code"] == "parameter_not_plannable"
        assert error["step"] == 2
        # Unknown keys are refused the same way: a plan sets only declared plannable names.
        assert error["parameters"] == ["pattern", "threshold", "typo"]

    def test_plan_parameters_deep_merge_over_profile_defaults(self, registry, boq_profile) -> None:
        profile = boq_profile.evolve(
            detector_defaults={
                "test.tunable": {
                    "checks": {"severity": "high", "fields": ["quantity", "unit_price"]},
                    "threshold": 7,
                }
            }
        )
        plan = _plan(
            PlannerKind.USER,
            ("test.tunable", {"limit": 4, "checks": {"severity": "critical"}}),
            ("test.tunable", {"checks": {"fields": ["line_total"]}}),
        )
        first, second = (r.config for r in _validate(registry, plan, profile))
        assert first.limit == 4
        assert first.checks == ChecksConfig(
            severity=Severity.CRITICAL, fields=["quantity", "unit_price"]
        )
        assert first.threshold == 7  # the profile's value, which the plan could not set
        assert first.pattern == r"^\d+$"
        # Lists replace instead of merging; the sibling severity comes from the profile.
        assert second.checks == ChecksConfig(severity=Severity.HIGH, fields=["line_total"])
        assert second.limit == 10


@pytest.fixture
def dataset(boq_profile):
    builder = DatasetBuilder(boq_profile)
    builder.table("LV", [("Qty", "quantity")]).row(["1"])
    return builder.build()


def _execute(registry, dataset, profile, plan):
    pipeline = ValidationPipeline(
        registry, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
    )
    return pipeline.execute(
        dataset=dataset,
        document_id="doc",
        profile=profile,
        plan=plan,
        plan_source=plan.planner,
        run_id="run_1",
    )


class TestInvalidParametersRejectTheWholePlan:
    def test_llm_plan_with_an_invalid_plannable_value(self, registry, dataset, boq_profile) -> None:
        plan = _plan(
            PlannerKind.LLM,
            *BASELINE_STEPS,
            ("test.tunable", {"limit": 0, "checks": {"severity": "catastrophic"}}),
        )
        with pytest.raises(PlanValidationError) as excinfo:
            _execute(registry, dataset, boq_profile, plan)
        [error] = _errors(excinfo)
        assert (error["step"], error["code"]) == (2, "invalid_detector_config")
        assert error["detector_id"] == "test.tunable"
        assert sorted(e["loc"] for e in error["errors"]) == [["checks", "severity"], ["limit"]]

    @pytest.mark.parametrize("source", [PlannerKind.USER, PlannerKind.LLM])
    def test_invalid_profile_parameters_reject_user_and_llm_plans(
        self, registry, dataset, boq_profile, source
    ) -> None:
        # A baseline plan would run the valid steps and fail only this one
        # (test_contract_rules.py); user and LLM plans are refused before anything runs.
        profile = boq_profile.evolve(detector_defaults={"test.tunable": {"threshold": -1}})
        plan = _plan(source, *BASELINE_STEPS, ("test.tunable", {"limit": 2}))
        with pytest.raises(PlanValidationError) as excinfo:
            _execute(registry, dataset, profile, plan)
        [error] = _errors(excinfo)
        assert (error["step"], error["code"]) == (2, "invalid_detector_config")
        assert [e["loc"] for e in error["errors"]] == [["threshold"]]
