# AntiDupe — Endstone Anti-Duplication Framework

A modular, production-oriented anti-duplication plugin for
[Endstone](https://github.com/EndstoneMC/endstone) (Minecraft Bedrock
server software), written from scratch around a pluggable detector
architecture instead of a single hard-coded exploit check.

This is a new design, not a port. It uses the packet-level bundle
detection technique proven by the reference `AntiBundleDuping` plugin
(inspecting `InventoryContent` packets, block-type reset for
hopper/dropper) as the foundation for its container detector, and adds
a full framework around it: confidence scoring, configurable actions,
SQLite persistence with a migration-ready repository layer, i18n,
permissions, admin commands, caching, cooldowns, and rate limiting.

## Architecture

```
src/endstone_antidupe/
├── plugin.py              # bootstraps everything, the only Endstone-Plugin-facing file
├── domain/                # framework-agnostic value objects (Detection, Position, Confidence)
├── config/                # config.yml schema + loader with hot reload
├── i18n/                  # dotted-key translation catalog (en_US, es_ES included)
├── persistence/           # Repository interface + SQLite implementation
├── detection/
│   ├── detector.py        # abstract Detector base every check implements
│   ├── registry.py         # owns detector lifecycle (register/reload/toggle)
│   └── detectors/          # bundle_container.py, bundle_ground.py
├── actions/                # log / alert / remove_item / notify_severe, driven by config
├── services/               # cache, cooldowns, rate limiter, metrics, alerts, stats
└── commands/                # /antidupe reload|stats|history|toggle|clear|metrics
```

### Adding a new detector

1. Create `detection/detectors/my_exploit.py` implementing `Detector`
   (`detector_id`, `register()`, `unregister()`, and calling
   `self.report(...)` when something suspicious is found).
2. Add it to `ALL_DETECTORS` in `detection/detectors/__init__.py`.
3. Add its default config block under `detectors:` in `config.yml`.

Nothing else needs to change — the registry, action pipeline,
persistence, commands, and stats all work against the `Detector`
interface, not against specific exploit logic.

### Confidence scoring & actions

Every detection carries a 0-100 confidence score, bucketed into
`LOW / MEDIUM / HIGH / CRITICAL` using per-detector thresholds from
`config.yml`. Which actions fire for each level is itself configured:

```yaml
actions:
  on_low: [log]
  on_medium: [log, alert]
  on_high: [log, alert, remove_item]
  on_critical: [log, alert, remove_item, notify_severe]
```

## Building & installing

```bash
pip install hatchling
python -m build   # produces a .whl in dist/
```

Copy the resulting wheel into your Endstone server's `plugins/`
directory and restart the server. `config.yml` and the SQLite database
(`antidupe.db`) are created automatically under the plugin's data
folder on first run.

## Commands & permissions

| Command | Permission | Description |
|---|---|---|
| `/antidupe reload` | `antidupe.command.reload` | Hot-reloads config.yml |
| `/antidupe stats` | `antidupe.command.stats` | Totals per detector |
| `/antidupe history <player> [page]` | `antidupe.command.history` | Per-player detection history |
| `/antidupe toggle <detector>` | `antidupe.command.toggle` | Enable/disable a detector live |
| `/antidupe clear` | `antidupe.command.clear` | Wipes all stored detections |
| `/antidupe metrics` | `antidupe.command.metrics` | Internal performance counters |

`antidupe.alerts.receive` controls who gets real-time chat alerts.
`antidupe.bypass` exempts a player from every detector.

## A note on the ground-item detector

The container detector (`bundle_container`) reuses a technique already
proven in production (packet inspection + safe hopper/dropper reset),
so it should work unmodified on any Endstone build that supports the
events used by the reference plugin this project studied.

The ground-item detector (`bundle_ground`) needs to enumerate nearby
entities, and Endstone's Python entity-lookup surface has changed
shape across versions. It tries a few known call patterns and disables
itself with a clear log message (without affecting the container
detector) if none match your installed build — check your server log
after first startup and adjust `_nearby_item_entities` in
`bundle_ground.py` for your exact Endstone version if you see that
warning.

## Testing performed in this environment

The framework-agnostic layers (config loading/hot-reload, i18n,
SQLite repository + migrations, confidence scoring, and the full
action pipeline) were exercised with a runtime smoke test and all
passed. The Endstone-specific event/scheduler glue in `plugin.py` and
the two detectors could not be executed here since no Endstone server
runtime or package is available in this sandbox — please test on a
real server before deploying to production, particularly the
ground-item entity lookup noted above.
