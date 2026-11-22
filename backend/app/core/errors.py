"""Domain exception hierarchy.

Exceptions carry a stable machine-readable ``code`` and optional structured ``details``. They are
transport-agnostic: the API layer (``app.api.errors``) maps them to HTTP status codes and a single
error envelope, so services never import FastAPI.
"""

from __future__ import annotations

from typing import Any


class WorkbenchError(Exception):
    """Base class for all expected, user-facing errors."""

    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(WorkbenchError):
    code = "not_found"


class InvalidInputError(WorkbenchError):
    code = "invalid_input"


class FileRejectedError(InvalidInputError):
    """The uploaded file failed a security or format check and was not stored."""

    code = "file_rejected"


class UnsupportedFormatError(FileRejectedError):
    code = "unsupported_format"


class FileTooLargeError(FileRejectedError):
    code = "file_too_large"


class ExtractionError(WorkbenchError):
    """A supported file could not be read into a table structure."""

    code = "extraction_failed"


class ProfileError(WorkbenchError):
    """A domain profile is missing or invalid."""

    code = "invalid_profile"


class RegistryError(WorkbenchError):
    """A detector could not be registered (programming or packaging error)."""

    code = "registry_error"


class PlanValidationError(InvalidInputError):
    """A validation plan referenced unknown detectors, bad parameters or exceeded limits."""

    code = "invalid_validation_plan"


class UnknownDetectorError(PlanValidationError):
    code = "unknown_detector"


class DetectorConfigError(PlanValidationError):
    code = "invalid_detector_config"


class ConflictError(WorkbenchError):
    code = "conflict"


class ReviewTransitionError(ConflictError):
    code = "invalid_review_transition"


class UnavailableError(WorkbenchError):
    """The server cannot take the request now (it is shutting down, or busy); the client may
    try again later, after ``retry_after`` seconds when that is known."""

    code = "unavailable"
    retry_after: int | None = None
