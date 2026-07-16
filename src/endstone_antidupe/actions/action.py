"""Base contract for pluggable actions triggered by a detection.

An action is anything that should happen as a *consequence* of a
detection: logging, alerting admins, removing the exploited item,
kicking the player, etc. Which actions fire for a given detection is
decided declaratively in config.yml (see ``config/models.py:ActionRules``),
so adding a brand-new action only requires implementing this
interface and registering it by name in ActionExecutor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from endstone_antidupe.domain.models import Detection


class Action(ABC):
    name: str = "unset"

    @abstractmethod
    def execute(self, detection: Detection, detector, context) -> None:
        """Perform the action. Must never raise -- exceptions are
        caught and logged by ActionExecutor so one broken action never
        prevents the others (or the server) from running."""
