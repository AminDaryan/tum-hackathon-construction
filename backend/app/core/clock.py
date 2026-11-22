"""Injectable clock so timestamps are deterministic in tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Test clock that returns a fixed instant and only moves when told to."""

    def __init__(self, instant: datetime | None = None) -> None:
        self._instant = instant or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._instant

    def advance(self, seconds: float) -> None:
        self._instant += timedelta(seconds=seconds)
