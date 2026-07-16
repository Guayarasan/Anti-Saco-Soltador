"""Lightweight metrics collector.

Not a Prometheus client -- just enough bookkeeping to answer
"is this plugin healthy and cheap?" via `/antidupe metrics`, without
adding a heavy dependency to a game-server plugin.
"""

from __future__ import annotations

import time
from collections import defaultdict


class MetricsCollector:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._counters: dict[str, int] = defaultdict(int)
        self._timings_total: dict[str, float] = defaultdict(float)
        self._timings_count: dict[str, int] = defaultdict(int)
        self._started_at = time.monotonic()

    def incr(self, name: str, amount: int = 1) -> None:
        if not self.enabled:
            return
        self._counters[name] += amount

    def record_timing(self, name: str, duration_seconds: float) -> None:
        if not self.enabled:
            return
        self._timings_total[name] += duration_seconds
        self._timings_count[name] += 1

    def timer(self, name: str) -> "_TimerContext":
        return _TimerContext(self, name)

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def snapshot(self) -> dict:
        avg_timings = {
            name: (self._timings_total[name] / self._timings_count[name]) * 1000
            for name in self._timings_count
            if self._timings_count[name] > 0
        }
        return {
            "uptime_seconds": round(self.uptime_seconds(), 1),
            "counters": dict(self._counters),
            "avg_timing_ms": {k: round(v, 3) for k, v in avg_timings.items()},
        }


class _TimerContext:
    def __init__(self, collector: MetricsCollector, name: str):
        self._collector = collector
        self._name = name
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._collector.record_timing(self._name, time.perf_counter() - self._start)
        return False
