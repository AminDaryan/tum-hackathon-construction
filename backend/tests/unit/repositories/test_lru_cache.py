"""The thread-safe LRU cache used for decoded dataset revisions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.repositories.lru_cache import CacheStats, LruCache
from app.repositories.sql import Database


def test_least_recently_used_entry_is_evicted() -> None:
    cache: LruCache[str, int] = LruCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # "b" is now the least recently used
    cache.put("c", 3)
    assert cache.get("b") is None
    assert (cache.get("a"), cache.get("c")) == (1, 3)
    assert cache.stats() == CacheStats(hits=3, misses=1, evictions=1, size=2, max_entries=2)


def test_put_refreshes_an_existing_key_without_eviction() -> None:
    cache: LruCache[str, int] = LruCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)  # evicts "b", the least recently used
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == (10, None, 3)


def test_zero_entries_disables_caching_and_negative_is_refused() -> None:
    disabled: LruCache[str, int] = LruCache(max_entries=0)
    disabled.put("a", 1)
    assert disabled.get("a") is None
    assert len(disabled) == 0
    with pytest.raises(ValueError, match="max_entries"):
        LruCache(max_entries=-1)


def test_clear_empties_the_cache_but_keeps_the_statistics() -> None:
    cache: LruCache[str, int] = LruCache()
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.clear()
    assert (len(cache), cache.get("a"), cache.get("b")) == (0, None, None)
    assert cache.stats() == CacheStats(hits=1, misses=2, evictions=0, size=0, max_entries=8)


def test_database_cache_defaults_to_eight_entries() -> None:
    assert LruCache().max_entries == 8
    with Database.in_memory_sqlite() as database:
        assert database.dataset_cache.max_entries == 8


def test_concurrent_use_keeps_the_cache_consistent() -> None:
    cache: LruCache[int, int] = LruCache(max_entries=16)

    def hammer(worker: int) -> None:
        for i in range(2_000):
            key = (worker * 7 + i) % 40
            cache.put(key, key * 2)
            value = cache.get(key)
            assert value is None or value == key * 2

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(hammer, range(8)))
    stats = cache.stats()
    assert stats.size == len(cache) <= 16
    assert stats.hits + stats.misses == 8 * 2_000
