"""Base contract every detector must implement.

Adding a new exploit detector to the plugin means writing exactly one
new class that implements this interface and registering it in
plugin.py -- nothing in the scheduler, action pipeline, commands, or
persistence layer needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from endstone_antidupe.config.models import DetectorConfig
from endstone_antidupe.detection.context import DetectionContext
from endstone_antidupe.domain.confidence import ConfidenceLevel
from endstone_antidupe.domain.models import Detection


class Detector(ABC):
    """A single exploit-detection strategy.

    Subclasses are responsible only for *finding* exploit attempts and
    reporting them via ``self.report(...)``. Everything downstream
    (cooldowns, rate limiting, confidence bucketing, persistence,
    alerting, and automatic actions) is handled centrally so every
    detector behaves consistently.
    """

    #: Stable identifier used in config.yml, permissions, and storage.
    #: Must never change across versions once released (migrations
    #: would be needed otherwise).
    detector_id: str = "unset"

    #: Human-readable name shown in chat alerts / commands. Looked up
    #: from the locale catalog by default via `display_name`.
    def __init__(self, context: DetectionContext):
        self.context = context
        self.detector_config: DetectorConfig = context.config.detector_config(self.detector_id)

    @property
    def display_name(self) -> str:
        return self.context.translator.t(f"detector.{self.detector_id}.name")

    @property
    def enabled(self) -> bool:
        return self.detector_config.enabled

    def refresh_config(self, config) -> None:
        """Called on `/antidupe reload` so live config changes apply
        without requiring a server restart."""
        self.detector_config = config.detector_config(self.detector_id)
        self.on_config_reloaded()

    def on_config_reloaded(self) -> None:
        """Hook for subclasses that cache derived config values."""

    @abstractmethod
    def register(self) -> None:
        """Wire up event listeners / schedule periodic tasks.

        Called once during plugin startup. Detectors that only need
        event hooks (no polling) can leave scheduling out entirely.
        """

    @abstractmethod
    def unregister(self) -> None:
        """Undo whatever `register()` set up. Called on plugin disable."""

    def report(
        self,
        *,
        player,
        position,
        raw_score: float,
        reason: str,
        metadata: dict | None = None,
        cooldown_subject: str | None = None,
    ) -> Detection | None:
        """Common entry point every detector calls when it finds a hit.

        Applies cooldown + rate limiting, buckets the confidence
        score, then hands the resulting :class:`Detection` to the
        action executor. Returns None if the report was suppressed by
        cooldown/rate limiting so callers can skip extra work (e.g.
        item removal) when appropriate -- though removal of the
        exploited item itself should generally happen regardless of
        whether the *report* is suppressed, since silently leaving the
        dupe item in place would defeat the detector.
        """
        subject = cooldown_subject or getattr(player, "unique_id", None) or getattr(player, "name", "unknown")
        subject = str(subject)

        if not self.context.cooldowns.try_consume(self.detector_id, subject, self.detector_config.cooldown_seconds):
            return None

        player_name = getattr(player, "name", "unknown")
        if not self.context.rate_limiter.allow(player_name):
            self.context.logger.debug("Rate limit reached for %s, suppressing report", player_name)
            return None

        level = ConfidenceLevel.from_score(raw_score, self.detector_config.thresholds)
        player_uuid = str(getattr(player, "unique_id", player_name))

        detection = Detection(
            detector_id=self.detector_id,
            player_name=player_name,
            player_uuid=player_uuid,
            position=position,
            confidence_score=raw_score,
            confidence_level=level,
            reason=reason,
            metadata=metadata or {},
        )

        self.context.metrics.incr(f"detections.{self.detector_id}")
        self.context.action_executor.execute(detection, self)
        return detection
