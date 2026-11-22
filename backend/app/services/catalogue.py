"""System and catalogue: health, domain profiles and detector descriptors."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from app.core.errors import InvalidInputError, NotFoundError
from app.ingestion.pdf.ocr import TesseractOcr
from app.models.profile import DomainProfile
from app.schemas.catalogue import (
    AiPlannerStatus,
    CatalogueDetector,
    DetectorList,
    HealthResponse,
    LlmStatus,
    OcrStatusSummary,
    ProfileFieldSummary,
    ProfileList,
    ProfileSummary,
    UnavailableDetector,
)
from app.services import bill_reviews
from app.services.workbench import Workbench
from app.validation.plan_validation import profile_config
from app.validation.registry.registry import DetectorDescriptor

AI_PLANNER = AiPlannerStatus(
    configured=False,
    note=("Adaptive AI planning is not available in this version; every registered check runs."),
)


def _version() -> str:
    try:
        return version("tabular-integrity-workbench-backend")
    except PackageNotFoundError:
        return "0.1.0"


def health(wb: Workbench) -> HealthResponse:
    llm = wb.llm.status()
    return HealthResponse(
        status="ok",
        version=_version(),
        detector_count=len(wb.detectors.ids()),
        profiles=[profile.profile_id for profile in wb.profiles.list()],
        unavailable_detectors=[
            UnavailableDetector(
                module=module.module,
                missing_package=module.missing_package,
                message=module.message,
            )
            for module in wb.detectors.unavailable()
        ],
        ai_planner=AI_PLANNER,
        llm=LlmStatus(
            provider=wb.settings.llm.provider,
            model=llm.model,
            ready=llm.ready,
            reason=llm.reason,
            server_version=llm.server_version,
            model_digest=llm.model_digest,
        ),
        bill_review_available=bill_reviews.available(wb),
        default_profile_id=wb.settings.default_profile_id,
        auth_required=wb.settings.auth.required,
        ocr=_ocr(wb),
    )


def _ocr(wb: Workbench) -> OcrStatusSummary:
    status = TesseractOcr(wb.settings.ocr).status
    return OcrStatusSummary(
        available=status.available,
        engine=status.version,
        languages=wb.settings.ocr.languages,
        reason=status.reason,
    )


def profile_summary(profile: DomainProfile) -> ProfileSummary:
    return ProfileSummary(
        profile_id=profile.profile_id,
        name=profile.name,
        version=profile.version,
        description=profile.description,
        fields=[
            ProfileFieldSummary(
                field_id=field.field_id,
                label=field.label,
                data_type=field.data_type,
                role=field.role,
                required=field.required,
            )
            for field in profile.fields
        ],
        unit_count=len(profile.units),
    )


def profiles(wb: Workbench) -> ProfileList:
    return ProfileList(items=[profile_summary(profile) for profile in wb.profiles.list()])


def detectors(wb: Workbench, profile_id: str | None = None) -> DetectorList:
    """The catalogue; with ``profile_id``, each entry's ``profile_config`` on that profile."""
    profile = None if profile_id is None else _profile(wb, profile_id)
    return DetectorList(
        profile_id=None if profile is None else profile.profile_id,
        items=[_entry(wb, descriptor, profile) for descriptor in wb.detectors.catalogue()],
    )


def detector(wb: Workbench, detector_id: str, profile_id: str | None = None) -> CatalogueDetector:
    if detector_id not in wb.detectors.ids():
        raise NotFoundError(f"Unknown detector {detector_id!r}.")
    profile = None if profile_id is None else _profile(wb, profile_id)
    return _entry(wb, wb.detectors.describe(detector_id), profile)


def _profile(wb: Workbench, profile_id: str) -> DomainProfile:
    """The named profile; an unknown id is an invalid request (422), as for an upload."""
    try:
        return wb.profiles.get(profile_id)
    except NotFoundError as exc:
        available = sorted(profile.profile_id for profile in wb.profiles.list())
        raise InvalidInputError(
            str(exc), details={"profile_id": profile_id, "available": available}
        ) from None


def _entry(
    wb: Workbench, descriptor: DetectorDescriptor, profile: DomainProfile | None
) -> CatalogueDetector:
    """``descriptor`` with the parameters ``profile`` gives the detector (resolved as the plan
    validator resolves a step that sets none), serialized like ``default_config``."""
    config = (
        None
        if profile is None
        else profile_config(wb.detectors, profile, descriptor.spec.detector_id)
    )
    return CatalogueDetector(
        spec=descriptor.spec,
        parameters_schema=descriptor.parameters_schema,
        default_config=descriptor.default_config,
        plannable_parameters=descriptor.plannable_parameters,
        profile_config=None if config is None else config.model_dump(mode="json"),
    )
