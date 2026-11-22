"""Discover detector classes in configured packages.

Every public module of a detector package is imported and the concrete :class:`Detector`
subclasses *defined in that module* are collected. Packages are listed explicitly in
``Settings.detector_packages``, so discovery is configured, deterministic (sorted) and testable,
not an implicit global side effect.

A module that fails to import because an optional package is missing is recorded as
*unavailable* (shown in the catalogue and health check) instead of breaking the application.
Detector authors should import optional packages lazily inside ``validate()``; this is the
safety net for modules that do not.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.core.errors import RegistryError
from app.validation.contracts.detector import AnyDetector, Detector

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UnavailableModule:
    module: str
    missing_package: str
    message: str


@dataclass(slots=True)
class DiscoveryResult:
    detectors: list[type[AnyDetector]] = field(default_factory=list)
    unavailable: list[UnavailableModule] = field(default_factory=list)


def discover(packages: Iterable[str]) -> DiscoveryResult:
    result = DiscoveryResult()
    for package_name in packages:
        try:
            package = importlib.import_module(package_name)
        except ImportError as exc:
            raise RegistryError(
                f"Detector package {package_name!r} cannot be imported: {exc}"
            ) from exc
        if not hasattr(package, "__path__"):
            raise RegistryError(f"{package_name!r} is a module, not a package")
        for module_info in sorted(
            pkgutil.walk_packages(package.__path__, f"{package_name}."), key=lambda m: m.name
        ):
            if module_info.name.rsplit(".", 1)[-1].startswith("_"):
                continue
            try:
                module = importlib.import_module(module_info.name)
            except ModuleNotFoundError as exc:
                missing = exc.name or "unknown"
                if missing.split(".")[0] == "app":
                    raise  # a bug in our own code, not an optional dependency
                logger.warning("Detector module %s unavailable: %s", module_info.name, exc)
                result.unavailable.append(
                    UnavailableModule(
                        module=module_info.name,
                        missing_package=missing,
                        message=f"Optional dependency not installed: {missing}.",
                    )
                )
                continue
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, Detector)
                    and obj is not Detector
                    and not inspect.isabstract(obj)
                    and obj.__module__ == module.__name__
                ):
                    result.detectors.append(obj)
    result.detectors.sort(key=lambda cls: cls.spec.detector_id)
    return result


def discover_detector_classes(packages: Iterable[str]) -> list[type[AnyDetector]]:
    """Detector classes only (unavailable modules are logged and left out)."""
    return discover(packages).detectors
