"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.core.config import BUILTIN_PROFILE_DIR
from app.models.profile import DomainProfile
from app.profiles.loader import ProfileCatalog


@pytest.fixture(scope="session")
def profile_catalog() -> ProfileCatalog:
    return ProfileCatalog.from_directories([BUILTIN_PROFILE_DIR])


@pytest.fixture(scope="session")
def boq_profile(profile_catalog: ProfileCatalog) -> DomainProfile:
    return profile_catalog.get("boq")


@pytest.fixture(scope="session")
def generic_profile(profile_catalog: ProfileCatalog) -> DomainProfile:
    return profile_catalog.get("generic")
