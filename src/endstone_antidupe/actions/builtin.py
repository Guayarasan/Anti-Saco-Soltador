from __future__ import annotations

from endstone_antidupe.actions.action import Action
from endstone_antidupe.domain.models import Detection


class LogAction(Action):
    """Always-on action: writes the detection to the repository via
    the stats service and emits a console log line. Every detection
    should have at minimum this action so nothing is ever silently
    dropped, regardless of what other actions are configured.
    """

    name = "log"

    def execute(self, detection: Detection, detector, context) -> None:
        context.metrics.incr("actions.log")
        context.logger.info(
            "[%s] %s at (%.0f, %.0f, %.0f) in %s — confidence %.1f%% (%s)",
            detector.display_name,
            detection.player_name,
            detection.position.x,
            detection.position.y,
            detection.position.z,
            detection.position.dimension,
            detection.confidence_score,
            detection.confidence_level.name,
        )
        context.stats_service.record(detection)


class AlertAction(Action):
    """Broadcasts to online staff with the alerts permission."""

    name = "alert"

    def execute(self, detection: Detection, detector, context) -> None:
        context.metrics.incr("actions.alert")
        context.alert_service.broadcast(detection, detector.display_name)


class NotifySevereAction(Action):
    """Extra, louder broadcast reserved for CRITICAL-confidence hits."""

    name = "notify_severe"

    def execute(self, detection: Detection, detector, context) -> None:
        context.metrics.incr("actions.notify_severe")
        context.alert_service.broadcast_severe(detection, detector.display_name)


class RemoveItemAction(Action):
    """Delegates the actual item removal back to the detector.

    Removal is item/container-specific (a hopper slot vs. a dropped
    item entity are removed differently), so the generic action layer
    just calls a hook the detector provides via metadata -- this keeps
    world-mutation code colocated with the detector that found the
    exploit, while still letting config decide *whether* it happens.
    """

    name = "remove_item"

    def execute(self, detection: Detection, detector, context) -> None:
        callback = detection.metadata.get("_remove_callback")
        if callback is None:
            return
        try:
            callback()
            context.metrics.incr("actions.remove_item")
        except Exception as exc:  # noqa: BLE001
            context.logger.warning("remove_item action failed: %s", exc)
