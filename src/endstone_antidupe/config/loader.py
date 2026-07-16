"""Loads, merges and persists config.yml.

Design notes:
- We never crash the server if config.yml is missing, malformed or
  partially filled in: missing keys silently fall back to defaults
  and a warning is logged, so plugin startup can never take the
  server down.
- ``reload()`` re-reads the file from disk and swaps the in-memory
  ``PluginConfig`` atomically, which is what backs ``/antidupe reload``.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Callable

import yaml

from endstone_antidupe.config.models import PluginConfig

DEFAULT_CONFIG: dict = {
    "language": "en_US",
    "debug": False,
    "storage_backend": "sqlite",
    "max_logs": 500,
    "cache_ttl_seconds": 30,
    "rate_limit_per_minute": 120,
    "metrics_enabled": True,
    "disabled_worlds": [],
    "actions": {
        "on_low": ["log"],
        "on_medium": ["log", "alert"],
        "on_high": ["log", "alert", "remove_item"],
        "on_critical": ["log", "alert", "remove_item", "notify_severe"],
    },
    "detectors": {
        "bundle_container": {
            "enabled": True,
            "cooldown_seconds": 1.0,
            "thresholds": {"medium": 40, "high": 70, "critical": 90},
            "options": {
                "watched_containers": ["hopper", "dropper", "chest", "barrel"],
                "batch_size": 40,
                "batch_interval_ticks": 5,
                "fallback_scan_interval_ticks": 400,
            },
        },
        "bundle_ground": {
            "enabled": True,
            "cooldown_seconds": 5.0,
            "thresholds": {"medium": 30, "high": 60, "critical": 85},
            "options": {
                "scan_interval_ticks": 15,
                "scan_radius": 16,
            },
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigLoader:
    """Owns config.yml on disk and the parsed :class:`PluginConfig`."""

    def __init__(self, config_path: Path, logger: logging.Logger | None = None):
        self._path = config_path
        self._logger = logger or logging.getLogger("antidupe.config")
        self._config = PluginConfig.from_dict(DEFAULT_CONFIG)
        self._on_reload_callbacks: list[Callable[[PluginConfig], None]] = []

    @property
    def config(self) -> PluginConfig:
        return self._config

    def on_reload(self, callback: Callable[[PluginConfig], None]) -> None:
        """Register a callback fired after every successful reload/load."""
        self._on_reload_callbacks.append(callback)

    def load(self) -> PluginConfig:
        raw = self._read_raw()
        merged = _deep_merge(DEFAULT_CONFIG, raw)
        self._config = PluginConfig.from_dict(merged)
        if raw != merged:
            # File was missing keys added in a newer version; persist the
            # completed version so admins can see and edit every option.
            self._write_raw(merged)
        self._notify()
        return self._config

    def reload(self) -> PluginConfig:
        return self.load()

    def save(self, config: PluginConfig | None = None) -> None:
        target = config or self._config
        self._write_raw(target.raw)

    def _read_raw(self) -> dict:
        if not self._path.exists():
            self._logger.info(f"config.yml not found, creating defaults at {self._path}")
            self._write_raw(DEFAULT_CONFIG)
            return copy.deepcopy(DEFAULT_CONFIG)
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                raise ValueError("config.yml root must be a mapping")
            return data
        except Exception as exc:  # noqa: BLE001 - never let bad YAML crash the server
            self._logger.warning(
                f"Failed to parse config.yml ({exc}). Falling back to defaults."
            )
            return copy.deepcopy(DEFAULT_CONFIG)

    def _write_raw(self, data: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(f"Failed to write config.yml: {exc}")

    def _notify(self) -> None:
        for callback in self._on_reload_callbacks:
            try:
                callback(self._config)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(f"Config reload callback failed: {exc}")
