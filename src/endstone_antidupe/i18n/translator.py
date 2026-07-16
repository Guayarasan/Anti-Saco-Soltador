"""Minimal i18n layer: dotted-key YAML lookups with a safe fallback.

Kept intentionally simple (no pluralization engine, no ICU) because
the plugin's surface area is server logs and short chat messages.
It's still fully pluggable: dropping a new ``xx_XX.yml`` file in the
locales folder and setting ``language: xx_XX`` in config.yml is enough
to add a language, no code changes required.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

FALLBACK_LOCALE = "en_US"


class Translator:
    def __init__(self, locales_dir: Path, language: str, logger: logging.Logger | None = None):
        self._locales_dir = locales_dir
        self._logger = logger or logging.getLogger("antidupe.i18n")
        self._language = language
        self._catalogs: dict[str, dict] = {}
        self._load(FALLBACK_LOCALE)
        if language != FALLBACK_LOCALE:
            self._load(language)

    def set_language(self, language: str) -> None:
        self._language = language
        self._load(language)

    def _load(self, locale: str) -> None:
        if locale in self._catalogs:
            return
        path = self._locales_dir / f"{locale}.yml"
        if not path.exists():
            self._logger.warning("Locale '%s' not found, falling back to %s", locale, FALLBACK_LOCALE)
            self._catalogs[locale] = {}
            return
        try:
            with path.open("r", encoding="utf-8") as fh:
                self._catalogs[locale] = yaml.safe_load(fh) or {}
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to load locale '%s': %s", locale, exc)
            self._catalogs[locale] = {}

    def _lookup(self, catalog: dict, dotted_key: str):
        node = catalog
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def t(self, key: str, **kwargs) -> str:
        """Translate ``key`` (dotted path) using the active language.

        Falls back to en_US, then to the raw key itself, so a missing
        translation is only ever a cosmetic issue, never an exception.
        """
        value = self._lookup(self._catalogs.get(self._language, {}), key)
        if value is None:
            value = self._lookup(self._catalogs.get(FALLBACK_LOCALE, {}), key)
        if value is None:
            return key
        try:
            return str(value).format(**kwargs)
        except (KeyError, IndexError):
            return str(value)
