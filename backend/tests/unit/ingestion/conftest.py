"""Shared fixtures for the ingestion tests."""

from __future__ import annotations

import pytest

from app.core.config import IngestionLimits


@pytest.fixture
def limits() -> IngestionLimits:
    """The default limits; tests that need a small limit build their own ``IngestionLimits``."""
    return IngestionLimits()
