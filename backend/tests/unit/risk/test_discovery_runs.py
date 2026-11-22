"""The discovery-run store replaces a run's file whole, also while Windows reports it in use."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from app.risk import discovery_runs

REAL_REPLACE = os.replace


def _failing(times: int, calls: list[tuple[Path, Path]]) -> Callable[[Path, Path], None]:
    """An ``os.replace`` that fails as Windows does for the first ``times`` calls."""

    def fake_replace(source: Path, target: Path) -> None:
        calls.append((source, target))
        if len(calls) <= times:
            raise PermissionError(5, "Access is denied")
        REAL_REPLACE(source, target)

    return fake_replace


def test_a_target_in_use_is_replaced_once_it_is_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(discovery_runs.os, "replace", _failing(2, calls))
    monkeypatch.setattr(discovery_runs.time, "sleep", lambda _: None)
    source, target = tmp_path / ".run.json.part", tmp_path / "run.json"
    source.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")

    discovery_runs.replace(source, target)

    assert len(calls) == 3
    assert target.read_text(encoding="utf-8") == "new"
    assert not source.exists()


def test_a_lasting_permission_error_is_raised_after_the_last_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Path]] = []
    pauses: list[float] = []
    monkeypatch.setattr(discovery_runs.os, "replace", _failing(10_000, calls))
    monkeypatch.setattr(discovery_runs.time, "sleep", pauses.append)

    with pytest.raises(PermissionError):
        discovery_runs.replace(tmp_path / "a", tmp_path / "b")

    assert len(calls) == discovery_runs.REPLACE_ATTEMPTS
    assert pauses == [discovery_runs.REPLACE_PAUSE_SECONDS] * (discovery_runs.REPLACE_ATTEMPTS - 1)
