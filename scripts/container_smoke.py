"""Verify a clean container wheel install can execute the bundled Zork engine."""

from __future__ import annotations

import tempfile
from importlib.resources import files
from pathlib import Path

from meshzork_plugin.zork import YazmRunner


def main() -> None:
    story = Path(str(files("meshzork_plugin").joinpath("assets/zork1.z3")))
    with tempfile.TemporaryDirectory(prefix="meshzork-smoke-") as directory:
        runner = YazmRunner(story, Path(directory), seed=117, timeout_seconds=15)
        output = runner.run(["open mailbox"], "container")
    expected = "Opening the small mailbox reveals a leaflet."
    if expected not in output:
        raise RuntimeError(f"unexpected Zork output: {output!r}")
    print("MeshZork container smoke test passed")


if __name__ == "__main__":
    main()
