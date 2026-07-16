"""Detects restricted bundle items dropped on the ground.

A bundle sitting on the ground near a player is a much weaker signal
than one appearing inside a container right after interaction, so this
detector is scored lower by default (see config.yml thresholds) and
exists mainly to surface *ground/dropper-style* dupe methods that never
touch a hopper at all, and to feed the repeat-offender scoring used by
other detectors via the shared stats service.

Entity iteration is intentionally defensive: different Endstone builds
have exposed entity-lookup helpers under slightly different names as
the API stabilizes, so this detector tries a short list of known
shapes and disables itself with a clear log message instead of
spamming warnings every tick if none are available on the running
build.
"""

from __future__ import annotations

from endstone_antidupe.detection.detector import Detector
from endstone_antidupe.domain.models import Position

RESTRICTED_ITEM_SUFFIXES = ("_bundle",)
RESTRICTED_EXACT = {"minecraft:bundle"}


class BundleGroundDetector(Detector):
    detector_id = "bundle_ground"

    def __init__(self, context):
        super().__init__(context)
        self._reported: set = set()
        self._scan_task = None
        self._entity_strategy_failed = False
        self.on_config_reloaded()

    def on_config_reloaded(self) -> None:
        options = self.detector_config.options
        self._scan_interval_ticks = int(options.get("scan_interval_ticks", 15))
        self._scan_radius = float(options.get("scan_radius", 16))

    def register(self) -> None:
        plugin = self.context.owner
        self._scan_task = self.context.server.scheduler.run_task(
            plugin,
            self._scan,
            delay=self._scan_interval_ticks,
            period=self._scan_interval_ticks,
        )

    def unregister(self) -> None:
        if self._scan_task is not None:
            try:
                self.context.server.scheduler.cancel_task(self._scan_task.task_id)
            except Exception:  # noqa: BLE001
                pass
            self._scan_task = None

    def _scan(self) -> None:
        if self._entity_strategy_failed:
            return
        try:
            players = list(self.context.server.online_players)
        except Exception:  # noqa: BLE001
            return

        for player in players:
            if player.has_permission("antidupe.bypass"):
                continue
            entities = self._nearby_item_entities(player)
            if entities is None:
                continue
            for entity in entities:
                self._inspect_entity(player, entity)

    def _nearby_item_entities(self, player):
        """Returns an iterable of nearby item entities using whichever
        API shape the running Endstone build supports, or None if none
        of the known shapes are available (logged once).
        """
        dimension = getattr(player, "dimension", None)
        location = getattr(player, "location", None)
        if dimension is None or location is None:
            return None

        for attempt in (
            lambda: dimension.get_entities_at(location, self._scan_radius),
            lambda: dimension.get_entities(location=location, max_distance=self._scan_radius),
            lambda: [e for e in getattr(dimension, "entities", []) if self._within_radius(e, location)],
        ):
            try:
                result = attempt()
                if result is not None:
                    return result
            except Exception:  # noqa: BLE001
                continue

        self._entity_strategy_failed = True
        self.context.logger.warning(
            "bundle_ground detector: no supported entity-lookup API found on this "
            "Endstone build; ground-item scanning disabled. Container-based "
            "detection is unaffected."
        )
        return None

    def _within_radius(self, entity, location) -> bool:
        try:
            ex, ey, ez = entity.location.x, entity.location.y, entity.location.z
            dx, dy, dz = ex - location.x, ey - location.y, ez - location.z
            return (dx * dx + dy * dy + dz * dz) <= (self._scan_radius ** 2)
        except Exception:  # noqa: BLE001
            return False

    def _inspect_entity(self, player, entity) -> None:
        item_type = self._extract_item_type(entity)
        if item_type is None or not self._is_restricted(item_type):
            return

        loc = getattr(entity, "location", None)
        if loc is None:
            return
        dim_name = getattr(getattr(player, "dimension", None), "name", "overworld")
        key = (dim_name, int(loc.x), int(loc.y), int(loc.z), item_type)
        if key in self._reported:
            return
        self._reported.add(key)
        if len(self._reported) > 5000:
            self._reported.clear()

        position = Position(x=loc.x, y=loc.y, z=loc.z, dimension=dim_name)
        self.report(
            player=player,
            position=position,
            raw_score=45.0,
            reason=self.context.translator.t("detector.bundle_ground.reason"),
            metadata={"item_type": item_type},
            cooldown_subject=f"{player.name}:ground",
        )

    @staticmethod
    def _extract_item_type(entity) -> str | None:
        entity_type = str(getattr(entity, "type", ""))
        if entity_type and "item" not in entity_type:
            return None
        item_stack = getattr(entity, "item_stack", None) or getattr(entity, "item", None)
        if item_stack is None:
            return None
        return str(getattr(item_stack, "type", item_stack)).lower() or None

    @staticmethod
    def _is_restricted(item_type: str) -> bool:
        if item_type in RESTRICTED_EXACT:
            return True
        return any(item_type.endswith(suffix) for suffix in RESTRICTED_ITEM_SUFFIXES)
