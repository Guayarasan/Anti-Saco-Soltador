"""Delivers admin-facing alerts for detections.

Kept separate from the action pipeline (actions/) so that *how* an
alert is delivered (chat broadcast today; could be a webhook or a
form-UI ping later) is swappable without touching detectors.
"""

from __future__ import annotations

import logging

from endstone_antidupe.domain.models import Detection
from endstone_antidupe.i18n.translator import Translator
from endstone_antidupe.permissions import Permissions


class AlertService:
    def __init__(self, server, translator: Translator, logger: logging.Logger | None = None):
        self._server = server
        self._translator = translator
        self._logger = logger or logging.getLogger("antidupe.alerts")

    def broadcast(self, detection: Detection, detector_display_name: str) -> None:
        message = self._translator.t(
            "alert.broadcast",
            player=detection.player_name,
            detector=detector_display_name,
            confidence=round(detection.confidence_score),
        )
        self._send_to_permitted(message)

    def broadcast_severe(self, detection: Detection, detector_display_name: str) -> None:
        message = self._translator.t(
            "alert.severe",
            player=detection.player_name,
            detector=detector_display_name,
        )
        self._send_to_permitted(message)

    def _send_to_permitted(self, message: str) -> None:
        try:
            for player in self._server.online_players:
                if player.has_permission(Permissions.ALERTS_RECEIVE):
                    player.send_message(message)
            self._server.logger.info(message)
        except Exception as exc:  # noqa: BLE001 - alerting must never crash the server
            self._logger.warning(f"Failed to broadcast alert: {exc}")
