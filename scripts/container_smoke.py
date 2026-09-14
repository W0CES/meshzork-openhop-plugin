"""Verify a clean container wheel install can execute the bundled Zork engine."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from importlib.resources import files
from pathlib import Path

from meshzork_plugin.config import Settings
from meshzork_plugin.zork import YazmRunner, ZorkStore


def main() -> None:
    story = Path(str(files("meshzork_plugin").joinpath("assets/zork1.z3")))
    with tempfile.TemporaryDirectory(prefix="meshzork-smoke-") as directory:
        data_dir = Path(directory) / "data"
        data_dir.mkdir()
        config_path = data_dir / "config.json"
        config = {"max_active_players": 7, "save_retention_days": 45}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        os.environ["OPENHOP_PLUGIN_DATA"] = str(data_dir)

        settings = Settings.from_env()
        if settings.max_active_players != 7 or settings.save_retention_days != 45:
            raise RuntimeError("existing plugin configuration was not preserved")

        runner = YazmRunner(story, data_dir / "files", seed=117, timeout_seconds=15)
        first_store = ZorkStore(settings.database_path, runner)
        output = first_store.handle("container-user", "open mailbox", timestamp=1) or ""
        if "Opening the small mailbox reveals a leaflet." not in output:
            raise RuntimeError(f"unexpected Zork output: {output!r}")

        reopened_store = ZorkStore(settings.database_path, runner)
        reopened_store.handle("container-user", "read leaflet", timestamp=2)
        with sqlite3.connect(settings.database_path) as connection:
            history = connection.execute(
                "SELECT history_json FROM zork_sessions WHERE sender_id=?",
                ("container-user",),
            ).fetchone()[0]
        if json.loads(history) != ["open mailbox", "read leaflet"]:
            raise RuntimeError("saved game did not survive reopening the plugin data")
        if json.loads(config_path.read_text(encoding="utf-8")) != config:
            raise RuntimeError("plugin configuration changed during the smoke test")

    print("MeshZork container installation, configuration, and save smoke test passed")


if __name__ == "__main__":
    main()
