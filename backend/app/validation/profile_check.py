"""Check domain profiles against the detector registry (run at startup and in the tests).

A profile fixes parameter shapes for detectors (``detector_defaults``). A mistyped detector id
would otherwise be ignored silently (the detector would run with its code defaults, e.g.
another tolerance), and a parameter shape that no longer matches the detector's config model
would only show up when a run starts.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.core.errors import ProfileError, WorkbenchError
from app.models.profile import DomainProfile
from app.profiles.currency import default_vocabulary
from app.validation.registry.registry import DetectorRegistry


def profile_problems(profile: DomainProfile, registry: DetectorRegistry) -> list[str]:
    """Problems of one profile: unknown detector ids in ``detector_defaults`` and defaults the
    config model rejects."""
    problems: list[str] = []
    for detector_id in sorted(profile.detector_defaults):
        if detector_id not in registry:
            problems.append(f"detector_defaults names unknown detector {detector_id!r}")
            continue
        try:
            registry.resolve_config(detector_id, [profile.detector_defaults[detector_id]])
        except WorkbenchError as exc:
            errors = exc.details.get("errors", [])
            listed = "; ".join(
                f"{'.'.join(str(p) for p in e.get('loc', [])) or '(root)'}: {e.get('msg')}"
                for e in errors[:5]
            )
            problems.append(f"detector_defaults for {detector_id!r} are invalid ({listed})")
    return problems


def check_profiles(profiles: Iterable[DomainProfile], registry: DetectorRegistry) -> None:
    """Raise :class:`ProfileError` listing every problem of every profile (and when the shared
    currency vocabulary, ``app/profiles/data/currencies.yaml``, does not load)."""
    default_vocabulary()
    problems = {
        profile.profile_id: found
        for profile in profiles
        if (found := profile_problems(profile, registry))
    }
    if problems:
        summary = "; ".join(f"{pid}: {', '.join(found)}" for pid, found in problems.items())
        raise ProfileError(
            f"Domain profiles do not match the detector catalogue: {summary}",
            details={"problems": problems},
        )
