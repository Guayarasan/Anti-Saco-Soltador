"""Confidence scoring model shared by every detector.

Every detector emits a numeric confidence score in the range [0, 100].
The score is then bucketed into a :class:`ConfidenceLevel`, which the
action pipeline uses to decide what should happen (log only, alert
admins, or trigger an automatic punishment). Thresholds are
configurable per detector, so the mapping below is only the default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ConfidenceLevel(IntEnum):
    """Discrete buckets a raw confidence score can fall into."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

    @classmethod
    def from_score(cls, score: float, thresholds: "ConfidenceThresholds") -> "ConfidenceLevel":
        if score >= thresholds.critical:
            return cls.CRITICAL
        if score >= thresholds.high:
            return cls.HIGH
        if score >= thresholds.medium:
            return cls.MEDIUM
        return cls.LOW


@dataclass(frozen=True, slots=True)
class ConfidenceThresholds:
    """Score cutoffs (0-100) used to bucket a raw score into a level."""

    medium: float = 40.0
    high: float = 70.0
    critical: float = 90.0

    @staticmethod
    def from_dict(data: dict) -> "ConfidenceThresholds":
        return ConfidenceThresholds(
            medium=float(data.get("medium", 40.0)),
            high=float(data.get("high", 70.0)),
            critical=float(data.get("critical", 90.0)),
        )
