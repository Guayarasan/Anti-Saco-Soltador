# AntiBundleDuping

[![Endstone](https://img.shields.io/badge/Endstone-0.11-blue.svg)](https://endstone.dev)
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENCE)

Automatically removes bundles from hoppers and droppers on Minecraft Bedrock Edition servers running the Endstone engine, preventing duplication exploits.

## 🎯 Overview

**AntiBundleDuping** monitors hoppers and droppers in real-time and automatically replaces any container found holding a bundle with a clean, empty one. This prevents duplication exploits where bundles interact with these containers to duplicate items, without restricting legitimate player interactions.

Bundles are detected at the packet level (inventory content packets), so the container is reset before the dupe mechanic can complete, and the bundle is dropped as a normal world item instead.

## ✨ Features

- 🔍 **Packet-level detection** for both **hoppers** and **droppers**
- 🔄 **Automatic container reset** — replaced with a fresh empty one, dropping the bundle as a world item
- ⚙️ **`config.toml`** — enable/disable hopper or dropper detection independently, packet id, tick intervals, console messages
- 📊 **Persistent statistics** — total attempts, per-player attempts, hoppers/droppers cleaned
- 📝 **Persistent history log** (`history.jsonl`) — player, coordinates, dimension, container type, date and time; survives restarts, shutdowns and crashes (atomic writes)
- 🖥️ **In-game admin menu** (`/antidupe`) — view stats, view recent history, top players, reload config, clear history — no need to memorize commands
- 🧰 **Console commands** — `/antidupe reload`, `/antidupe stats`, `/antidupe clear` also work from the server console
- ⚡ **Lightweight** — event-driven, cleans containers by their own dimension instead of scanning every dimension on the level

## 📋 Requirements

- **Endstone** 0.11 or higher
- **Minecraft Bedrock** 1.21.60 or higher

## 🚀 Installation

1. Download the latest `.whl` file from the releases page
2. Place it in your server's `plugins/` directory
3. Restart your server
4. A `config.toml` will be generated in the plugin's data folder on first run

## 🔧 How It Works

1. When a player opens a hopper or dropper, the plugin remembers which container was accessed
2. If the server sends inventory data containing a bundle (`minecraft:bundle`), the container is marked for cleaning
3. On the next scan (configurable, 1 tick by default) the container is replaced with air (dropping its contents) and then with a fresh copy of itself
4. The attempt and the cleanup are recorded to `stats.json` and `history.jsonl` in the plugin's data folder

## ⚙️ Configuration (`config.toml`)

```toml
[containers]
hopper_enabled = true
dropper_enabled = true

[detection]
packet_id = 49
clean_scan_period_ticks = 1
stale_check_period_ticks = 20

[logging]
console_enabled = true

[history]
max_entries = 500

[messages]
detection_console = "Intento de dupe detectado: jugador={player} contenedor={container} pos=({x}, {y}, {z}) dimension={dimension}"
cleaned_console = "{container} limpiado en ({x}, {y}, {z}) dimension={dimension}"
```

## 🕹️ Commands

| Command | Description |
| --- | --- |
| `/antidupe` | Opens the in-game admin menu (players only) |
| `/antidupe stats` | Prints a summary of the statistics |
| `/antidupe reload` | Reloads `config.toml` |
| `/antidupe clear` | Clears the history and resets the statistics |

Commands require operator permission by default (Endstone's default for plugin commands).

## 📝 Notes

- The container replacement resets its orientation/state to defaults — intentional, it helps break dupe mechanics that rely on specific states
- `history.jsonl` is capped at `history.max_entries` most recent entries to avoid unbounded disk usage; writes are atomic (temp file + rename) so a crash mid-write cannot corrupt the file
- No player permissions or commands are required for the detection itself — it works fully automatically

## 📄 License

see the [LICENCE](./LICENCE) file for details.
