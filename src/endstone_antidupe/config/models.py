"""Typed views over the raw config.yml dict.

We intentionally keep configuration as plain dicts on disk (YAML) but
wrap access behind small dataclasses so the rest of the codebase never
does ``config["detectors"]["bundle_container"]["enabled"]`` by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from endstone_antidupe.domain.confidence import ConfidenceThresholds


@dataclass(slots=True)
class DetectorConfig:
    enabled: bool = True
    thresholds: ConfidenceThresholds = field(default_factory=ConfidenceThresholds)
    cooldown_seconds: float = 3.0
    options: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict) -> "DetectorConfig":
        data = data or {}
        return DetectorConfig(
            enabled=bool(data.get("enabled", True)),
            thresholds=ConfidenceThresholds.from_dict(data.get("thresholds", {})),
            cooldown_seconds=float(data.get("cooldown_seconds", 3.0)),
            options=data.get("options", {}) or {},
        )


@dataclass(slots=True)
class ActionRules:
    """Maps confidence levels to the actions that should fire."""

    on_low: list = field(default_factory=lambda: ["log"])
    on_medium: list = field(default_factory=lambda: ["log", "alert"])
    on_high: list = field(default_factory=lambda: ["log", "alert", "remove_item"])
    on_critical: list = field(default_factory=lambda: ["log", "alert", "remove_item", "notify_severe"])

    @staticmethod
    def from_dict(data: dict) -> "ActionRules":
        data = data or {}
        return ActionRules(
            on_low=list(data.get("on_low", ["log"])),
            on_medium=list(data.get("on_medium", ["log", "alert"])),
            on_high=list(data.get("on_high", ["log", "alert", "remove_item"])),
            on_critical=list(
                data.get("on_critical", ["log", "alert", "remove_item", "notify_severe"])
            ),
        )


@dataclass(slots=True)
class PluginConfig:
    language: str = "en_US"
    debug: bool = False
    storage_backend: str = "sqlite"
    max_logs: int = 500
    cache_ttl_seconds: int = 30
    rate_limit_per_minute: int = 120
    metrics_enabled: bool = True
    disabled_worlds: list = field(default_factory=list)
    detectors: dict = field(default_factory=dict)  # name -> DetectorConfig
    actions: ActionRules = field(default_factory=ActionRules)
    raw: dict = field(default_factory=dict)  # full original dict, for round-tripping

    @staticmethod
    def from_dict(data: dict) -> "PluginConfig":
        data = data or {}
        detectors_raw = data.get("detectors", {}) or {}
        detectors = {
            name: DetectorConfig.from_dict(cfg) for name, cfg in detectors_raw.items()
        }
        return PluginConfig(
            language=str(data.get("language", "en_US")),
            debug=bool(data.get("debug", False)),
            storage_backend=str(data.get("storage_backend", "sqlite")),
            max_logs=int(data.get("max_logs", 500)),
            cache_ttl_seconds=int(data.get("cache_ttl_seconds", 30)),
            rate_limit_per_minute=int(data.get("rate_limit_per_minute", 120)),
            metrics_enabled=bool(data.get("metrics_enabled", True)),
            disabled_worlds=list(data.get("disabled_worlds", []) or []),
            detectors=detectors,
            actions=ActionRules.from_dict(data.get("actions", {})),
            raw=data,
        )

    def detector_config(self, name: str) -> DetectorConfig:
        return self.detectors.get(name, DetectorConfig())

    def is_world_enabled(self, world_name: str) -> bool:
        return world_name not in self.disabled_worlds

    def actions_for(self, level_name: str) -> list:
        return getattr(self.actions, f"on_{level_name.lower()}", ["log"])
