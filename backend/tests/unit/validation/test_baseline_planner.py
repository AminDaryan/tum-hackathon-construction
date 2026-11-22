"""The baseline plan: every registered check, whatever the profile (ADR 0010), each with a
rationale that says whether it can confirm an error or only signals one."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import ValidationError

from app.models.dataset import Dataset
from app.models.issue import EvidenceClass, IssueCategory
from app.models.plan import PlannerKind
from app.models.profile import DomainProfile
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.planner import (
    BASELINE_NOTE,
    RULE_RATIONALE,
    SIGNAL_RATIONALE,
    BaselinePlanner,
    Planner,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder


def _spec(
    detector_id: str,
    *,
    category: DetectorCategory = DetectorCategory.DETERMINISTIC,
    evidence: tuple[EvidenceClass, ...] = (EvidenceClass.CONFIRMED_RULE_VIOLATION,),
) -> DetectorSpec:
    return DetectorSpec(
        detector_id=detector_id,
        name=detector_id,
        version="1.0.0",
        category=category,
        description="test detector",
        applicability="always",
        evidence_classes=evidence,
        issue_categories=(IssueCategory.CONSTRAINT,),
    )


class _Quiet(Detector[DetectorConfig]):
    def validate(
        self, context: ValidationContext, config: DetectorConfig
    ) -> DetectorResult:  # pragma: no cover - planning never runs a check
        return DetectorResult()


class Rule(_Quiet):
    spec: ClassVar[DetectorSpec] = _spec("test.rule")


class Signal(_Quiet):
    spec: ClassVar[DetectorSpec] = _spec(
        "test.signal",
        category=DetectorCategory.STATISTICAL,
        evidence=(EvidenceClass.SUSPECTED_ANOMALY, EvidenceClass.EXTRACTION_UNCERTAINTY),
    )


class SemanticCheck(_Quiet):
    spec: ClassVar[DetectorSpec] = _spec(
        "test.a_warning",
        category=DetectorCategory.SEMANTIC,
        evidence=(EvidenceClass.SEMANTIC_WARNING,),
    )


@pytest.fixture
def registry() -> DetectorRegistry:
    return DetectorRegistry([Rule, Signal, SemanticCheck])


@pytest.fixture
def dataset(boq_profile: DomainProfile) -> Dataset:
    builder = DatasetBuilder(boq_profile)
    builder.table("LV", [("Qty", "quantity")]).row(["1"])
    return builder.build()


def test_it_is_a_planner(registry: DetectorRegistry) -> None:
    planner: Planner = BaselinePlanner(registry)
    assert isinstance(planner, BaselinePlanner)


@pytest.mark.parametrize("profile_id", ["boq", "generic"])
def test_every_registered_check_is_planned(
    registry: DetectorRegistry,
    dataset: Dataset,
    profile_id: str,
    boq_profile: DomainProfile,
    generic_profile: DomainProfile,
) -> None:
    profile = boq_profile if profile_id == "boq" else generic_profile
    plan = BaselinePlanner(registry).plan(dataset, profile)
    assert plan.planner is PlannerKind.BASELINE
    assert [(s.detector_id, s.rationale, s.config) for s in plan.steps] == [
        ("test.a_warning", SIGNAL_RATIONALE, {}),  # registry order (by id)
        ("test.rule", RULE_RATIONALE, {}),
        ("test.signal", SIGNAL_RATIONALE, {}),
    ]
    assert plan.notes == [BASELINE_NOTE]


@pytest.mark.parametrize("key", ["baseline_detectors", "disabled_detectors"])
def test_a_profile_cannot_choose_checks(boq_profile: DomainProfile, key: str) -> None:
    data = boq_profile.model_dump(mode="json")
    with pytest.raises(ValidationError, match=key):
        DomainProfile.model_validate({**data, key: ["test.signal"]})
