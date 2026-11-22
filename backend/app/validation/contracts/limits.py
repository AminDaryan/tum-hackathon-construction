"""Run limits that stop a detector part-way (time and issue caps).

A detector never has to handle these: :class:`ValidationContext.rows` checks the deadline
while it iterates and the issue factory checks the caps when it creates an issue. Either one
raises a :class:`DetectorStopped` subclass, which the pipeline catches; it keeps the issues
the detector created so far and reports why the detector stopped.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


class DetectorStopped(Exception):
    """Base class: a run limit stopped the current detector."""


class IssueLimitReached(DetectorStopped):
    """The detector (or the whole run) reached its maximum number of issues."""


class TimeLimitReached(DetectorStopped):
    """The detector ran longer than its time limit."""


@dataclass(slots=True)
class Deadline:
    """Monotonic deadline; :meth:`check` raises :class:`TimeLimitReached` once it passed."""

    seconds: float
    clock: Callable[[], float] = time.monotonic
    started: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.started = self.clock()

    @property
    def expired(self) -> bool:
        return self.clock() - self.started > self.seconds

    def check(self) -> None:
        if self.expired:
            raise TimeLimitReached(f"Stopped after the time limit of {self.seconds:g} s.")
