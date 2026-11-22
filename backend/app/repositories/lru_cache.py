"""A small thread-safe least-recently-used cache.

The SQL adapter keeps decoded dataset revisions in one (keyed by ``(dataset_id, revision)``)
so repeated reads of a large dataset neither decompress nor re-validate it. It stores only
immutable models, which is what makes sharing entries between threads safe.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")

DEFAULT_MAX_ENTRIES = 8


@dataclass(frozen=True, slots=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int
    size: int
    max_entries: int


class LruCache(Generic[K, V]):
    """Keeps at most ``max_entries`` values; ``0`` disables caching. All methods are guarded
    by one lock, so the cache can be shared by FastAPI's worker threads."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 0:
            raise ValueError(f"max_entries must be >= 0, got {max_entries}")
        self._max_entries = max_entries
        self._entries: OrderedDict[K, V] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def get(self, key: K) -> V | None:
        """The cached value (now the most recently used one), or ``None`` on a miss."""
        with self._lock:
            try:
                value = self._entries[key]
            except KeyError:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: K, value: V) -> None:
        """Store ``value`` as the most recently used entry, evicting the least recently used
        entries beyond ``max_entries``."""
        if self._max_entries == 0:
            return
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                size=len(self._entries),
                max_entries=self._max_entries,
            )
