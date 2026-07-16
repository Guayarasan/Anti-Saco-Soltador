"""Implements every `/antidupe <subcommand>` behaviour.

Kept as a plain class (not an Endstone `Command` subclass) so it can be
unit-tested without a running server: `plugin.py` wires
`Plugin.on_command` to `AntiDupeCommandHandler.handle`.
"""

from __future__ import annotations

import logging

from endstone_antidupe.permissions import Permissions

HISTORY_PAGE_SIZE = 8


class AntiDupeCommandHandler:
    def __init__(
        self,
        *,
        config_loader,
        detector_registry,
        stats_service,
        translator,
        logger: logging.Logger | None = None,
    ):
        self._config_loader = config_loader
        self._registry = detector_registry
        self._stats = stats_service
        self._translator = translator
        self._logger = logger or logging.getLogger("antidupe.command")

    def handle(self, sender, args: list[str]) -> bool:
        if not sender.has_permission(Permissions.COMMAND_USE):
            sender.send_message(self._translator.t("command.no_permission"))
            return True

        if not args:
            self._help(sender)
            return True

        sub = args[0].lower()
        rest = args[1:]

        handlers = {
            "reload": self._reload,
            "stats": self._stats_cmd,
            "history": self._history,
            "toggle": self._toggle,
            "clear": self._clear,
            "metrics": self._metrics,
            "help": self._help,
        }
        handler = handlers.get(sub)
        if handler is None:
            sender.send_message(self._translator.t("command.unknown_subcommand"))
            return True

        handler(sender, rest)
        return True

    # -- subcommands ------------------------------------------------------

    def _help(self, sender, args: list[str] | None = None) -> None:
        sender.send_message(self._translator.t("command.help_header"))
        sender.send_message("§7/antidupe reload §f- reload config.yml")
        sender.send_message("§7/antidupe stats §f- show detection totals")
        sender.send_message("§7/antidupe history <player> [page] §f- show a player's history")
        sender.send_message("§7/antidupe toggle <detector> §f- enable/disable a detector")
        sender.send_message("§7/antidupe clear §f- wipe all stored detections")
        sender.send_message("§7/antidupe metrics §f- show internal performance metrics")

    def _reload(self, sender, args: list[str]) -> None:
        if not sender.has_permission(Permissions.COMMAND_RELOAD):
            sender.send_message(self._translator.t("command.no_permission"))
            return
        try:
            config = self._config_loader.reload()
            self._registry.reload(config)
            sender.send_message(self._translator.t("plugin.reload_success"))
        except Exception as exc:  # noqa: BLE001
            self._logger.error("Reload failed: %s", exc)
            sender.send_message(self._translator.t("plugin.reload_failed", error=str(exc)))

    def _stats_cmd(self, sender, args: list[str]) -> None:
        if not sender.has_permission(Permissions.COMMAND_STATS):
            sender.send_message(self._translator.t("command.no_permission"))
            return
        totals = self._stats.totals_by_detector()
        sender.send_message(self._translator.t("command.stats_header"))
        for detector in self._registry.all():
            count = totals.get(detector.detector_id, 0)
            sender.send_message(
                self._translator.t("command.stats_line", detector=detector.display_name, count=count)
            )
        sender.send_message(
            self._translator.t("command.stats_total", total=self._stats.total_detections())
        )

    def _history(self, sender, args: list[str]) -> None:
        if not sender.has_permission(Permissions.COMMAND_HISTORY):
            sender.send_message(self._translator.t("command.no_permission"))
            return
        if not args:
            sender.send_message("§cUsage: /antidupe history <player> [page]")
            return
        player_name = args[0]
        page = 0
        if len(args) > 1 and args[1].isdigit():
            page = max(0, int(args[1]) - 1)

        records = self._stats.history_for(player_name, limit=HISTORY_PAGE_SIZE, offset=page * HISTORY_PAGE_SIZE)
        if not records:
            sender.send_message(self._translator.t("command.player_not_found", player=player_name))
            return

        total_records = len(self._stats.history_for(player_name, limit=10_000))
        total_pages = max(1, (total_records + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)

        sender.send_message(
            self._translator.t(
                "command.history_header", player=player_name, page=page + 1, pages=total_pages
            )
        )
        for record in records:
            from datetime import datetime

            time_str = datetime.fromtimestamp(record.timestamp).strftime("%Y-%m-%d %H:%M")
            sender.send_message(
                self._translator.t(
                    "command.history_line",
                    time=time_str,
                    detector=record.detector_id,
                    x=int(record.position.x),
                    y=int(record.position.y),
                    z=int(record.position.z),
                    confidence=round(record.confidence_score),
                )
            )

    def _toggle(self, sender, args: list[str]) -> None:
        if not sender.has_permission(Permissions.COMMAND_TOGGLE):
            sender.send_message(self._translator.t("command.no_permission"))
            return
        if not args:
            sender.send_message("§cUsage: /antidupe toggle <detector>")
            return
        detector_id = args[0]
        detector = self._registry.get(detector_id)
        if detector is None:
            sender.send_message(self._translator.t("command.unknown_subcommand"))
            return
        new_state = not detector.enabled
        self._registry.set_enabled(detector_id, new_state)
        state_text = self._translator.t("state.enabled" if new_state else "state.disabled")
        sender.send_message(
            self._translator.t("command.toggle_detector", detector=detector_id, state=state_text)
        )

    def _clear(self, sender, args: list[str]) -> None:
        if not sender.has_permission(Permissions.COMMAND_CLEAR):
            sender.send_message(self._translator.t("command.no_permission"))
            return
        self._stats.clear_all()
        sender.send_message(self._translator.t("command.logs_cleared"))

    def _metrics(self, sender, args: list[str]) -> None:
        if not sender.has_permission(Permissions.COMMAND_METRICS):
            sender.send_message(self._translator.t("command.no_permission"))
            return
        # Populated by plugin.py via a bound attribute so this class
        # doesn't need to depend on MetricsCollector directly.
        snapshot = getattr(self, "_metrics_provider", lambda: {})()
        sender.send_message("§b=== AntiDupe Metrics ===")
        sender.send_message(f"§7Uptime: §f{snapshot.get('uptime_seconds', 0)}s")
        for name, value in snapshot.get("counters", {}).items():
            sender.send_message(f"§7{name}: §f{value}")
        for name, value in snapshot.get("avg_timing_ms", {}).items():
            sender.send_message(f"§7{name} (avg): §f{value}ms")

    def bind_metrics_provider(self, provider) -> None:
        self._metrics_provider = provider
