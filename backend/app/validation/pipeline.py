"""Executes a validated plan against one dataset revision.

Guarantees:

* A detector that raises does not abort the run: it is reported as ``failed`` with a sanitized
  message (the exception type and a log reference; exception text can carry document content,
  so only messages written for users, from ``WorkbenchError``, are shown) and the other
  detectors still run. The full traceback goes to the server log under the same reference.
* Limits bound every run: each detector has a time limit (checked while it iterates rows) and
  finding caps (enforced when issues are created); a stopped detector keeps the findings it made
  and says why it stopped. Steps that would start after the run's time limit are skipped.
* Not-applicable detectors and detectors whose optional dependencies are missing are reported as
  ``skipped`` with reasons, never silently omitted.
* Issues must be the exact objects the run's issue factory created for that detector (so the
  evidence policy cannot be bypassed by building or editing issues), and every finding must
  satisfy the evidence rule (at least one evidence item; a confirmed rule violation points at a
  cell or a row), checked by the factory and again here; caps are enforced and reported. A
  detector that breaks an issue rule is ``failed`` with the rule it broke, and the other
  detectors still run. A detector that catches the factory's refusal itself and goes on is
  ``failed`` too, with the number of refused findings by rule; the findings the factory did
  accept are kept. Fingerprints are unique within a run: the factory rejects a second
  finding with the same fingerprint as a detector defect, so findings are never merged
  silently.
* A baseline step whose *profile* parameters are invalid fails on its own (``failed`` with
  the validation errors) and the other checks still run: a broken profile entry must not
  block basic validation. Plans from users or an LLM are rejected as a whole instead.
* A dataset whose extraction failed is not validated at all; a dataset whose extraction needs
  review is validated, and confirmed findings in affected tables carry a caveat.
* Run status: ``completed`` when no detector failed or stopped; ``completed_with_errors`` when
  some failed or stopped (a stopped detector keeps the findings it made); ``failed`` when
  every detector that executed failed.
"""

from __future__ import annotations

import importlib.util
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, TypedDict

from app.core.clock import Clock
from app.core.config import ValidationLimits
from app.core.errors import WorkbenchError
from app.core.ids import IdFactory
from app.models.bill_review import BillReview
from app.models.dataset import Dataset, ExtractionQuality
from app.models.issue import ValidationIssue
from app.models.material_answers import MaterialAnswers
from app.models.model_takeoff import ModelTakeoff
from app.models.plan import PlannerKind, ValidationPlan
from app.models.profile import DomainProfile
from app.models.run import DetectorExecutionStatus, DetectorRunReport, RunStatus
from app.models.tender import Tender
from app.validation.contracts.context import ValidationContext, build_validation_context
from app.validation.contracts.detector import DetectorConfig
from app.validation.contracts.issue_factory import IssuePolicyError, evidence_rule_problem
from app.validation.contracts.limits import (
    Deadline,
    DetectorStopped,
    TimeLimitReached,
)
from app.validation.plan_validation import PlanValidator, ResolvedStep
from app.validation.registry.registry import DetectorRegistry

logger = logging.getLogger(__name__)

_MAX_ERROR_CHARS = 500
_ERROR_PREFIX = "err"


class _ReportBase(TypedDict):
    """The fields every report of one executed step starts from."""

    detector_id: str
    detector_version: str
    config: dict[str, Any]
    rationale: str | None


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    status: RunStatus
    reports: list[DetectorRunReport]
    issues: list[ValidationIssue]
    warnings: list[str]


class ValidationPipeline:
    def __init__(
        self,
        registry: DetectorRegistry,
        *,
        ids: IdFactory,
        clock: Clock,
        limits: ValidationLimits,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._validator = PlanValidator(registry, limits)
        self._ids = ids
        self._clock = clock
        self._limits = limits
        self._monotonic = monotonic

    def execute(
        self,
        *,
        dataset: Dataset,
        document_id: str,
        profile: DomainProfile,
        plan: ValidationPlan,
        plan_source: PlannerKind,
        run_id: str,
        model: ModelTakeoff | None = None,
        material_answers: MaterialAnswers | None = None,
        bill_review: BillReview | None = None,
        tender: Tender | None = None,
    ) -> PipelineOutcome:
        """``plan_source`` is the planner that actually produced ``plan`` (decided by the
        caller's code path: a plan received over the API is ``user``)."""
        # raises PlanValidationError
        steps = self._validator.validate(plan, profile, source=plan_source)
        if dataset.extraction.quality is ExtractionQuality.FAILED:
            return PipelineOutcome(
                status=RunStatus.FAILED,
                reports=[],
                issues=[],
                warnings=[
                    "Extraction of this document failed, so no checks were run. Fix the "
                    "extraction (or the source file) before validating."
                ],
            )
        context = build_validation_context(
            dataset=dataset,
            document_id=document_id,
            profile=profile,
            run_id=run_id,
            limits=self._limits,
            ids=self._ids,
            clock=self._clock,
            monotonic=self._monotonic,
            model=model,
            material_answers=material_answers,
            bill_review=bill_review,
            tender=tender,
        )
        warnings = [*self._dataset_warnings(dataset), *_profile_warnings(dataset, profile)]
        reports: list[DetectorRunReport] = []
        issues: list[ValidationIssue] = []
        run_deadline = Deadline(self._limits.max_run_seconds, clock=self._monotonic)
        for resolved in steps:
            if resolved.config is None:  # reported even after the run limit: a profile bug
                reports.append(_invalid_profile_config(resolved))
                continue
            if run_deadline.expired:
                reports.append(_skipped_after_run_limit(resolved, self._limits.max_run_seconds))
                continue
            step_context = replace(
                context,
                deadline=Deadline(self._limits.max_detector_seconds, clock=self._monotonic),
            )
            report, produced = self._run_step(resolved, resolved.config, step_context)
            context.issues.release(resolved.detector.spec.detector_id)
            issues.extend(produced)
            reports.append(report)
        status = run_status(reports)
        unchecked = sum(r.coverage.get("rows_failed", 0) for r in reports)
        if unchecked:
            warnings.append(
                f"{unchecked} row check(s) could not be completed and were skipped; see the "
                "notes of each check."
            )
        if any(r.limit_reached for r in reports):
            warnings.append(
                "At least one check stopped at a run limit; its findings are incomplete."
            )
        return PipelineOutcome(status=status, reports=reports, issues=issues, warnings=warnings)

    # ------------------------------------------------------------------ helpers
    def _run_step(
        self, resolved: ResolvedStep, config: DetectorConfig, context: ValidationContext
    ) -> tuple[DetectorRunReport, list[ValidationIssue]]:
        spec = resolved.detector.spec
        base = _ReportBase(
            detector_id=spec.detector_id,
            detector_version=spec.version,
            config=config.model_dump(mode="json"),
            rationale=resolved.step.rationale,
        )
        missing = [dep for dep in spec.dependencies if importlib.util.find_spec(dep) is None]
        if missing:
            return (
                DetectorRunReport(
                    **base,
                    status=DetectorExecutionStatus.SKIPPED,
                    skipped_reasons=[f"Optional dependency not installed: {', '.join(missing)}."],
                ),
                [],
            )
        detector = resolved.detector()
        started = time.perf_counter()
        try:
            applicability = detector.applicability(context, config)
            if not applicability.applicable:
                return (
                    DetectorRunReport(
                        **base,
                        status=DetectorExecutionStatus.SKIPPED,
                        skipped_reasons=list(applicability.reasons),
                        duration_ms=_elapsed_ms(started),
                    ),
                    [],
                )
            result = detector.validate(context, config)
        except DetectorStopped as stop:
            return self._stopped(base, spec.detector_id, stop, context, started)
        except Exception as exc:  # isolation boundary: one detector must not stop the run
            reference = self._ids.new(_ERROR_PREFIX)
            logger.exception("Detector %s failed (reference %s)", spec.detector_id, reference)
            return (
                DetectorRunReport(
                    **base,
                    status=DetectorExecutionStatus.FAILED,
                    error=_sanitized_error(exc, reference),
                    duration_ms=_elapsed_ms(started),
                ),
                [],
            )
        rejected = _rejection(result.issues, spec.detector_id, context)
        if rejected is not None:
            return (
                DetectorRunReport(
                    **base,
                    status=DetectorExecutionStatus.FAILED,
                    error=rejected,
                    duration_ms=_elapsed_ms(started),
                ),
                [],
            )
        cap = self._limits.max_issues_per_detector
        kept = result.issues[:cap]
        dropped = len(result.issues) - len(kept)
        notes = list(result.notes)
        if dropped:
            notes.append(
                f"{dropped} further finding(s) not stored: per-detector limit of {cap} reached."
            )
        refused = context.issues.refusals(spec.detector_id)
        status = DetectorExecutionStatus.FAILED if refused else DetectorExecutionStatus.COMPLETED
        return (
            DetectorRunReport(
                **base,
                status=status,
                error=_refusal_error(refused) if refused else None,
                issues_found=len(kept),
                issues_dropped=dropped,
                duration_ms=_elapsed_ms(started),
                notes=notes,
                coverage=dict(result.coverage),
            ),
            kept,
        )

    def _stopped(
        self,
        base: _ReportBase,
        detector_id: str,
        stop: DetectorStopped,
        context: ValidationContext,
        started: float,
    ) -> tuple[DetectorRunReport, list[ValidationIssue]]:
        """Keep the (unmodified) findings made before a run limit stopped the detector. A
        detector that went on after the factory refused findings is ``failed`` all the same."""
        kept = [
            i
            for i in context.issues.created_by(detector_id)
            if context.issues.owns(i) and evidence_rule_problem(i) is None
        ]
        by_time = isinstance(stop, TimeLimitReached)
        note = str(stop) + (
            " Rows after that point were not checked."
            if by_time
            else " Further findings were not computed."
        )
        refused = context.issues.refusals(detector_id)
        if refused:
            status = DetectorExecutionStatus.FAILED
        elif by_time:
            status = DetectorExecutionStatus.STOPPED
        else:
            status = DetectorExecutionStatus.COMPLETED
        return (
            DetectorRunReport.model_validate(
                {
                    **base,
                    "status": status,
                    "error": _refusal_error(refused) if refused else None,
                    "issues_found": len(kept),
                    "limit_reached": "time" if by_time else "issues",
                    "duration_ms": _elapsed_ms(started),
                    "notes": [note],
                }
            ),
            kept,
        )

    @staticmethod
    def _dataset_warnings(dataset: Dataset) -> list[str]:
        if dataset.extraction.quality is ExtractionQuality.OK:
            return []
        codes = sorted({w.code for w in dataset.extraction.warnings if w.needs_review})
        return [
            "Extraction of this document needs review "
            f"({', '.join(codes) or 'see extraction report'}). Findings may reflect extraction "
            "problems rather than errors in the document."
        ]


def _rejection(
    issues: list[ValidationIssue], detector_id: str, context: ValidationContext
) -> str | None:
    """Why a detector's returned findings cannot enter the run, or ``None``: each must be the
    unmodified object the run's factory created for this detector, and satisfy the evidence
    rule."""
    for issue in issues:
        if (
            issue.detector_id != detector_id
            or issue.validation_run_id != context.run_id
            or not context.issues.owns(issue)
        ):
            return (
                "Detector returned issues that were not created by its issue factory for this "
                "run (or were modified afterwards)."
            )
    for issue in issues:
        problem = evidence_rule_problem(issue)
        if problem is not None:
            return f"Detector returned findings that break the evidence rule: {problem}."
    return None


def run_status(reports: list[DetectorRunReport]) -> RunStatus:
    """``failed`` only when every detector that executed failed; a stopped detector did run
    and keeps its findings, so it makes the run partial (``completed_with_errors``)."""
    failed = sum(r.status is DetectorExecutionStatus.FAILED for r in reports)
    stopped = sum(r.status is DetectorExecutionStatus.STOPPED for r in reports)
    completed = sum(r.status is DetectorExecutionStatus.COMPLETED for r in reports)
    if failed and not (completed or stopped):
        return RunStatus.FAILED
    if failed or stopped:
        return RunStatus.COMPLETED_WITH_ERRORS
    return RunStatus.COMPLETED


def _invalid_profile_config(resolved: ResolvedStep) -> DetectorRunReport:
    spec = resolved.detector.spec
    return DetectorRunReport(
        detector_id=spec.detector_id,
        detector_version=spec.version,
        status=DetectorExecutionStatus.FAILED,
        rationale=resolved.step.rationale,
        error=resolved.config_error
        or "The domain profile's parameters for this check are invalid.",
    )


def _profile_warnings(dataset: Dataset, profile: DomainProfile) -> list[str]:
    warnings = []
    if dataset.profile_id != profile.profile_id or dataset.profile_version != profile.version:
        warnings.append(
            f"The dataset was normalized with profile {dataset.profile_id} "
            f"{dataset.profile_version} but is validated with {profile.profile_id} "
            f"{profile.version}; re-normalize the document if the profile changed."
        )
    known = {f.field_id for f in profile.fields}
    unknown = sorted(
        {
            c.mapping.field_id
            for t in dataset.tables
            for c in t.columns
            if c.mapping is not None and c.mapping.field_id not in known
        }
    )
    if unknown:
        warnings.append(
            f"Columns are mapped to fields the profile does not define: {', '.join(unknown)}."
        )
    return warnings


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _sanitized_error(exc: Exception, reference: str) -> str:
    """User-facing error text: messages written for users (WorkbenchError) are kept, an issue
    rule a detector broke is named by its fixed reason (``IssuePolicyError.reason``); any other
    exception text may contain document content or internals and is replaced by a reference
    to the server log."""
    if isinstance(exc, IssuePolicyError):
        return (
            f"The issue policy rejected {exc.reason}, so this check was stopped "
            f"(reference {reference}; details are in the server log)."
        )
    if isinstance(exc, WorkbenchError):
        suffix = f" (reference {reference})"
        message = exc.message[: _MAX_ERROR_CHARS - len(suffix) - 1]
        if len(message) < len(exc.message):
            message += "…"
        return f"{message}{suffix}"
    return f"{type(exc).__name__} (reference {reference}; details are in the server log)"


def _refusal_error(refused: Mapping[str, int]) -> str:
    """The error of a detector that went on after the issue factory refused findings (it
    caught ``IssuePolicyError`` itself): how many were refused, by the fixed reason of the rule
    each broke (no document or caller values)."""
    total = sum(refused.values())
    listed = "; ".join(f"{count} × {reason}" for reason, count in sorted(refused.items()))
    return (
        f"The issue policy refused {total} finding{'' if total == 1 else 's'} of this check: "
        f"{listed}. The check went on without {'it' if total == 1 else 'them'}, so it is "
        "reported as failed; the findings it was allowed to make are kept."
    )


def _skipped_after_run_limit(resolved: ResolvedStep, seconds: float) -> DetectorRunReport:
    spec = resolved.detector.spec
    return DetectorRunReport(
        detector_id=spec.detector_id,
        detector_version=spec.version,
        status=DetectorExecutionStatus.SKIPPED,
        config=resolved.config.model_dump(mode="json") if resolved.config is not None else {},
        rationale=resolved.step.rationale,
        skipped_reasons=[f"The run reached its time limit of {seconds:g} s before this check."],
        limit_reached="time",
    )
