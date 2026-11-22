"""Test helpers for the formula, reference and unit detector tests (not a test module)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core.clock import FixedClock
from app.core.config import ValidationLimits
from app.core.ids import SequentialIdFactory
from app.models.dataset import Dataset
from app.models.issue import ValidationIssue
from app.models.plan import PlannerKind
from app.models.profile import DomainProfile
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import Applicability, Detector, DetectorResult
from app.validation.pipeline import PipelineOutcome, ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, make_context

BOQ_COLUMNS: list[tuple[str | None, str | None]] = [
    ("Pos.", "item_code"),
    ("Kurztext", "description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
    ("EP", "unit_price"),
    ("GP", "line_total"),
]


def boq_dataset(
    profile: DomainProfile,
    rows: Iterable[Sequence[Any]],
    *,
    name: str = "LV",
    columns: Sequence[tuple[str | None, str | None]] = BOQ_COLUMNS,
) -> Dataset:
    """One table of item rows with the BoQ columns (or ``columns``)."""
    builder = DatasetBuilder(profile)
    table = builder.table(name, columns)
    for values in rows:
        table.row(list(values))
    return builder.build()


def resolve(
    detector: type[Detector],
    profile: DomainProfile,
    overrides: Mapping[str, Any] | None = None,
) -> Any:
    """The detector's config from the profile defaults plus ``overrides`` (the same merge the
    pipeline applies; overrides here may also set profile-controlled parameters)."""
    registry = DetectorRegistry([detector])
    defaults = profile.detector_defaults.get(detector.spec.detector_id, {})
    return registry.resolve_config(detector.spec.detector_id, [defaults, dict(overrides or {})])


def run(
    detector: type[Detector],
    dataset: Dataset,
    profile: DomainProfile,
    overrides: Mapping[str, Any] | None = None,
    *,
    context: ValidationContext | None = None,
) -> DetectorResult:
    """Run one detector directly (after checking it is applicable)."""
    config = resolve(detector, profile, overrides)
    context = context or make_context(dataset, profile)
    instance = detector()
    applicability = instance.applicability(context, config)
    assert applicability.applicable, applicability.reasons
    return instance.validate(context, config)


def applicability(
    detector: type[Detector],
    dataset: Dataset,
    profile: DomainProfile,
    overrides: Mapping[str, Any] | None = None,
) -> Applicability:
    config = resolve(detector, profile, overrides)
    return detector().applicability(make_context(dataset, profile), config)


def run_pipeline(
    detector: type[Detector], dataset: Dataset, profile: DomainProfile
) -> PipelineOutcome:
    """A baseline run through the real pipeline with a registry holding only ``detector``."""
    registry = DetectorRegistry([detector])
    plan = BaselinePlanner(registry).plan(dataset, profile)
    pipeline = ValidationPipeline(
        registry, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
    )
    return pipeline.execute(
        dataset=dataset,
        document_id=dataset.document_id,
        profile=profile,
        plan=plan,
        plan_source=PlannerKind.BASELINE,
        run_id="run_test",
    )


def by_rule(issues: Iterable[ValidationIssue], rule_id: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.rule_id == rule_id]


def assert_unique_fingerprints(issues: Sequence[ValidationIssue]) -> None:
    fingerprints = [issue.fingerprint for issue in issues]
    assert len(fingerprints) == len(set(fingerprints))


def assert_well_formed(issues: Sequence[ValidationIssue]) -> None:
    """Shape rules every finding of these detectors must follow."""
    for issue in issues:
        assert 0 < len(issue.title) <= 200
        assert "col_" not in issue.title and "row_" not in issue.title  # no internal ids
        assert issue.explanation and issue.suggested_action
        assert issue.evidence
        assert issue.affected_cells or issue.row_id


LARGE_ROWS = 20_000
_LARGE: dict[str, Dataset] = {}


def large_boq_dataset(profile: DomainProfile) -> Dataset:
    """20,000 item rows shared by the performance tests (built once per profile; datasets are
    immutable). Codes 01.0000 to 20.0999; every 100th description refers to the next item;
    every 50th unit is the unknown 'VE'; every 200th quantity of pieces is fractional; every
    1000th line total is a formula error; descriptions repeat in 500 groups."""
    if profile.profile_id not in _LARGE:
        from tests.support.builders import error_cell, number_cell

        builder = DatasetBuilder(profile)
        table = builder.table("LV", BOQ_COLUMNS)
        units = ["m3", "m²", "Stk.", "psch", "lfm"]
        for n in range(LARGE_ROWS):
            code = f"{n // 1000 + 1:02d}.{n % 1000:04d}"
            description = f"Mauerwerk aus Kalksandstein Typ {n % 500}"
            if n % 100 == 0:
                following = n + 1
                description += f", wie Pos. {following // 1000 + 1:02d}.{following % 1000:04d}"
            unit = "VE" if n % 50 == 0 else units[n % len(units)]
            quantity = "2.5" if n % 200 == 2 else "2" if unit != "psch" else "1"
            total = (
                error_cell("#REF!")
                if n % 1000 == 0
                else number_cell("20.00", formula=f"=C{n + 2}*E{n + 2}")
            )
            table.row([code, description, quantity, unit, "10.00", total])
        _LARGE[profile.profile_id] = builder.build()
    return _LARGE[profile.profile_id]
