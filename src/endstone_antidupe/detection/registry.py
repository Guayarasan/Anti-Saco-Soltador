"""Owns the set of active detectors and their lifecycle.

Adding a new detector class to the plugin is: import it, pass it into
`DetectorRegistry(context, [...])` in plugin.py. Nothing else changes.
"""

from __future__ import annotations

import logging

from endstone_antidupe.detection.context import DetectionContext
from endstone_antidupe.detection.detector import Detector


class DetectorRegistry:
    def __init__(self, context: DetectionContext, detector_classes: list[type[Detector]]):
        self._context = context
        self._logger = logging.getLogger("antidupe.detectors")
        self._detectors: dict[str, Detector] = {
            cls.detector_id: cls(context) for cls in detector_classes
        }

    def all(self) -> list[Detector]:
        return list(self._detectors.values())

    def get(self, detector_id: str) -> Detector | None:
        return self._detectors.get(detector_id)

    def register_all(self) -> int:
        active = 0
        for detector in self._detectors.values():
            if not detector.enabled:
                self._logger.info("Detector '%s' is disabled in config, skipping.", detector.detector_id)
                continue
            try:
                detector.register()
                active += 1
            except Exception as exc:  # noqa: BLE001 - one bad detector must not break plugin startup
                self._logger.error("Failed to register detector '%s': %s", detector.detector_id, exc)
        return active

    def unregister_all(self) -> None:
        for detector in self._detectors.values():
            try:
                detector.unregister()
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Failed to unregister detector '%s': %s", detector.detector_id, exc)

    def reload(self, config) -> None:
        """Re-registers detectors whose enabled state changed, and
        refreshes config for the ones that stay active."""
        for detector in self._detectors.values():
            was_enabled = detector.enabled
            detector.refresh_config(config)
            now_enabled = detector.enabled
            if was_enabled and not now_enabled:
                detector.unregister()
                self._logger.info("Detector '%s' disabled via reload.", detector.detector_id)
            elif not was_enabled and now_enabled:
                detector.register()
                self._logger.info("Detector '%s' enabled via reload.", detector.detector_id)

    def set_enabled(self, detector_id: str, enabled: bool) -> bool:
        detector = self._detectors.get(detector_id)
        if detector is None:
            return False
        if enabled and not detector.enabled:
            detector.detector_config.enabled = True
            detector.register()
        elif not enabled and detector.enabled:
            detector.detector_config.enabled = False
            detector.unregister()
        return True
