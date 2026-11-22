"""Strict validation of plans against the registry before anything executes.

Rejects: unknown detector ids, invalid or unknown parameters,
parameters a non-baseline plan is not allowed to set (only parameters declared ``plannable``;
tolerances, patterns and switches stay under the profile's control), plans with more steps than
the configured limit or too many steps for one detector, and repeated identical steps (the
guard against repetitive tool calls from an adaptive planner).

Trust comes from the code path, never from the payload: callers pass ``source``, the kind of
planner that actually produced the plan (a plan received over the API is ``user``), and the
plan's own ``planner`` field must agree. A baseline plan may not carry parameters at all (the
baseline planner never sets any). An LLM plan must keep every registered check: every
validation runs them all (ADR 0010), and a document's text cannot talk the planner out of one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.config import ValidationLimits
from app.core.errors import DetectorConfigError, PlanValidationError, WorkbenchError
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.models.profile import DomainProfile
from app.validation.contracts.detector import AnyDetector, DetectorConfig
from app.validation.registry.registry import DetectorRegistry


@dataclass(frozen=True, slots=True)
class ResolvedStep:
    """A validated step. ``config`` is ``None`` only for a baseline step whose profile
    parameters are invalid: the pipeline reports that step as failed (``config_error``)
    and runs the others."""

    step: PlanStep
    detector: type[AnyDetector]
    config: DetectorConfig | None
    config_error: str | None = None


class PlanValidator:
    def __init__(self, registry: DetectorRegistry, limits: ValidationLimits) -> None:
        self._registry = registry
        self._limits = limits

    def validate(
        self, plan: ValidationPlan, profile: DomainProfile, *, source: PlannerKind
    ) -> list[ResolvedStep]:
        if plan.planner is not source:
            raise PlanValidationError(
                "The plan's planner field does not match the code path that produced it.",
                details={"declared": plan.planner.value, "source": source.value},
            )
        if not plan.steps:
            raise PlanValidationError("The validation plan contains no steps.")
        if len(plan.steps) > self._limits.max_plan_steps:
            raise PlanValidationError(
                f"The plan has {len(plan.steps)} steps; "
                f"the limit is {self._limits.max_plan_steps}.",
                details={"steps": len(plan.steps), "limit": self._limits.max_plan_steps},
            )
        resolved: list[ResolvedStep] = []
        seen: set[tuple[str, str]] = set()
        errors: list[dict[str, object]] = []
        errors.extend(self._structural_errors(plan, source))
        for index, step in enumerate(plan.steps):
            try:
                detector = self._registry.get(step.detector_id)
                if source is not PlannerKind.BASELINE:
                    locked = sorted(set(step.config) - detector.config_model.plannable_parameters())
                    if locked:
                        errors.append(
                            {
                                "step": index,
                                "code": "parameter_not_plannable",
                                "message": "These parameters are controlled by the domain "
                                f"profile and cannot be set by a plan: {', '.join(locked)}.",
                                "parameters": locked,
                            }
                        )
                        continue
                config = step_config(self._registry, profile, step.detector_id, step.config)
            except DetectorConfigError as exc:
                if source is PlannerKind.BASELINE:
                    # Only profile defaults are involved: fail this check, run the others.
                    resolved.append(
                        ResolvedStep(
                            step=step,
                            detector=detector,
                            config=None,
                            config_error=_config_error_text(profile, exc),
                        )
                    )
                    continue
                errors.append(
                    {"step": index, "code": exc.code, "message": exc.message, **exc.details}
                )
                continue
            except WorkbenchError as exc:
                errors.append(
                    {"step": index, "code": exc.code, "message": exc.message, **exc.details}
                )
                continue
            key = (step.detector_id, json.dumps(config.model_dump(mode="json"), sort_keys=True))
            if key in seen:
                errors.append(
                    {
                        "step": index,
                        "code": "duplicate_step",
                        "message": f"Detector {step.detector_id!r} is requested twice "
                        "with the same parameters.",
                    }
                )
                continue
            seen.add(key)
            resolved.append(ResolvedStep(step=step, detector=detector, config=config))
        if errors:
            raise PlanValidationError("The validation plan is invalid.", details={"errors": errors})
        return resolved

    def _structural_errors(
        self, plan: ValidationPlan, source: PlannerKind
    ) -> list[dict[str, object]]:
        errors: list[dict[str, object]] = []
        if source is PlannerKind.BASELINE:
            errors.extend(
                {
                    "step": index,
                    "code": "baseline_step_with_parameters",
                    "message": "Baseline plans use profile defaults and cannot set parameters.",
                }
                for index, step in enumerate(plan.steps)
                if step.config
            )
        per_detector: dict[str, int] = {}
        for step in plan.steps:
            per_detector[step.detector_id] = per_detector.get(step.detector_id, 0) + 1
        limit = self._limits.max_steps_per_detector
        errors.extend(
            {
                "code": "too_many_steps_for_detector",
                "message": f"Detector {detector_id!r} appears {count} times; the limit is {limit}.",
                "detector_id": detector_id,
            }
            for detector_id, count in sorted(per_detector.items())
            if count > limit
        )
        if source is PlannerKind.LLM:
            missing = sorted(set(self._registry.ids()) - set(per_detector))
            if missing:
                errors.append(
                    {
                        "code": "check_missing",
                        "message": "An adaptive plan must keep every registered check.",
                        "detector_ids": missing,
                    }
                )
        return errors


def step_config(
    registry: DetectorRegistry,
    profile: DomainProfile,
    detector_id: str,
    config: Mapping[str, Any],
) -> DetectorConfig:
    """The parameters a step runs with: the detector's code defaults, then the profile's
    ``detector_defaults`` for it, then the step's own ``config`` (later layers win, see
    :meth:`DetectorRegistry.resolve_config`). Raises :class:`DetectorConfigError`."""
    return registry.resolve_config(
        detector_id, [profile.detector_defaults.get(detector_id, {}), config]
    )


def profile_config(
    registry: DetectorRegistry, profile: DomainProfile, detector_id: str
) -> DetectorConfig | None:
    """The parameters a step that sets none runs with on ``profile`` (the baseline plan's
    steps), or ``None`` when the profile's parameters for the detector are invalid: such a
    step fails (:class:`ResolvedStep` with ``config=None``). Startup rejects profiles with
    invalid parameters, so a loaded profile always has a configuration here."""
    try:
        return step_config(registry, profile, detector_id, {})
    except DetectorConfigError:
        return None


def _config_error_text(profile: DomainProfile, exc: DetectorConfigError) -> str:
    """Readable summary of invalid profile parameters (keys and messages only; profiles are
    server-side configuration, so this text contains no document content)."""
    problems = [
        f"{'.'.join(str(part) for part in error.get('loc', [])) or '(root)'}: {error.get('msg')}"
        for error in exc.details.get("errors", [])[:5]
    ]
    listed = "; ".join(problems) or exc.message
    return (
        f"The parameters for this check in profile '{profile.profile_id}' "
        f"{profile.version} are invalid ({listed}). Fix the profile; the other checks ran."
    )[:500]
