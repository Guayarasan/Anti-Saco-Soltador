"""AntiDupe plugin entry point.

Responsible only for bootstrapping: constructing every service in
dependency order, wiring the action pipeline, registering detectors,
and exposing the `/antidupe` command. All actual logic lives in the
layers under `endstone_antidupe/*` so this file stays short and is the
one place that must change if Endstone's Plugin base class API shifts.
"""

from __future__ import annotations

import logging
from pathlib import Path

from endstone.plugin import Plugin

from endstone_antidupe.actions.builtin import (
    AlertAction,
    LogAction,
    NotifySevereAction,
    RemoveItemAction,
)
from endstone_antidupe.actions.executor import ActionExecutor
from endstone_antidupe.actions.service_context import ActionServiceContext
from endstone_antidupe.commands.antidupe_command import AntiDupeCommandHandler
from endstone_antidupe.config.loader import ConfigLoader
from endstone_antidupe.detection.context import DetectionContext
from endstone_antidupe.detection.detectors import ALL_DETECTORS
from endstone_antidupe.detection.registry import DetectorRegistry
from endstone_antidupe.i18n.translator import Translator
from endstone_antidupe.permissions import PERMISSION_DEFINITIONS, Permissions
from endstone_antidupe.persistence.database import Database
from endstone_antidupe.persistence.sqlite_repository import SQLiteDetectionRepository
from endstone_antidupe.services.alert_service import AlertService
from endstone_antidupe.services.cache import TTLCache
from endstone_antidupe.services.cooldown import CooldownManager
from endstone_antidupe.services.metrics import MetricsCollector
from endstone_antidupe.services.rate_limiter import RateLimiter
from endstone_antidupe.services.stats_service import StatsService


class AntiDupePlugin(Plugin):
    api_version = "0.11"

    name = "AntiDupe"
    version = "1.0.0"
    description = "Modular, production-grade anti-duplication framework."

    commands = {
        "antidupe": {
            "description": "Manage the AntiDupe plugin.",
            "usages": ["/antidupe (reload|stats|history|toggle|clear|metrics|help)<action: AntiDupeAction>"],
            "permissions": [Permissions.COMMAND_USE],
        }
    }

    permissions = PERMISSION_DEFINITIONS

    def on_load(self) -> None:
        self.logger.info("AntiDupe loading...")

    def on_enable(self) -> None:
        try:
            self._bootstrap()
        except Exception as exc:  # noqa: BLE001 - startup must never crash the server
            self.logger.error("AntiDupe failed to start cleanly: %s", exc, exc_info=True)
            return

        active = self._registry.register_all()
        self.logger.info(
            self._translator.t("plugin.enabled", detector_count=active)
        )

    def on_disable(self) -> None:
        try:
            self._registry.unregister_all()
            self._repository.close()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Error during shutdown: %s", exc)
        self.logger.info(self._translator.t("plugin.disabled"))

    def on_command(self, sender, command, args) -> bool:  # noqa: ARG002 - `command` required by API
        return self._command_handler.handle(sender, list(args))

    # -- bootstrap -----------------------------------------------------------

    def _bootstrap(self) -> None:
        data_dir = Path(self.data_folder)
        data_dir.mkdir(parents=True, exist_ok=True)

        self._config_loader = ConfigLoader(data_dir / "config.yml", logger=self.logger)
        config = self._config_loader.load()

        locales_dir = Path(__file__).parent / "resources" / "locales"
        if not locales_dir.exists():
            # Editable/source installs keep locales next to the repo root
            # resources/ folder instead of packaged inside the wheel.
            locales_dir = Path(__file__).parent.parent.parent / "resources" / "locales"
        self._translator = Translator(locales_dir, config.language, logger=self.logger)

        self._database = Database(data_dir / "antidupe.db", logger=self.logger)
        self._repository = SQLiteDetectionRepository(self._database, logger=self.logger)
        self._stats_service = StatsService(self._repository, logger=self.logger)
        self._alert_service = AlertService(self.server, self._translator, logger=self.logger)
        self._metrics = MetricsCollector(enabled=config.metrics_enabled)
        self._cooldowns = CooldownManager()
        self._rate_limiter = RateLimiter(max_events_per_window=config.rate_limit_per_minute)
        self._cache = TTLCache(ttl_seconds=config.cache_ttl_seconds)

        self._action_executor = ActionExecutor(config, logger=self.logger)
        self._action_executor.service_context = ActionServiceContext(
            stats_service=self._stats_service,
            alert_service=self._alert_service,
            metrics=self._metrics,
            logger=self.logger,
        )
        for action in (LogAction(), AlertAction(), NotifySevereAction(), RemoveItemAction()):
            self._action_executor.register_action(action)

        detection_context = DetectionContext(
            server=self.server,
            owner=self,
            config=config,
            translator=self._translator,
            cooldowns=self._cooldowns,
            rate_limiter=self._rate_limiter,
            cache=self._cache,
            metrics=self._metrics,
            action_executor=self._action_executor,
            logger=self.logger,
        )
        self._registry = DetectorRegistry(detection_context, ALL_DETECTORS)

        self._command_handler = AntiDupeCommandHandler(
            config_loader=self._config_loader,
            detector_registry=self._registry,
            stats_service=self._stats_service,
            translator=self._translator,
            logger=self.logger,
        )
        self._command_handler.bind_metrics_provider(self._metrics.snapshot)

        self._config_loader.on_reload(self._on_config_reloaded)

        # Periodically release stale cooldown/rate-limit entries so
        # memory use stays flat on servers running for months.
        self.server.scheduler.run_task(
            self, self._housekeeping, delay=1200, period=1200
        )

    def _on_config_reloaded(self, config) -> None:
        self._translator.set_language(config.language)
        self._action_executor.refresh_config(config)
        self._metrics.enabled = config.metrics_enabled
        self._rate_limiter.set_max_events(config.rate_limit_per_minute)

    def _housekeeping(self) -> None:
        try:
            self._cooldowns.purge_older_than(3600)
            self._stats_service.prune(keep_latest=max(500, self._config_loader.config.max_logs))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Housekeeping task failed: %s", exc)
