"""Cooldown tracking: prevents a single exploit attempt from generating
a flood of duplicate detections/alerts within a short window.
"""

from __future__ import annotations

import time


class CooldownManager:
    def __init__(self):
        self._last_seen: dict[str, float] = {}

    @staticmethod
    def _key(scope: str, subject: str) -> str:
        return f"{scope}:{subject}"

    def is_ready(self, scope: str, subject: str, cooldown_seconds: float) -> bool:
        key = self._key(scope, subject)
        last = self._last_seen.get(key)
        if last is None:
            return True
        return (time.monotonic() - last) >= cooldown_seconds

    def mark(self, scope: str, subject: str) -> None:
        self._last_seen[self._key(scope, subject)] = time.monotonic()

    def try_consume(self, scope: str, subject: str, cooldown_seconds: float) -> bool:
        """Atomically check-and-mark. Returns True if the action should proceed."""
        if self.is_ready(scope, subject, cooldown_seconds):
            self.mark(scope, subject)
            return True
        return False

    def purge_older_than(self, seconds: float) -> None:
        cutoff = time.monotonic() - seconds
        stale = [k for k, ts in self._last_seen.items() if ts < cutoff]
        for k in stale:
            self._last_seen.pop(k, None)
