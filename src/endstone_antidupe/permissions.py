"""Permission node constants.

Kept as plain string constants (rather than scattering literals across
the codebase) so a typo in a permission check is a `NameError` at
import time instead of a silent always-false check at runtime.
"""

from __future__ import annotations


class Permissions:
    COMMAND_USE = "antidupe.command"
    COMMAND_RELOAD = "antidupe.command.reload"
    COMMAND_STATS = "antidupe.command.stats"
    COMMAND_HISTORY = "antidupe.command.history"
    COMMAND_TOGGLE = "antidupe.command.toggle"
    COMMAND_CLEAR = "antidupe.command.clear"
    COMMAND_METRICS = "antidupe.command.metrics"
    ALERTS_RECEIVE = "antidupe.alerts.receive"
    BYPASS = "antidupe.bypass"


# Registered with Endstone's permission manager at plugin startup so
# server admins can manage them through any standard permissions plugin.
PERMISSION_DEFINITIONS = {
    Permissions.COMMAND_USE: {
        "description": "Allows using the base /antidupe command.",
        "default": "op",
    },
    Permissions.COMMAND_RELOAD: {
        "description": "Allows reloading AntiDupe's configuration.",
        "default": "op",
    },
    Permissions.COMMAND_STATS: {
        "description": "Allows viewing AntiDupe statistics.",
        "default": "op",
    },
    Permissions.COMMAND_HISTORY: {
        "description": "Allows viewing a player's detection history.",
        "default": "op",
    },
    Permissions.COMMAND_TOGGLE: {
        "description": "Allows enabling/disabling individual detectors.",
        "default": "op",
    },
    Permissions.COMMAND_CLEAR: {
        "description": "Allows clearing all stored detection logs.",
        "default": "op",
    },
    Permissions.COMMAND_METRICS: {
        "description": "Allows viewing internal performance metrics.",
        "default": "op",
    },
    Permissions.ALERTS_RECEIVE: {
        "description": "Receive real-time chat alerts for detected exploit attempts.",
        "default": "op",
    },
    Permissions.BYPASS: {
        "description": "Exempts a player from all AntiDupe detectors.",
        "default": False,
    },
}
