"""Central dispatcher that turns a Detection into a sequence of Actions.

Which actions run is driven entirely by config.yml's `actions` block
(one list per confidence level). This is the only place that maps
confidence -> behavior, so tuning a server's response (e.g. "only log,
never auto-punish, until I trust the detector") is a config edit, not
a code change.
"""

from __future__ import annotations

import logging

from endstone_antidupe.actions.action import Action
from endstone_antidupe.domain.models import Detection


class ActionExecutor:
    def __init__(self, config, logger: logging.Logger | None = None):
        self._config = config
        self._logger = logger or logging.getLogger("antidupe.actions")
        self._actions: dict[str, Action] = {}
        # Populated by the plugin after construction, once all services
        # exist -- see plugin.py. Kept as a simple namespace object
        # rather than growing this constructor's parameter list every
        # time a new service is added.
        self.service_context = None

    def register_action(self, action: Action) -> None:
        self._actions[action.name] = action

    def refresh_config(self, config) -> None:
        self._config = config

    def execute(self, detection: Detection, detector) -> None:
        action_names = self._config.actions_for(detection.confidence_level.name)
        for name in action_names:
            action = self._actions.get(name)
            if action is None:
                self._logger.warning(f"Unknown action '{name}' referenced in config.yml")
                continue
            try:
                action.execute(detection, detector, self.service_context)
            except Exception as exc:  # noqa: BLE001 - one bad action must not break the rest
                self._logger.warning(f"Action '{name}' raised an exception: {exc}")
