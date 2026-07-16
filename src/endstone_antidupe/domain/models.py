"""Plain data structures shared across the plugin.

Kept free of any Endstone import so the domain layer stays testable in
isolation and never depends on the game runtime.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from endstone_antidupe.domain.confidence import ConfidenceLevel


@dataclass(frozen=True, slots=True)
class Position:
    x: float
    y: float
    z: float
    dimension: str
    world: str = "default"

    def block_tuple(self) -> tuple:
        return (int(self.x) // 1, int(self.y), int(self.z))

    def as_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "dimension": self.dimension,
            "world": self.world,
        }


@dataclass(frozen=True, slots=True)
class Detection:
    """A single exploit attempt reported by a detector."""

    detector_id: str
    player_name: str
    player_uuid: str
    position: Position
    confidence_score: float
    confidence_level: ConfidenceLevel
    reason: str
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    detection_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(slots=True)
class PlayerProfile:
    """Aggregated, in-memory view of a player's dupe-related history.

    Backed by the repository layer but cached here so hot-path checks
    (cooldowns, repeat-offender scoring) never touch disk.
    """

    player_uuid: str
    player_name: str
    total_detections: int = 0
    detections_by_detector: dict = field(default_factory=dict)
    last_detection_at: float | None = None
    trust_penalty: float = 0.0

    def register(self, detection: Detection) -> None:
        self.total_detections += 1
        self.detections_by_detector[detection.detector_id] = (
            self.detections_by_detector.get(detection.detector_id, 0) + 1
        )
        self.last_detection_at = detection.timestamp
        # Repeat offenders slowly raise their own baseline suspicion,
        # which detectors may add on top of their raw score.
        self.trust_penalty = min(25.0, self.trust_penalty + 2.5)
