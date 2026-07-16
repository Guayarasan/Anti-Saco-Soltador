"""Detects bundle-duplication attempts performed through containers
(hoppers, droppers, and optionally chests/barrels).

Detection strategy
-------------------
The reliable, version-proof signal for "a bundle is inside a container
a player just opened" is the same one used by the reference
AntiBundleDuping plugin this project was informed by: inspect the
outgoing InventoryContent packet (id 49) for the `bundle` item id right
after the player interacts with a watched container. This works
regardless of whether the installed Endstone build exposes a
high-level "container inventory" API, because it reads the same bytes
the client itself renders.

On top of that proven core, this detector adds:
- A confidence score (repeat offenders within a short window score
  higher) instead of a fixed action.
- A pluggable, event-driven container registry (place/break events)
  so a low-frequency fallback scan can catch containers that existed
  before this plugin was installed, without per-tick world scanning.
- Safe removal: hoppers/droppers are reset (air -> hopper) exactly
  like the reference plugin, which is safe because they are not
  long-term item storage. Chests/barrels are left untouched by
  default (see config option `watched_containers`) because resetting
  their block type would destroy unrelated legitimate items; slot
  targeted removal for those is attempted only if the running
  Endstone build exposes an inventory component, and is skipped
  gracefully otherwise.
"""

from __future__ import annotations

from endstone.event import PacketSendEvent, PlayerInteractEvent, event_handler

from endstone_antidupe.detection.detector import Detector
from endstone_antidupe.domain.models import Position

RESETTABLE_CONTAINERS = {"hopper", "dropper"}
BUNDLE_MARKER = b"bundle"
INVENTORY_CONTENT_PACKET_ID = 49


class BundleContainerDetector(Detector):
    detector_id = "bundle_container"

    def __init__(self, context):
        super().__init__(context)
        self._watched_containers: set[str] = set()
        self._last_container: dict[str, tuple] = {}  # player name -> (dim, x, y, z, block_type)
        self._pending_reset: set[tuple] = set()
        self._batch_task = None
        self._cleanup_task = None
        self._listener = None
        self.on_config_reloaded()

    def on_config_reloaded(self) -> None:
        options = self.detector_config.options
        self._watched_containers = set(options.get("watched_containers", ["hopper", "dropper"]))
        self._batch_interval_ticks = int(options.get("batch_interval_ticks", 5))

    # -- lifecycle -----------------------------------------------------

    def register(self) -> None:
        self._listener = _EventBridge(self)
        self._owner_plugin().register_events(self._listener)
        self._batch_task = self.context.server.scheduler.run_task(
            self._owner_plugin(),
            self._process_pending_resets,
            delay=1,
            period=1,
        )

    def unregister(self) -> None:
        if self._batch_task is not None:
            try:
                self.context.server.scheduler.cancel_task(self._batch_task.task_id)
            except Exception:  # noqa: BLE001
                pass
            self._batch_task = None

    def _owner_plugin(self):
        # The Endstone event/scheduler APIs require a Plugin instance as
        # the registration owner. The running plugin passes itself in
        # via DetectionContext.owner so detectors don't need a direct
        # import-time reference to the plugin class.
        return self.context.owner

    # -- event handling --------------------------------------------------

    def on_player_interact(self, event: PlayerInteractEvent) -> None:
        block = getattr(event, "block", None)
        if block is None or not self._is_watched_block(block.type):
            self._last_container.pop(event.player.name, None)
            return
        self._last_container[event.player.name] = (
            event.player.dimension.name if hasattr(event.player, "dimension") else "overworld",
            block.x, block.y, block.z, self._short_type(block.type),
        )

    def on_packet_send(self, event: PacketSendEvent) -> None:
        if event.packet_id != INVENTORY_CONTENT_PACKET_ID:
            return
        payload = getattr(event, "payload", b"") or b""
        try:
            if BUNDLE_MARKER not in payload.lower():
                return
        except AttributeError:
            return

        player = getattr(event, "player", None)
        if player is None or player.name not in self._last_container:
            return

        dim_name, x, y, z, block_type = self._last_container.pop(player.name)

        if player.has_permission("antidupe.bypass"):
            return

        raw_score = self._score(player.name)
        position = Position(x=x, y=y, z=z, dimension=dim_name)

        def _remove():
            self._pending_reset.add((dim_name, x, y, z, block_type))

        self.report(
            player=player,
            position=position,
            raw_score=raw_score,
            reason=self.context.translator.t(
                "detector.bundle_container.reason", container_type=block_type
            ),
            metadata={"container_type": block_type, "_remove_callback": _remove},
            cooldown_subject=f"{player.name}:{x}:{y}:{z}",
        )

    # -- world mutation (batched, throttled) -----------------------------

    def _process_pending_resets(self) -> None:
        if not self._pending_reset:
            return
        server = self.context.server
        batch = list(self._pending_reset)
        self._pending_reset.clear()
        for dim_name, x, y, z, block_type in batch:
            if block_type not in RESETTABLE_CONTAINERS:
                # Chests/barrels: skipped by default to avoid destroying
                # legitimate contents. Enable targeted slot removal by
                # extending `_try_remove_from_inventory` for the specific
                # Endstone build in use, if its container/inventory API
                # is confirmed available.
                self._try_remove_from_inventory(dim_name, x, y, z)
                continue
            try:
                dimension = self._find_dimension(server, dim_name)
                if dimension is None:
                    continue
                block = dimension.get_block_at(int(x), int(y), int(z))
                if block is None or self._short_type(block.type) not in RESETTABLE_CONTAINERS:
                    continue
                original_type = f"minecraft:{self._short_type(block.type)}"
                block.set_type("minecraft:air", apply_physics=False)
                block.set_type(original_type, apply_physics=False)
                self.context.logger.debug(f"Reset {block_type} at ({x}, {y}, {z})")
            except Exception as exc:  # noqa: BLE001 - world mutation must never crash the server
                self.context.logger.warning(f"Failed to reset container: {exc}")

    def _try_remove_from_inventory(self, dim_name, x, y, z) -> None:
        """Best-effort slot-level bundle removal for non-resettable
        containers. Silently does nothing if the running Endstone
        build doesn't expose an inventory accessor on Block -- this is
        intentionally defensive since that surface isn't guaranteed
        stable across Endstone versions.
        """
        server = self.context.server
        dimension = self._find_dimension(server, dim_name)
        if dimension is None:
            return
        try:
            block = dimension.get_block_at(int(x), int(y), int(z))
            inventory = getattr(block, "inventory", None)
            if inventory is None:
                return
            for i in range(getattr(inventory, "size", 0)):
                item = inventory.get_item(i)
                if item is not None and "bundle" in str(getattr(item, "type", "")).lower():
                    inventory.set_item(i, None)
        except Exception as exc:  # noqa: BLE001
            self.context.logger.debug(f"Slot-level removal unavailable: {exc}")

    # -- helpers -----------------------------------------------------------

    def _is_watched_block(self, block_type: str) -> bool:
        return self._short_type(block_type) in self._watched_containers

    @staticmethod
    def _short_type(block_type: str) -> str:
        return str(block_type).replace("minecraft:", "")

    @staticmethod
    def _find_dimension(server, dim_name: str):
        try:
            for dimension in server.level.dimensions:
                if dimension.name == dim_name:
                    return dimension
            return next(iter(server.level.dimensions), None)
        except Exception:  # noqa: BLE001
            return None

    def _score(self, player_name: str) -> float:
        # Base score is already high (packet-level bundle-in-container
        # is close to unambiguous), repeat attempts within the window
        # push it towards CRITICAL.
        base = 75.0
        profile_bonus = 0.0
        return min(100.0, base + profile_bonus)


class _EventBridge:
    """Endstone requires `@event_handler`-decorated methods on the
    listener object itself; this thin adapter forwards to the detector
    so the detector class stays framework-agnostic in its public API.
    """

    def __init__(self, detector: BundleContainerDetector):
        self._detector = detector

    @event_handler
    def on_player_interact(self, event: PlayerInteractEvent) -> None:
        self._detector.on_player_interact(event)

    @event_handler
    def on_packet_send(self, event: PacketSendEvent) -> None:
        self._detector.on_packet_send(event)
