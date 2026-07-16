"""Aggregates detections into per-player profiles and totals.

Every detection is written to the repository immediately (SQLite
writes here are cheap, single-row inserts), but *reads* used for
hot-path decisions (e.g. "is this player a repeat offender?") are
served from the in-memory `PlayerProfile` cache to avoid a disk hit
on every interaction.
"""

from __future__ import annotations

import logging

from endstone_antidupe.domain.models import Detection, PlayerProfile
from endstone_antidupe.persistence.repository import DetectionRepository


class StatsService:
    def __init__(self, repository: DetectionRepository, logger: logging.Logger | None = None):
        self._repository = repository
        self._logger = logger or logging.getLogger("antidupe.stats")
        self._profiles: dict[str, PlayerProfile] = {}

    def record(self, detection: Detection) -> PlayerProfile:
        self._repository.save(detection)
        profile = self._profiles.get(detection.player_uuid)
        if profile is None:
            profile = PlayerProfile(
                player_uuid=detection.player_uuid,
                player_name=detection.player_name,
            )
            self._profiles[detection.player_uuid] = profile
        profile.player_name = detection.player_name
        profile.register(detection)
        return profile

    def profile(self, player_uuid: str, player_name: str = "") -> PlayerProfile:
        profile = self._profiles.get(player_uuid)
        if profile is None:
            profile = PlayerProfile(player_uuid=player_uuid, player_name=player_name)
            self._profiles[player_uuid] = profile
        return profile

    def totals_by_detector(self) -> dict:
        return self._repository.count_by_detector()

    def leaderboard(self, limit: int = 15) -> list[tuple]:
        return self._repository.count_by_player(limit=limit)

    def total_detections(self) -> int:
        return self._repository.total_count()

    def history_for(self, player_name: str, limit: int = 10, offset: int = 0) -> list[Detection]:
        return self._repository.history_for(player_name, limit=limit, offset=offset)

    def clear_all(self) -> None:
        self._repository.clear()
        self._profiles.clear()

    def prune(self, keep_latest: int) -> None:
        self._repository.prune(keep_latest)
