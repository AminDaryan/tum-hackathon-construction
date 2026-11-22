"""Load and validate domain profiles from YAML files (``yaml.safe_load`` only)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.errors import NotFoundError, ProfileError
from app.models.profile import DomainProfile


def load_profile(path: Path) -> DomainProfile:
    """Parse one profile file. Raises :class:`ProfileError` with the file name on any problem."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"Cannot read profile {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"Profile {path.name} must contain a mapping at the top level")
    try:
        return DomainProfile.model_validate(data)
    except ValidationError as exc:
        raise ProfileError(
            f"Profile {path.name} is invalid",
            details={"errors": exc.errors(include_url=False, include_context=False)},
        ) from exc


class ProfileCatalog:
    """In-memory catalogue of validated profiles keyed by ``profile_id``."""

    def __init__(self, profiles: Iterable[DomainProfile]) -> None:
        self._profiles: dict[str, DomainProfile] = {}
        for profile in profiles:
            if profile.profile_id in self._profiles:
                raise ProfileError(f"Duplicate profile id {profile.profile_id!r}")
            self._profiles[profile.profile_id] = profile

    @classmethod
    def from_directories(cls, directories: Iterable[Path]) -> ProfileCatalog:
        profiles: list[DomainProfile] = []
        for directory in directories:
            if not directory.is_dir():
                raise ProfileError(f"Profile directory {directory} does not exist")
            profiles.extend(load_profile(path) for path in sorted(directory.glob("*.yaml")))
        return cls(profiles)

    def get(self, profile_id: str) -> DomainProfile:
        try:
            return self._profiles[profile_id]
        except KeyError:
            raise NotFoundError(
                f"Unknown domain profile {profile_id!r}",
                details={"available": sorted(self._profiles)},
            ) from None

    def list(self) -> list[DomainProfile]:
        return [self._profiles[key] for key in sorted(self._profiles)]
