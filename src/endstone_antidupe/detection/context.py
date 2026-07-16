"""Dependency bundle injected into every detector.

Detectors never reach into the plugin directly; they only see this
context, which keeps them independently testable and decoupled from
plugin bootstrapping order.
"""

from __future__ import annotations

from dataclasses import dataclass

from endstone_antidupe.actions.executor import ActionExecutor
from endstone_antidupe.config.models import PluginConfig
from endstone_antidupe.i18n.translator import Translator
from endstone_antidupe.services.cache import TTLCache
from endstone_antidupe.services.cooldown import CooldownManager
from endstone_antidupe.services.metrics import MetricsCollector
from endstone_antidupe.services.rate_limiter import RateLimiter


@dataclass
class DetectionContext:
    server: object
    config: PluginConfig
    translator: Translator
    cooldowns: CooldownManager
    rate_limiter: RateLimiter
    cache: TTLCache
    metrics: MetricsCollector
    action_executor: ActionExecutor
    logger: object
