"""Baseline planner: the always-available, no-LLM path.

Every validation runs every registered detector (ADR 0010); there is no opt-in check and no
way to switch one off. Applicability is decided per detector at execution time and reported,
so a dataset without mapped price columns shows "skipped: unit_price not mapped" rather than
silence. An LLM planner (later phase) will produce the same :class:`ValidationPlan` shape and
pass through the same :class:`~app.validation.plan_validation.PlanValidator`, which requires
every registered check in an adaptive plan.

The planner a workbench uses is injectable (``Workbench.planner``); services call it through
the :class:`Planner` protocol. A planner's ``kind`` is what the plan validator trusts as the
plan's source (the code path, never the plan's own ``planner`` label).
"""

from __future__ import annotations

from typing import Protocol

from app.models.dataset import Dataset
from app.models.issue import EvidenceClass
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.models.profile import DomainProfile
from app.validation.contracts.detector import DetectorSpec
from app.validation.registry.registry import DetectorRegistry

BASELINE_NOTE = (
    "Adaptive AI planning is not available in this version; every registered check runs, "
    "and each one reports whether it applies to this dataset."
)
RULE_RATIONALE = "Runs on every validation: a rule check that can confirm an error."
SIGNAL_RATIONALE = "Runs on every validation: a signal, never a confirmed error."


class Planner(Protocol):
    @property
    def kind(self) -> PlannerKind:
        """Who produces the plans: the source the plan validator checks them against."""
        ...

    def plan(self, dataset: Dataset, profile: DomainProfile) -> ValidationPlan: ...


def rationale(spec: DetectorSpec) -> str:
    """Why a step is in the plan: whether the check can confirm an error or only signals one."""
    if EvidenceClass.CONFIRMED_RULE_VIOLATION in spec.evidence_classes:
        return RULE_RATIONALE
    return SIGNAL_RATIONALE


class BaselinePlanner:
    kind = PlannerKind.BASELINE

    def __init__(self, registry: DetectorRegistry) -> None:
        self._registry = registry

    def plan(self, dataset: Dataset, profile: DomainProfile) -> ValidationPlan:
        steps = [
            PlanStep(detector_id=spec.detector_id, rationale=rationale(spec))
            for spec in self._registry.specs()
        ]
        return ValidationPlan(planner=PlannerKind.BASELINE, steps=steps, notes=[BASELINE_NOTE])
