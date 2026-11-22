"""System and catalogue responses: health, domain profiles and detector descriptors."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.models.profile import FieldRole
from app.models.values import DataType
from app.schemas.base import ResponseModel
from app.validation.registry.registry import DetectorDescriptor


class UnavailableDetector(ResponseModel):
    """A detector module that could not be loaded because an optional package is missing."""

    module: str
    missing_package: str
    message: str


class AiPlannerStatus(ResponseModel):
    configured: bool
    note: str


class LlmStatus(ResponseModel):
    provider: Literal["none", "ollama"]
    model: str | None = Field(description="The configured model, as the server names it.")
    ready: bool = Field(description="Whether the server answered and has the model installed.")
    reason: str | None = Field(
        description="Why the model is not ready: 'not configured', 'no model configured', "
        "'server not reachable', 'model not installed' or 'unexpected server response'."
    )
    server_version: str | None
    model_digest: str | None = Field(description="The digest the server reports for the model.")


class OcrStatusSummary(ResponseModel):
    """Text recognition for scanned PDF pages (Tesseract, run locally)."""

    available: bool
    engine: str | None = Field(description="The engine's version line, when it runs.")
    languages: str = Field(description="The configured language data, e.g. 'deu+eng'.")
    reason: str | None = Field(description="Why OCR is not available.")


class HealthResponse(ResponseModel):
    status: Literal["ok"]
    version: str
    detector_count: int = Field(ge=0)
    profiles: list[str] = Field(description="Ids of the loaded domain profiles.")
    unavailable_detectors: list[UnavailableDetector]
    ai_planner: AiPlannerStatus
    llm: LlmStatus = Field(description="The local language model; asked at most every 30 seconds.")
    bill_review_available: bool = Field(
        description="Whether a reviewer can send a bill to Claude for review: the server has an "
        "Anthropic key and the SDK. Nothing is sent to find out."
    )
    default_profile_id: str = Field(description="The profile used when an upload names none.")
    auth_required: bool = Field(
        description="Whether the other routes need 'Authorization: Bearer <token>'."
    )
    ocr: OcrStatusSummary


class ProfileFieldSummary(ResponseModel):
    field_id: str
    label: str
    data_type: DataType
    role: FieldRole
    required: bool


class ProfileSummary(ResponseModel):
    profile_id: str
    name: str
    version: str
    description: str
    fields: list[ProfileFieldSummary]
    unit_count: int = Field(ge=0, description="Units in the profile's unit catalogue.")


class ProfileList(ResponseModel):
    items: list[ProfileSummary]


class CatalogueDetector(DetectorDescriptor):
    """A catalogue entry, with the parameters the requested profile gives the detector."""

    profile_config: dict[str, Any] | None = Field(
        description="With the profile_id query parameter: the parameters a run on that profile "
        "uses for this detector when the plan sets none, that is default_config with the "
        "profile's detector_defaults for it merged over it, validated like a plan step. "
        "null without profile_id."
    )


class DetectorList(ResponseModel):
    profile_id: str | None = Field(
        description="The profile_id query parameter the items' profile_config was resolved "
        "for; null without it."
    )
    items: list[CatalogueDetector]
