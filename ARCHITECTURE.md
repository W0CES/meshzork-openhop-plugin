# Current openHop plugin architecture and API

Research baseline: `openhop-dev/openhop_repeater` release `1.1.4`, commit
`13eb8b2ea8b1cdb4a07ed6e282dc99e3aa8a5a8b` on the default `main` branch,
cross-checked against `dev` commit
`9e375da776826632a0b7b6a25a529b102e864018` on 2026-09-11. The plugin package
was identical across those two snapshots.

Primary sources:

- <https://github.com/openhop-dev/openhop_repeater/blob/main/docs/plugins.md>
- <https://github.com/openhop-dev/openhop_repeater/tree/main/repeater/plugins>
- <https://github.com/openhop-dev/openhop_repeater/blob/main/repeater/plugins/manifest.py>
- <https://github.com/openhop-dev/openhop_repeater/blob/main/repeater/plugins/runtime.py>
- <https://github.com/openhop-dev/openhop_repeater/blob/main/repeater/plugins/manager.py>
- <https://github.com/openhop-dev/openhop_repeater/blob/main/repeater/plugins/ipc.py>
- <https://github.com/openhop-dev/openhop_repeater/blob/main/repeater/web/plugin_endpoints.py>
- official service-plugin example: <https://github.com/openhop-dev/openhop-nomad-plugin>
- live catalogue: <https://repeater-plugins.openhop.dev/catalogue.json>

## The important boundary

Plugins are external applications. They are never imported into the repeater
daemon. The plugin manager's Unix-socket IPC handles installation and lifecycle;
it is not a packet/event API for a plugin. Runtime plugins receive messages by
connecting to an existing repeater interface. For a MeshCore bot, the supported
working example is a dedicated Companion TCP frame server.

```text
MeshCore radio packet
  -> openhop-repeater
  -> dedicated Companion identity / TCP frame server (127.0.0.1:5002)
  -> MeshZork process
  -> SQLite command-history transaction
  -> isolated pure-Python yazm Z-machine replay
  -> Companion SEND_TXT_MSG
  -> openhop-repeater transmit path

Dashboard REST /api/plugins/*
  -> JSON-lines Unix socket
  -> openhop-plugin-manager
  -> install, configure, start, stop, supervise
```

## Manifest schema 1

The wheel must contain `openhop-plugin.json`. openHop prefers it under
`share/openhop/plugins/<id>/`. Required fields are `schema`, `id`, `name`, and
`version`, plus at least one of `runtime` or `ui`.

- `schema` must equal `1`.
- `id` is lowercase and matches `^[a-z0-9][a-z0-9._-]*$`, is at most 128
  characters, and may not contain path separators or `..`.
- `version` is semantic-version shaped (`1.2.3`, with optional prerelease/build).
- the only runtime type is currently `python`.
- `runtime.entrypoint` is a bare installed console-script name.
- the only UI type is currently `application`; its entry must live in a
  dedicated non-reserved subtree such as `ui/index.html`.
- `config.defaults` may contain an opaque JSON object up to 256 KiB.
- unknown keys are not represented by the parsed manifest, so they should not
  be used as an implied API or permission system.

MeshZork declares a Python runtime and a static application UI. Its wheel
data-files place the manifest and `config.default.json` at
`share/openhop/plugins/openhop.meshzork/`, with the settings application under
the dedicated `ui/` subtree. The UI reads and replaces the authenticated plugin
settings object, preserving non-editable MeshZork values, and requests a
MeshZork-only restart after saving. It exposes player capacity, inactive-slot
timeout, and save-retention controls without importing Repeater internals.

## Installation and storage

The HTTP layer accepts a multipart wheel upload or a JSON host `wheel_path` at
`POST /api/plugins/install`. It forwards a management request over a Unix domain
socket, normally `/var/lib/openhop_repeater/plugin-manager.sock`. The manager:

1. validates archive limits and the schema-1 manifest;
2. creates `/var/lib/openhop_repeater/plugins/<id>/releases/<version>/`;
3. archives the exact wheel in that release;
4. creates a release-specific Python virtual environment;
5. runs pip inside that environment;
6. resolves the declared console entrypoint inside the environment;
7. atomically switches `current` to the installed release;
8. preserves the plugin's enabled flag and persistent `data/` directory.

The installed layout separates versioned code/venv from persistent `data/` and
bounded logs. Installing a local wheel leaves it disabled. Catalogue installs
are enabled by default. The live schema-2 catalogue pins an approved version,
GitHub release wheel URL, source revision, and SHA-256; pip-resolved transitive
dependencies are not covered by that wheel checksum.

## Runtime and lifecycle

At manager startup, every enabled service plugin is started. `enable` both
persists enabled state and starts a runtime. `start` and `restart` reject a
disabled plugin. `stop` stops the process but leaves the enabled flag; `disable`
stops it and persists disabled state.

The runtime launches exactly the installed console script with `shell=False`,
the plugin data directory as its working directory, combined stdout/stderr sent
to bounded plugin logs, and these environment variables:

- `OPENHOP_PLUGIN_ID=<id>`
- `OPENHOP_PLUGIN_DATA=<persistent data directory>`

On Linux it starts a new process session. Stop/disable first send SIGTERM to the
captured process group, wait for the stop timeout, then send SIGKILL. Unexpected
exits are restarted. Five exits within the 60-second crash window produce
`FAILED`. The manager and repeater are separate services with a soft dependency;
either can remain running when the other stops.

This is reliability isolation, not a hostile-code sandbox: native plugins run
under the `repeater` account and inherit its filesystem/network access.

## Management IPC and HTTP API

The internal IPC is newline-delimited JSON over an AF_UNIX socket. It bounds
message size, connections, workers, installer output, and timeouts. Slow
download/install operations share one slot. A lost transport after an install
is dispatched can yield an unknown outcome; callers must inspect status rather
than assume rollback.

Exposed operations include:

- list and per-plugin status;
- install and uninstall (data retained unless `delete_data=true`);
- enable, disable, start, stop, restart;
- bounded log tail;
- get/set opaque `config.json`, optionally restarting;
- read plugin-written `runtime.json` for UI status;
- catalogue list/install, update check/apply, and progress.

These map to authenticated routes under `/api/plugins/`. If the manager socket
is unavailable, plugin API calls fail with HTTP 503 while repeater operation
continues. Current API bearer tokens are administrator-equivalent, not scoped
plugin credentials.

| HTTP route | Purpose |
| --- | --- |
| `GET /api/plugins/` | list installed plugins |
| `GET /api/plugins/{id}` | status, PID, last exit, capabilities, and paths |
| `POST /api/plugins/install` | multipart `wheel` or JSON `wheel_path` install |
| `POST /api/plugins/enable` | persist enabled and start a service runtime |
| `POST /api/plugins/disable` | stop and persist disabled |
| `POST /api/plugins/start` | start an already-enabled runtime |
| `POST /api/plugins/stop` | stop without clearing enabled state |
| `POST /api/plugins/restart` | stop/start an enabled runtime |
| `GET /api/plugins/logs?id=...&tail=...` | bounded plugin log tail |
| `GET/POST /api/plugins/settings` | read or replace opaque plugin config |
| `GET /api/plugins/runtime?id=...` | read plugin-owned `runtime.json` |
| `DELETE /api/plugins/{id}` | uninstall, optionally `delete_data=true` |
| `GET /api/plugins/catalogue` | approved catalogue plus install/update state |
| `POST /api/plugins/catalogue_install` | install an approved catalogue wheel |
| `GET /api/plugins/updates?id=...` | check the approved update state |
| `POST /api/plugins/update` | install an approved update |
| `GET /api/plugins/progress?id=...` | stream install/update progress with SSE |

## MeshCore message handling used here

The official NOMAD plugin demonstrates the current service-plugin pattern.
MeshZork follows the same Companion frame flow:

1. connect to the configured local Companion TCP port;
2. send `CMD_APP_START` and `CMD_DEVICE_QUERY`;
3. react to unsolicited `PUSH_CODE_MSG_WAITING` frames (and poll defensively);
4. issue `CMD_SYNC_NEXT_MESSAGE` until `RESP_CODE_NO_MORE_MESSAGES`;
5. parse legacy or v3 direct-contact message frames and ignore channel frames;
6. reply with `CMD_SEND_TXT_MSG`, plain-text type, and the sender's six-byte
   prefix;
7. wait for `RESP_CODE_SENT` or `RESP_CODE_ERR`, retrying bounded timeouts.

The Companion server admits one TCP client, so MeshZork needs its own Companion
identity/port. It intentionally handles DMs only, avoiding accidental gameplay
in shared channels.

## MeshZork design decisions

- Per-user key: six-byte sender prefix encoded as hex.
- Persistence: SQLite in `$OPENHOP_PLUGIN_DATA/sessions.sqlite3`; each sender has
  an independent command history. The history is replayed through `yazm-py` with
  a fixed random seed, making recovery independent of an in-memory process.
- Duplicate safety: sender + radio timestamp + normalized-command digest is
  retained for a configurable TTL so a radio retry cannot move twice.
- Capacity: at most three players are active at once. A slot is released after
  15 minutes without a command, while its saved game remains resumable.
- Retention: sessions unused for 30 days are removed during normal message
  processing, bounding SQLite growth without affecting active games.
- Airtime: long story output is stored as UTF-8-safe numbered pages of at most
  `max_reply_bytes` (145 by default). Up to four pages are sent automatically
  with an inter-packet delay; `NEXT` retrieves only unusually long remaining output.
  The interpreter score/move status bar is removed from routine replies.
- Privacy in logs: sender prefix and a command digest are logged, not command
  text.
- Fault containment: no repeater imports, separate venv/process group, bounded
  work, graceful SIGTERM, automatic Companion reconnect.

Version 0.2.0 replaced the original test world with the complete MIT-licensed
historical Zork I Z-machine program. Version 0.3.0 replaced the external
`dfrotz` operating-system dependency with pinned, MIT-licensed `yazm-py`. The
interpreter is launched from the plugin virtual environment in a bounded child
process, uses plain output and a fixed random seed, and keeps story file access
under a per-player data directory. The wheel is platform-independent and works
with the Python 3.12 runtime in the published openHop Docker image. Interpreter
failures remain inside the plugin manager's supervised process boundary and do
not interrupt the repeater.
