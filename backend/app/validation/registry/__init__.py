"""Detector registry and package discovery."""

from app.validation.registry.discovery import (
    DiscoveryResult,
    UnavailableModule,
    discover,
    discover_detector_classes,
)
from app.validation.registry.registry import DetectorDescriptor, DetectorRegistry, deep_merge

__all__ = [
    "DetectorDescriptor",
    "DetectorRegistry",
    "DiscoveryResult",
    "UnavailableModule",
    "deep_merge",
    "discover",
    "discover_detector_classes",
]
