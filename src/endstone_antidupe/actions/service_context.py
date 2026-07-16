"""Dependency bundle passed to every Action.execute() call.

Separate from detection.context.DetectionContext because actions run
strictly *after* a detection has been produced and only need the
output-facing services (persistence, alerting, metrics, logging) --
not the detection-facing ones (cooldowns, rate limiting, cache).
"""

from __future__ import annotations

from dataclasses import dataclass

from endstone_antidupe.services.alert_service import AlertService
from endstone_antidupe.services.metrics import MetricsCollector
from endstone_antidupe.services.stats_service import StatsService


@dataclass
class ActionServiceContext:
    stats_service: StatsService
    alert_service: AlertService
    metrics: MetricsCollector
    logger: object
