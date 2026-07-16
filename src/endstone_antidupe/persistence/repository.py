"""Storage-agnostic repository contracts.

Everything above this layer (services, commands, detectors) talks to
these interfaces only. Swapping SQLite for MySQL/Postgres later means
writing one new class that implements :class:`DetectionRepository` --
nothing else in the plugin needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from endstone_antidupe.domain.models import Detection


class DetectionRepository(ABC):
    """Persists individual detection events and derived aggregates."""

    @abstractmethod
    def save(self, detection: Detection) -> None:
        """Persist a single detection record."""

    @abstractmethod
    def history_for(self, player_name: str, limit: int = 50, offset: int = 0) -> list[Detection]:
        """Return the most recent detections for a player, newest first."""

    @abstractmethod
    def recent(self, limit: int = 50) -> list[Detection]:
        """Return the most recent detections across all players."""

    @abstractmethod
    def count_by_detector(self) -> dict:
        """Return {detector_id: total_count} across all history."""

    @abstractmethod
    def count_by_player(self, limit: int = 15) -> list[tuple]:
        """Return [(player_name, count), ...] sorted descending, for a leaderboard."""

    @abstractmethod
    def total_count(self) -> int:
        """Return the total number of detections ever recorded."""

    @abstractmethod
    def clear(self) -> None:
        """Delete all stored detections (admin-triggered, irreversible)."""

    @abstractmethod
    def prune(self, keep_latest: int) -> None:
        """Trim history down to the ``keep_latest`` most recent rows."""

    @abstractmethod
    def close(self) -> None:
        """Release underlying resources (connections, file handles)."""
