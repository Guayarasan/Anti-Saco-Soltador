import json
import os
import tempfile
from datetime import datetime

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.event import (
    event_handler,
    PacketSendEvent,
    PlayerInteractEvent,
    PlayerQuitEvent,
)
from endstone.form import ActionForm
from endstone.plugin import Plugin

# Valores por defecto de config.toml. Se combinan con lo que ya exista en
# disco (self.config), así que un config.toml viejo/incompleto se completa
# solo sin perder lo que el admin ya haya tocado.
DEFAULT_CONFIG = {
    "containers": {
        "hopper_enabled": True,
        "dropper_enabled": True,
    },
    "detection": {
        # ID del paquete de inventario (InventoryContentPacket) donde se
        # revisa si viene un bundle. 49 es el valor vanilla actual.
        "packet_id": 49,
        # Cada cuántos ticks se escanean los contenedores marcados para
        # limpieza. El comportamiento original limpiaba en el siguiente
        # tick, por eso el valor por defecto es 1.
        "clean_scan_period_ticks": 1,
        # Cada cuántos ticks se revisa si un jugador con una interacción
        # pendiente sigue teniendo un bundle en el inventario (barrido de
        # entradas que quedaron "colgadas").
        "stale_check_period_ticks": 20,
    },
    "logging": {
        "console_enabled": True,
    },
    "history": {
        # Máximo de entradas que se conservan en history.jsonl. Evita que
        # el archivo crezca sin límite en servidores que llevan meses.
        "max_entries": 500,
    },
    "messages": {
        "detection_console": (
            "Intento de dupe detectado: jugador={player} contenedor={container} "
            "pos=({x}, {y}, {z}) dimension={dimension}"
        ),
        "cleaned_console": (
            "{container} limpiado en ({x}, {y}, {z}) dimension={dimension}"
        ),
    },
}


def _merge_defaults(target: dict, defaults: dict) -> bool:
    """Rellena en target las claves de defaults que falten, recursivamente.
    Devuelve True si se modificó algo (para saber si hace falta guardar)."""
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
            changed = True
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            if _merge_defaults(target[key], value):
                changed = True
    return changed


def _empty_stats() -> dict:
    return {
        "total_attempts": 0,
        "cleaned": {"hopper": 0, "dropper": 0},
        "players": {},
    }


class AntiBundleDuping(Plugin):
    api_version = "0.11"

    commands = {
        "antidupe": {
            "description": "Estadisticas, historial y configuracion de AntiBundleDuping.",
            "usages": ["/antidupe (reload|stats|clear)[action: AntiDupeAction]"],
            "aliases": ["abd"],
        }
    }

    def on_enable(self):
        self.logger.info("Anti-Bundle-Duping enabled!")

        self.data_folder.mkdir(parents=True, exist_ok=True)
        self._stats_path = self.data_folder / "stats.json"
        self._history_path = self.data_folder / "history.jsonl"

        self.load_configuration()

        self.stats = self._load_stats()
        self.history = self._load_history()

        # Sigue una interacción reciente con un contenedor por jugador:
        # name -> {"pos": (x, y, z), "dimension": id, "container": "minecraft:hopper"}
        self.last_interaction = {}
        # Contenedores marcados para limpieza en el próximo escaneo:
        # (x, y, z) -> {"dimension": id, "container": "minecraft:hopper", "player": name}
        self.pending_clean = {}

        self.register_events(self)

        self.server.scheduler.run_task(
            self,
            self.clean_marked_containers,
            period=self._clean_scan_period,
        )
        self.server.scheduler.run_task(
            self,
            self._sweep_stale_interactions,
            period=self._stale_check_period,
        )

    def on_disable(self):
        self._save_stats()
        self._save_history()

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------

    def load_configuration(self):
        config = self.config
        if _merge_defaults(config, DEFAULT_CONFIG):
            self.save_config()

        containers = config["containers"]
        detection = config["detection"]

        self._hopper_enabled = bool(containers.get("hopper_enabled", True))
        self._dropper_enabled = bool(containers.get("dropper_enabled", True))
        self._packet_id = int(detection.get("packet_id", 49))
        self._clean_scan_period = max(1, int(detection.get("clean_scan_period_ticks", 1)))
        self._stale_check_period = max(1, int(detection.get("stale_check_period_ticks", 20)))
        self._log_console = bool(config["logging"].get("console_enabled", True))
        self._history_max_entries = max(1, int(config["history"].get("max_entries", 500)))
        self._msg_detection = config["messages"].get(
            "detection_console", DEFAULT_CONFIG["messages"]["detection_console"]
        )
        self._msg_cleaned = config["messages"].get(
            "cleaned_console", DEFAULT_CONFIG["messages"]["cleaned_console"]
        )

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------

    @event_handler
    def on_player_interact(self, event: PlayerInteractEvent):
        if not event.block:
            self.last_interaction.pop(event.player.name, None)
            return

        block_type = event.block.type
        is_hopper = "hopper" in block_type
        is_dropper = "dropper" in block_type

        if not is_hopper and not is_dropper:
            self.last_interaction.pop(event.player.name, None)
            return

        if (is_hopper and not self._hopper_enabled) or (
            is_dropper and not self._dropper_enabled
        ):
            self.last_interaction.pop(event.player.name, None)
            return

        self.last_interaction[event.player.name] = {
            "pos": (event.block.x, event.block.y, event.block.z),
            "dimension": event.block.dimension.id,
            "container": block_type,
        }

    @event_handler
    def on_packet_send(self, event: PacketSendEvent):
        if event.packet_id != self._packet_id:
            return
        if b"bundle" not in event.payload.lower():
            return

        player = event.player
        if not player or player.name not in self.last_interaction:
            return

        info = self.last_interaction.pop(player.name)
        pos = info["pos"]
        self.pending_clean[pos] = {
            "dimension": info["dimension"],
            "container": info["container"],
            "player": player.name,
        }

        self._record_attempt(player.name, pos, info["dimension"], info["container"])

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        # Evita que quede una interacción "colgada" si el jugador se
        # desconecta justo después de abrir el contenedor.
        self.last_interaction.pop(event.player.name, None)

    # ------------------------------------------------------------------
    # Tareas programadas
    # ------------------------------------------------------------------

    def clean_marked_containers(self):
        if not self.pending_clean:
            return

        level = self.server.level
        for pos, info in list(self.pending_clean.items()):
            x, y, z = pos
            container_type = info["container"]
            try:
                dimension = level.get_dimension(info["dimension"])
                if dimension is None:
                    continue
                block = dimension.get_block_at(x, y, z)
                if container_type in block.type:
                    block.set_type("minecraft:air", apply_physics=False)
                    block.set_type(container_type, apply_physics=False)
                    self._record_cleanup(
                        info["player"], pos, info["dimension"], container_type
                    )
            except Exception as e:
                self.logger.warning(f"Error al limpiar {container_type} en {pos}: {e}")
            finally:
                self.pending_clean.pop(pos, None)

    def _sweep_stale_interactions(self):
        for player_name in list(self.last_interaction.keys()):
            player = self.server.get_player(player_name)
            if not player:
                self.last_interaction.pop(player_name, None)
                continue
            has_bundle = any(
                item and "bundle" in str(item.type) for item in player.inventory.contents
            )
            if not has_bundle:
                self.last_interaction.pop(player_name, None)

    # ------------------------------------------------------------------
    # Estadísticas / historial persistente
    # ------------------------------------------------------------------

    @staticmethod
    def _simple_name(container_type: str) -> str:
        return "hopper" if "hopper" in container_type else "dropper"

    def _record_attempt(self, player_name, pos, dimension_id, container_type):
        simple = self._simple_name(container_type)

        self.stats["total_attempts"] += 1
        player_stats = self.stats["players"].setdefault(
            player_name, {"attempts": 0, "cleaned": {"hopper": 0, "dropper": 0}}
        )
        player_stats["attempts"] += 1
        self._save_stats()

        if self._log_console:
            x, y, z = pos
            self.logger.info(
                self._msg_detection.format(
                    player=player_name,
                    container=simple,
                    x=x,
                    y=y,
                    z=z,
                    dimension=dimension_id,
                )
            )

    def _record_cleanup(self, player_name, pos, dimension_id, container_type):
        simple = self._simple_name(container_type)
        x, y, z = pos
        now = datetime.now()

        self.stats["cleaned"][simple] = self.stats["cleaned"].get(simple, 0) + 1
        player_stats = self.stats["players"].setdefault(
            player_name, {"attempts": 0, "cleaned": {"hopper": 0, "dropper": 0}}
        )
        player_stats["cleaned"][simple] = player_stats["cleaned"].get(simple, 0) + 1
        self._save_stats()

        self.history.append(
            {
                "player": player_name,
                "x": x,
                "y": y,
                "z": z,
                "dimension": dimension_id,
                "container": simple,
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
            }
        )
        if len(self.history) > self._history_max_entries:
            self.history = self.history[-self._history_max_entries:]
        self._save_history()

        if self._log_console:
            self.logger.info(
                self._msg_cleaned.format(
                    container=simple, x=x, y=y, z=z, dimension=dimension_id
                )
            )

    def _load_stats(self) -> dict:
        if not self._stats_path.exists():
            return _empty_stats()
        try:
            with open(self._stats_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stats = _empty_stats()
            stats.update(
                {k: v for k, v in data.items() if k in ("total_attempts", "cleaned", "players")}
            )
            return stats
        except Exception as e:
            self.logger.warning(f"No se pudo leer stats.json, se reinicia: {e}")
            return _empty_stats()

    def _load_history(self) -> list:
        if not self._history_path.exists():
            return []
        entries = []
        try:
            with open(self._history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            self.logger.warning(f"No se pudo leer history.jsonl: {e}")
            return []
        return entries[-self._history_max_entries:]

    def _atomic_write(self, path, write_fn):
        """Escribe en un archivo temporal y hace os.replace() al final, para
        que un crash a mitad de escritura no deje el archivo corrupto."""
        directory = os.path.dirname(str(path))
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".swap")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                write_fn(f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except Exception as e:
            self.logger.warning(f"Error al guardar {path}: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _save_stats(self):
        self._atomic_write(self._stats_path, lambda f: json.dump(self.stats, f, indent=2))

    def _save_history(self):
        def writer(f):
            for entry in self.history:
                f.write(json.dumps(entry, ensure_ascii=False))
                f.write("\n")

        self._atomic_write(self._history_path, writer)

    def _reset_history_and_stats(self):
        self.stats = _empty_stats()
        self.history = []
        self._save_stats()
        self._save_history()

    def _top_players(self, limit=10):
        return sorted(
            self.stats["players"].items(),
            key=lambda item: item[1]["attempts"],
            reverse=True,
        )[:limit]

    def _build_stats_text(self) -> str:
        cleaned = self.stats["cleaned"]
        lines = [
            "§b--- AntiBundleDuping: Estadisticas ---",
            f"§7Intentos detectados: §f{self.stats['total_attempts']}",
            f"§7Hoppers limpiados: §f{cleaned.get('hopper', 0)}",
            f"§7Droppers limpiados: §f{cleaned.get('dropper', 0)}",
            f"§7Jugadores distintos: §f{len(self.stats['players'])}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    def on_command(self, sender: CommandSender, command: Command, args: list) -> bool:
        if command.name != "antidupe":
            return False

        if args:
            action = args[0].lower()
            if action == "reload":
                self.load_configuration()
                sender.send_message("§b[AntiDupe] §fConfiguracion recargada.")
                return True
            if action == "stats":
                sender.send_message(self._build_stats_text())
                return True
            if action == "clear":
                self._reset_history_and_stats()
                sender.send_message("§b[AntiDupe] §fHistorial y estadisticas borrados.")
                return True
            sender.send_message("§cUso: /antidupe (reload|stats|clear)")
            return True

        if isinstance(sender, Player):
            self._open_main_menu(sender)
        else:
            sender.send_message(
                "§b[AntiDupe] §fUsa este comando en el juego para abrir el menu, "
                "o /antidupe (reload|stats|clear) desde la consola."
            )
        return True

    # ------------------------------------------------------------------
    # Menú (ActionForm)
    # ------------------------------------------------------------------

    def _open_main_menu(self, player: Player):
        form = ActionForm(
            title="AntiBundleDuping",
            content="Selecciona una opcion:",
        )
        form.add_button(
            "Ver estadisticas", on_click=lambda p: self._show_stats_form(p)
        )
        form.add_button(
            "Ver historial", on_click=lambda p: self._show_history_form(p)
        )
        form.add_button(
            "Top jugadores", on_click=lambda p: self._show_top_players_form(p)
        )
        form.add_button(
            "Recargar configuracion", on_click=lambda p: self._handle_reload(p)
        )
        form.add_button(
            "Borrar historial", on_click=lambda p: self._show_confirm_clear_form(p)
        )
        player.send_form(form)

    def _show_stats_form(self, player: Player):
        form = ActionForm(title="Estadisticas", content=self._build_stats_text())
        form.add_button("Volver", on_click=lambda p: self._open_main_menu(p))
        player.send_form(form)

    def _show_history_form(self, player: Player):
        if not self.history:
            content = "§7No hay entradas en el historial."
        else:
            recent = self.history[-15:][::-1]
            lines = []
            for entry in recent:
                lines.append(
                    f"§7[{entry['date']} {entry['time']}] §f{entry['player']} "
                    f"§7- {entry['container']} en ({entry['x']}, {entry['y']}, {entry['z']}) "
                    f"§7[{entry['dimension']}]"
                )
            content = "\n".join(lines)

        form = ActionForm(title="Historial reciente", content=content)
        form.add_button("Volver", on_click=lambda p: self._open_main_menu(p))
        player.send_form(form)

    def _show_top_players_form(self, player: Player):
        top = self._top_players(10)
        if not top:
            content = "§7Todavia no hay datos."
        else:
            lines = []
            for i, (name, data) in enumerate(top, start=1):
                cleaned = data["cleaned"]
                lines.append(
                    f"§7{i}. §f{name} §7- intentos: §f{data['attempts']} "
                    f"§7(hoppers: {cleaned.get('hopper', 0)}, droppers: {cleaned.get('dropper', 0)})"
                )
            content = "\n".join(lines)

        form = ActionForm(title="Top jugadores", content=content)
        form.add_button("Volver", on_click=lambda p: self._open_main_menu(p))
        player.send_form(form)

    def _handle_reload(self, player: Player):
        self.load_configuration()
        player.send_message("§b[AntiDupe] §fConfiguracion recargada.")
        self._open_main_menu(player)

    def _show_confirm_clear_form(self, player: Player):
        form = ActionForm(
            title="Confirmar borrado",
            content="Esto borrara TODO el historial y las estadisticas.\n"
            "Esta accion no se puede deshacer. ¿Continuar?",
        )
        form.add_button("Si, borrar", on_click=lambda p: self._handle_clear(p))
        form.add_button("Cancelar", on_click=lambda p: self._open_main_menu(p))
        player.send_form(form)

    def _handle_clear(self, player: Player):
        self._reset_history_and_stats()
        player.send_message("§b[AntiDupe] §fHistorial y estadisticas borrados.")
        self._open_main_menu(player)
