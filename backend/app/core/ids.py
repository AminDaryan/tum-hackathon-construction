"""Stable identifier generation.

Identifiers are opaque strings with a type prefix (``row_…``, ``iss_…``). They are assigned once,
persisted, and never derived from a displayed position, so sorting or filtering a view can never
change which cell an issue points at. Inject :class:`SequentialIdFactory` in tests for
reproducible ids.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Protocol


class IdPrefix:
    DOCUMENT = "doc"
    DATASET = "ds"
    TABLE = "tbl"
    COLUMN = "col"
    ROW = "row"
    RUN = "run"
    ISSUE = "iss"
    AUDIT = "aud"
    PLAN = "plan"
    EXPLANATION = "exp"


class IdFactory(Protocol):
    def new(self, prefix: str) -> str: ...


class RandomIdFactory:
    """Production id factory: ``<prefix>_<32 hex chars>`` from UUID4."""

    def new(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"


class SequentialIdFactory:
    """Deterministic id factory for tests: ``<prefix>_000001``, ``<prefix>_000002``, …"""

    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)

    def new(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}_{self._counters[prefix]:06d}"
