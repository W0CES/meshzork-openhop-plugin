# MeshZork for openHop

Created for and credited to **MacKayz117**.

MeshZork is a minimal, original interactive-fiction proof of concept for an
openHop Repeater. Players direct-message a dedicated MeshCore Companion
identity. Each sender gets an independent SQLite-backed game session, and every
reply is limited to one LoRa-friendly text packet.

This project contains no Zork story text, data files, or Infocom code. It is a
small original game in the command-driven adventure tradition.

## What this proof of concept does

- receives plain-text direct messages through an openHop Companion TCP server;
- identifies a player by the six-byte MeshCore sender prefix;
- saves room, inventory, move count, and victory state in SQLite;
- persists sessions across plugin and repeater restarts;
- ignores duplicate radio deliveries using sender, timestamp, and command hash;
- sends one UTF-8 response of at most 145 bytes by default;
- reconnects automatically if the Companion server is temporarily unavailable;
- runs as a child of `openhop-plugin-manager`, outside the repeater process.

The tiny test world understands `LOOK`, `N`, `S`, `E`, `W`, `TAKE KEY`,
`INVENTORY`, `SCORE`, `HELP`, and `RESET`.

## Requirements

- openHop Repeater 1.1.4 or newer with plugins enabled;
- the separate `openhop-plugin-manager` service running;
- one dedicated Companion identity with a free local TCP port (the examples use
  `5002`);
- internet access during first installation so the isolated plugin environment
  can install `openhop-core==1.1.1`.

The current plugin manager is not a security sandbox. It isolates the plugin's
process and Python dependencies, but native plugins still run as the `repeater`
user. Install only wheels you trust.

## Build the wheel

On any Python 3.10+ machine, from this directory:

```bash
python3 -m venv .build-venv
. .build-venv/bin/activate
python -m pip install --upgrade build
python -m build --wheel
```

The result is `dist/openhop_meshzork_plugin-0.1.1-py3-none-any.whl`.

## Raspberry Pi installation

### 1. Update openHop and confirm the manager

Run the openHop upgrade from the source checkout used for your installation:

```bash
cd ~/openhop_repeater
sudo bash ./manage.sh upgrade
sudo systemctl status openhop-repeater --no-pager
sudo systemctl status openhop-plugin-manager --no-pager
```

If the manager unit was not enabled by the upgrade, install the unit from the
matching openHop source checkout and start it:

```bash
sudo cp ~/openhop_repeater/openhop-plugin-manager.service /etc/systemd/system/openhop-plugin-manager.service
sudo systemctl daemon-reload
sudo systemctl enable --now openhop-plugin-manager
```

Do not run the plugin manager as root. If the packaged unit is in a different
location on your installation, use the `openhop-plugin-manager.service` from the
matching openHop Repeater 1.1.4 source tree.

### 2. Create a dedicated Companion identity

In the openHop dashboard, open **Identities**, add a **Companion**, and use:

- registration/name: `MeshZork`
- advertised node name: `MeshZork`
- TCP bind address: `127.0.0.1`
- TCP port: `5002`
- timeout: `0` (keeps the long-running local plugin connected)

Let openHop generate the identity key. A Companion allows one connected TCP
client, so do not reuse an identity already occupied by another app. Confirm the
Companion is active before enabling the plugin.

Equivalent YAML shape, if you manage `/etc/openhop_repeater/config.yaml`
directly, is:

```yaml
plugins:
  enabled: true

identities:
  companions:
    - name: "MeshZork"
      identity_key: "YOUR_OPENHOP_GENERATED_PRIVATE_IDENTITY_KEY"
      settings:
        node_name: "MeshZork"
        bind_address: "127.0.0.1"
        tcp_port: 5002
        tcp_timeout: 0
```

If you edit YAML directly, restart `openhop-repeater` and verify port 5002 is
listening before continuing.

### 3. Install the wheel

Copy the wheel to the Pi, sign in to the openHop dashboard, open **Plugins**, and
use the local wheel upload. Select:

```text
openhop_meshzork_plugin-0.1.1-py3-none-any.whl
```

The manager installs it disabled. Open the MeshZork plugin settings and confirm:

```json
{
  "meshcore_host": "127.0.0.1",
  "meshcore_port": 5002,
  "max_reply_bytes": 145,
  "max_command_bytes": 160,
  "duplicate_ttl_seconds": 600,
  "log_level": "INFO"
}
```

Save, then enable MeshZork. Enabling starts its service process.

The same operation can be performed through openHop's authenticated REST API if
you already have an API bearer token:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -F "wheel=@openhop_meshzork_plugin-0.1.1-py3-none-any.whl" \
  http://127.0.0.1:8000/api/plugins/install

curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id":"openhop.meshzork"}' \
  http://127.0.0.1:8000/api/plugins/enable
```

Treat the bearer token as an administrator credential.

## Test over MeshCore

1. Add the advertised `MeshZork` Companion as a contact in your MeshCore client.
2. Send it a direct message: `LOOK`.
3. Expect a short reply beginning `Faded Trail:`.
4. Send `E`, `TAKE KEY`, `W`, `N`, `N` to reach the victory room.
5. Send `SCORE`; expect `Score 10/10`.
6. From a second MeshCore identity, send `INVENTORY`; it should report an empty
   inventory, proving sessions are separated.
7. Restart the plugin and send `SCORE` again from the first identity; the saved
   state should remain.

Useful checks on the Pi:

```bash
sudo journalctl -u openhop-plugin-manager -n 100 --no-pager
sudo ss -ltnp | grep ':5002'
```

The dashboard Plugins page also exposes status and bounded plugin logs. A
`RUNNING` status only confirms the process exists; the log should also contain
`Connected to Companion 127.0.0.1:5002`.

## Failure isolation and recovery

MeshZork is not imported by `openhop-repeater`. The manager gives it a dedicated
virtual environment and starts it in a separate process group. If MeshZork
crashes, the repeater keeps forwarding packets. The manager restarts unexpected
exits, but marks the plugin `FAILED` after five exits in 60 seconds. Disable the
plugin to stop it without stopping the repeater.

Session data lives at:

```text
/var/lib/openhop_repeater/plugins/openhop.meshzork/data/sessions.sqlite3
```

Normal uninstall keeps that `data/` directory. Select delete-data explicitly if
you want to remove all player sessions.

## Local tests

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
python -m build --wheel
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the exact openHop plugin/API findings
used by this implementation.
