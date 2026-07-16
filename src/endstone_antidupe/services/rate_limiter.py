"""Per-subject sliding-window rate limiter.

Used to cap how many detections/actions a single player can trigger
per minute, so a scripted dupe-spam attempt can't flood logs, the
database, or chat with alerts.
"""

from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, max_events_per_window: int, window_seconds: float = 60.0):
        self._max_events = max_events_per_window
        self._window = window_seconds
        self._events: dict[str, deque] = {}

    def allow(self, subject: str) -> bool:
        now = time.monotonic()
        bucket = self._events.setdefault(subject, deque())
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max_events:
            return False
        bucket.append(now)
        return True

    def remaining(self, subject: str) -> int:
        bucket = self._events.get(subject)
        if not bucket:
            return self._max_events
        return max(0, self._max_events - len(bucket))

    def reset(self, subject: str) -> None:
        self._events.pop(subject, None)

    def set_max_events(self, max_events_per_window: int) -> None:
        self._max_events = max_events_per_window
