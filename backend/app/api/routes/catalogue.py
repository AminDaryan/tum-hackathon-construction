"""System and catalogue: ``/health``, ``/profiles``, ``/detectors``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.routes._deps import workbench
from app.schemas.catalogue import CatalogueDetector, DetectorList, HealthResponse, ProfileList
from app.services import catalogue

router = APIRouter(tags=["system and catalogue"])


@router.get("/health")
def health(request: Request) -> HealthResponse:
    return catalogue.health(workbench(request))


@router.get("/profiles")
def profiles(request: Request) -> ProfileList:
    return catalogue.profiles(workbench(request))


ProfileQuery = Annotated[
    str | None,
    Query(
        description="A loaded domain profile: each entry then carries profile_config, the "
        "parameters a run on that profile uses when the plan sets none. An unknown id is "
        "rejected (422 invalid_input)."
    ),
]


@router.get("/detectors")
def detectors(request: Request, profile_id: ProfileQuery = None) -> DetectorList:
    return catalogue.detectors(workbench(request), profile_id)


@router.get("/detectors/{detector_id}")
def detector(
    request: Request, detector_id: str, profile_id: ProfileQuery = None
) -> CatalogueDetector:
    return catalogue.detector(workbench(request), detector_id, profile_id)
