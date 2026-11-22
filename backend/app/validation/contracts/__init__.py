"""The contract every detector implements, and the read-only context it receives."""

from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.contracts.issue_factory import IssueFactory

__all__ = [
    "Applicability",
    "Detector",
    "DetectorCategory",
    "DetectorConfig",
    "DetectorResult",
    "DetectorSpec",
    "IssueFactory",
    "ValidationContext",
]
