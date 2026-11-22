"""The detector catalogue page (``docs/architecture/detector-catalogue.md``), rendered from the
registered detectors' specs so it cannot drift from the code. A test compares the committed page
with :func:`render`. Regenerate it from ``backend/`` by redirecting the output of
``.venv/bin/python -m app.validation.catalogue_markdown`` into
``../docs/architecture/detector-catalogue.md``.
"""

from __future__ import annotations

import json

from app.core.config import Settings
from app.models.finding_category import (
    CATEGORY_BY_DETECTOR,
    CATEGORY_BY_RULE,
    FindingCategory,
)
from app.validation.contracts.detector import AnyDetector
from app.validation.registry import DetectorRegistry


def _items(values: tuple[str, ...] | tuple[object, ...]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def _default(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _category(category: FindingCategory | None) -> str:
    return f"`{category.value}`" if category is not None else "none (reading the file)"


def _finding_category(detector_id: str) -> str:
    """The detector's finding category, then each rule whose category differs from it."""
    rules = [
        f"rule `{rule_id}`: {_category(category)}"
        for (detector, rule_id), category in sorted(CATEGORY_BY_RULE.items())
        if detector == detector_id
    ]
    return "; ".join([_category(CATEGORY_BY_DETECTOR.get(detector_id)), *rules])


def _parameters(detector: type[AnyDetector]) -> list[str]:
    """One line per config parameter: name, who may set it, code default, description."""
    model = detector.config_model
    plannable = model.plannable_parameters()
    defaults = model().model_dump(mode="json")
    return [
        f"  - `{name}` ({'plan or profile' if name in plannable else 'profile'}): "
        f"`{_default(defaults[name])}`" + (f". {info.description}" if info.description else "")
        for name, info in model.model_fields.items()
    ]


def render(registry: DetectorRegistry) -> str:
    specs = sorted(
        (registry.get(detector_id).spec for detector_id in registry.ids()),
        key=lambda spec: spec.detector_id,
    )
    lines = [
        "# Detector catalogue",
        "",
        "Generated from the detectors' specs (`backend/app/validation/catalogue_markdown.py`); "
        "do not edit by hand. Every detector is deterministic, runs locally and uses no paid "
        "service. Every validation runs every detector (ADR 0010); a detector that does not "
        "apply to a dataset reports why.",
        "Parameters show their code defaults; a profile's `detector_defaults` may set any of "
        "them, an LLM plan only those marked *plan or profile*. "
        "`GET /api/v1/detectors?profile_id=<id>` returns the values a profile gives them "
        "(`profile_config`).",
        "The finding category of a finding (`finding_category`) is its detector's, or its "
        "rule's where the two differ (`backend/app/models/finding_category.py`); none means "
        'that the finding is about reading the file ("Reading the file"). The evidence class '
        "does not change it: a finding the evidence policy downgraded to "
        "`extraction_uncertainty` keeps its category.",
        "",
        "| Detector | Category | Finding category | Cost |",
        "| --- | --- | --- | --- |",
    ]
    for spec in specs:
        anchor = spec.detector_id.replace(".", "")  # GitHub drops dots, keeps underscores
        lines.append(
            f"| [{spec.name}](#{anchor}) | `{spec.category.value}` | "
            f"{_category(CATEGORY_BY_DETECTOR.get(spec.detector_id))} | {spec.cost} |"
        )
    for spec in specs:
        lines += [
            "",
            f"## {spec.detector_id}",
            "",
            f"**{spec.name}** (version {spec.version}). {spec.description}",
            "",
            f"- Applies when: {spec.applicability}",
            f"- Required fields: {_items(spec.required_fields)}; optional: "
            f"{_items(spec.optional_fields)}",
            f"- Evidence classes: {_items(tuple(c.value for c in spec.evidence_classes))}",
            f"- Issue categories: {_items(spec.issue_categories)}",
            f"- Finding category: {_finding_category(spec.detector_id)}",
        ]
        if spec.limitations:
            lines.append("- Limitations:")
            lines += [f"  - {limitation}" for limitation in spec.limitations]
        if spec.references:
            lines.append(f"- References: {'; '.join(spec.references)}")
        parameters = _parameters(registry.get(spec.detector_id))
        if parameters:
            lines.append("- Parameters:")
            lines += parameters
    return "\n".join(lines) + "\n"


def main() -> None:
    print(render(DetectorRegistry.from_packages(Settings().detector_packages)), end="")


if __name__ == "__main__":
    main()
