"""The detector registry: the only list of tools a planner (human, baseline or LLM) may use."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import Field, ValidationError

from app.core.errors import DetectorConfigError, RegistryError, UnknownDetectorError
from app.models.base import FrozenModel
from app.validation.contracts.detector import AnyDetector, DetectorConfig, DetectorSpec
from app.validation.registry.discovery import UnavailableModule, discover


class DetectorDescriptor(FrozenModel):
    """Serializable catalogue entry: spec, JSON schema of parameters, default parameters and
    the parameters a user or LLM plan may set (all others are controlled by the profile)."""

    spec: DetectorSpec
    parameters_schema: dict[str, Any]
    default_config: dict[str, Any]
    plannable_parameters: list[str] = Field(default_factory=list)


class DetectorRegistry:
    def __init__(
        self,
        detectors: Iterable[type[AnyDetector]] = (),
        *,
        unavailable: Iterable[UnavailableModule] = (),
    ) -> None:
        self._detectors: dict[str, type[AnyDetector]] = {}
        self._unavailable = list(unavailable)
        for detector in detectors:
            self.register(detector)

    @classmethod
    def from_packages(cls, packages: Sequence[str]) -> DetectorRegistry:
        found = discover(packages)
        return cls(found.detectors, unavailable=found.unavailable)

    def unavailable(self) -> list[UnavailableModule]:
        """Detector modules that could not be loaded (missing optional dependencies)."""
        return list(self._unavailable)

    def register(self, detector: type[AnyDetector]) -> None:
        spec = getattr(detector, "spec", None)
        if not isinstance(spec, DetectorSpec):
            raise RegistryError(f"{detector.__qualname__} does not declare a DetectorSpec")
        config_model = getattr(detector, "config_model", None)
        if not (isinstance(config_model, type) and issubclass(config_model, DetectorConfig)):
            raise RegistryError(f"{spec.detector_id}: config_model must subclass DetectorConfig")
        if config_model.model_config.get("extra") != "forbid":
            raise RegistryError(f"{spec.detector_id}: config_model must forbid unknown keys")
        try:
            config_model()
        except ValidationError as exc:
            raise RegistryError(
                f"{spec.detector_id}: every parameter needs a default ({exc.error_count()} missing)"
            ) from exc
        if spec.detector_id in self._detectors:
            raise RegistryError(f"Duplicate detector id {spec.detector_id!r}")
        self._detectors[spec.detector_id] = detector

    # ------------------------------------------------------------------ lookup
    def __contains__(self, detector_id: object) -> bool:
        return detector_id in self._detectors

    def __len__(self) -> int:
        return len(self._detectors)

    def ids(self) -> list[str]:
        return sorted(self._detectors)

    def get(self, detector_id: str) -> type[AnyDetector]:
        try:
            return self._detectors[detector_id]
        except KeyError:
            raise UnknownDetectorError(
                f"Unknown detector {detector_id!r}", details={"available": self.ids()}
            ) from None

    def specs(self) -> list[DetectorSpec]:
        return [self._detectors[i].spec for i in self.ids()]

    def describe(self, detector_id: str) -> DetectorDescriptor:
        detector = self.get(detector_id)
        return DetectorDescriptor(
            spec=detector.spec,
            parameters_schema=detector.config_model.model_json_schema(),
            default_config=detector.config_model().model_dump(mode="json"),
            plannable_parameters=sorted(detector.config_model.plannable_parameters()),
        )

    def catalogue(self) -> list[DetectorDescriptor]:
        return [self.describe(i) for i in self.ids()]

    # ------------------------------------------------------------------ config
    def resolve_config(
        self, detector_id: str, layers: Sequence[Mapping[str, Any]]
    ) -> DetectorConfig:
        """Deep-merge parameter layers and validate strictly against the config model.

        Later layers win. Nested mappings merge key by key (overriding ``tolerance.absolute``
        keeps the profile's ``tolerance.per_term_absolute``); lists and scalars replace."""
        detector = self.get(detector_id)
        merged: dict[str, Any] = {}
        for layer in layers:
            merged = deep_merge(merged, layer)
        try:
            return detector.config_model.model_validate(merged)
        except ValidationError as exc:
            raise DetectorConfigError(
                f"Invalid parameters for detector {detector_id!r}",
                details={
                    "detector_id": detector_id,
                    "errors": [
                        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                        for e in exc.errors(include_url=False, include_context=False)
                    ],
                },
            ) from exc


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursive merge of mappings; non-mapping values (including lists) replace."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged
