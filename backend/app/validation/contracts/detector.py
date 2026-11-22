"""Detector contract.

A detector is a small, stateless class that declares *what it is* (:class:`DetectorSpec`),
*what it accepts* (a strict :class:`DetectorConfig` subclass) and implements
``validate(context, config) -> DetectorResult``. It reads only the canonical dataset through
:class:`~app.validation.contracts.context.ValidationContext` and creates issues only through
``context.issues`` so ids, fingerprints and the evidence policy are applied uniformly.

Adding a detector = adding one module to a detector package. The pipeline, API, UI, exports and
database do not change.

Optional dependencies (scikit-learn, embeddings, ...) must be imported lazily inside
``validate()`` and declared in ``DetectorSpec.dependencies``: the pipeline then reports the
detector as skipped when the package is missing, and discovery never fails on import.

Parameters are *profile-controlled* unless marked plannable with :func:`plannable`. Profiles are
trusted server-side files; plans from users or (later) an LLM may set only plannable
parameters, so a plan can never widen a tolerance, swap a regular expression or switch a
reconciliation off.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.base import FrozenModel
from app.models.issue import (
    CATEGORY_PATTERN,
    DETECTOR_EVIDENCE_CLASSES,
    EvidenceClass,
    ValidationIssue,
)
from app.models.plan import DETECTOR_ID_PATTERN
from app.models.values import DataType

if TYPE_CHECKING:
    from app.validation.contracts.context import ValidationContext


class DetectorCategory(StrEnum):
    DETERMINISTIC = "deterministic"
    STATISTICAL = "statistical"
    MACHINE_LEARNING = "machine_learning"
    SEMANTIC = "semantic"
    DOMAIN = "domain"
    RESEARCH = "research"  # adapters for algorithms from papers (see docs/algorithms)


_SIGNAL_CLASSES = frozenset(
    {
        EvidenceClass.SUSPECTED_ANOMALY,
        EvidenceClass.EXTRACTION_UNCERTAINTY,
        EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
    }
)

# Which evidence classes each detector category may emit. Only rule-based categories may
# confirm a violation; statistical, ML and research methods produce signals, and semantic
# methods produce warnings. Nobody but a reviewer produces human_confirmed_error.
ALLOWED_EVIDENCE_CLASSES: dict[DetectorCategory, frozenset[EvidenceClass]] = {
    DetectorCategory.DETERMINISTIC: DETECTOR_EVIDENCE_CLASSES,
    DetectorCategory.DOMAIN: DETECTOR_EVIDENCE_CLASSES,
    DetectorCategory.STATISTICAL: _SIGNAL_CLASSES,
    DetectorCategory.MACHINE_LEARNING: _SIGNAL_CLASSES,
    DetectorCategory.RESEARCH: _SIGNAL_CLASSES,
    DetectorCategory.SEMANTIC: frozenset(
        {
            EvidenceClass.SEMANTIC_WARNING,
            EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            EvidenceClass.EXTRACTION_UNCERTAINTY,
        }
    ),
}


class DetectorSpec(FrozenModel):
    """Self-description used by the registry, the API catalogue and (later) the LLM planner."""

    detector_id: str = Field(pattern=DETECTOR_ID_PATTERN, max_length=128)
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    category: DetectorCategory
    description: str
    required_fields: tuple[str, ...] = ()  # semantic fields needed with default parameters
    optional_fields: tuple[str, ...] = ()  # used when mapped, e.g. currency
    supported_data_types: tuple[DataType, ...] = ()
    applicability: str  # human-readable applicability conditions
    evidence_classes: tuple[EvidenceClass, ...]
    issue_categories: tuple[str, ...]
    dependencies: tuple[str, ...] = ()  # importable Python packages beyond the core install
    limitations: tuple[str, ...] = ()
    license: str = "Project code (no third-party algorithm)"
    references: tuple[str, ...] = ()  # papers, standards, documentation
    cost: Literal["low", "medium", "high"] = "low"
    # Evaluation reports that document a calibration; required before any issue may carry an
    # AnomalyScore with calibrated=True (see app.models.issue.AnomalyScore).
    calibration_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _declared_behaviour_is_allowed(self) -> DetectorSpec:
        if not self.evidence_classes:
            raise ValueError("A detector must declare at least one evidence class")
        if not self.issue_categories:
            raise ValueError("A detector must declare at least one issue category")
        allowed = ALLOWED_EVIDENCE_CLASSES[self.category]
        disallowed = sorted(c.value for c in self.evidence_classes if c not in allowed)
        if disallowed:
            raise ValueError(
                f"{self.category.value} detectors may not emit {', '.join(disallowed)}"
            )
        bad = [c for c in self.issue_categories if not re.fullmatch(CATEGORY_PATTERN, c)]
        if bad:
            raise ValueError(f"Invalid issue categories: {bad}")
        return self


PLANNABLE_KEY = "plannable"


def plannable(default: Any = ..., **kwargs: Any) -> Any:
    """``Field(...)`` for a parameter that user and LLM plans may set (within its validation
    constraints). Use it for choices such as which field to check or a severity, never for
    tolerances, regular expressions or switches that turn a check off."""
    extra = dict(kwargs.pop("json_schema_extra", None) or {})
    extra[PLANNABLE_KEY] = True
    return Field(default, json_schema_extra=extra, **kwargs)


class DetectorConfig(BaseModel):
    """Base class for detector parameters. Unknown keys are rejected; every parameter must have
    a default so every run can run a detector without extra input. Parameters are
    profile-controlled unless declared with :func:`plannable`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @classmethod
    def plannable_parameters(cls) -> frozenset[str]:
        return frozenset(
            name
            for name, info in cls.model_fields.items()
            if isinstance(info.json_schema_extra, dict)
            and info.json_schema_extra.get(PLANNABLE_KEY) is True
        )


ConfigT = TypeVar("ConfigT", bound=DetectorConfig)


@dataclass(frozen=True, slots=True)
class Applicability:
    applicable: bool
    reasons: tuple[str, ...] = ()

    @classmethod
    def yes(cls, *reasons: str) -> Applicability:
        return cls(True, tuple(reasons))

    @classmethod
    def no(cls, *reasons: str) -> Applicability:
        return cls(False, tuple(reasons))


@dataclass(slots=True)
class DetectorResult:
    """What one detector execution produced.

    ``notes`` and ``coverage`` describe what was and was not checked (e.g.
    ``{"rows_checked": 120, "rows_skipped_missing_inputs": 4}``) so reviewers and the planner can
    see gaps instead of mistaking silence for a clean result.
    """

    issues: list[ValidationIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def count(self, key: str, amount: int = 1) -> None:
        self.coverage[key] = self.coverage.get(key, 0) + amount


class Detector(ABC, Generic[ConfigT]):
    """Base class for all detectors. Subclasses set ``spec`` and ``config_model``."""

    spec: ClassVar[DetectorSpec]
    config_model: ClassVar[type[DetectorConfig]] = DetectorConfig

    def required_fields(self, config: ConfigT) -> tuple[str, ...]:
        """Semantic fields needed for this configuration. Override when parameters choose
        the fields (e.g. a configurable ``quantity_field``)."""
        return self.spec.required_fields

    def applicability(self, context: ValidationContext, config: ConfigT) -> Applicability:
        """Default rule: applicable when at least one table maps every required field."""
        fields = self.required_fields(config)
        if not fields:
            return Applicability.yes("No mapped semantic fields are required.")
        tables = [t for t in context.dataset.tables if context.has_fields(t, *fields)]
        if tables:
            names = ", ".join(t.name for t in tables)
            return Applicability.yes(f"Fields {', '.join(fields)} are mapped in: {names}.")
        missing = sorted(
            {f for t in context.dataset.tables for f in fields if t.column_for_field(f) is None}
        )
        return Applicability.no(
            f"Required fields are not mapped in any table: {', '.join(missing)}."
        )

    @abstractmethod
    def validate(self, context: ValidationContext, config: ConfigT) -> DetectorResult:
        """Inspect the dataset and return issues. Must not mutate the dataset, perform I/O or
        keep state between calls."""


# A detector of any parameter model. The registry, the plan validator and the pipeline hold
# detectors with different config models side by side; each detector is only ever given the
# config its own ``config_model`` validated (``DetectorRegistry.resolve_config``).
AnyDetector = Detector[Any]
