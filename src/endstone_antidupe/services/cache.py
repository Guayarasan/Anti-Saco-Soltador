"""Small generic TTL cache.

Detectors use this to avoid re-scanning the same containers/positions
every tick when nothing has changed since the last lookup.
"""

from __future__ import annotations

import time
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    def __init__(self, ttl_seconds: float = 30.0, max_entries: int = 5000):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: dict[K, tuple[float, V]] = {}

    def get(self, key: K, default: V | None = None) -> V | None:
        entry = self._store.get(key)
        if entry is None:
            return default
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return default
        return value

    def set(self, key: K, value: V, ttl_seconds: float | None = None) -> None:
        if len(self._store) >= self._max_entries:
            self._evict_oldest()
        expires_at = time.monotonic() + (ttl_seconds if ttl_seconds is not None else self._ttl)
        self._store[key] = (expires_at, value)

    def invalidate(self, key: K) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def _evict_oldest(self) -> None:
        if not self._store:
            return
        oldest_key = min(self._store, key=lambda k: self._store[k][0])
        self._store.pop(oldest_key, None)

    def __len__(self) -> int:
        return len(self._store)
