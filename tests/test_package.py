import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from meshzork_plugin import __version__

ROOT = Path(__file__).parents[1]


def test_manifest_and_package_versions_match() -> None:
    manifest = json.loads((ROOT / "openhop-plugin.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert manifest["schema"] == 1
    assert manifest["id"] == "openhop.meshzork"
    assert manifest["runtime"] == {"type": "python", "entrypoint": "meshzork-openhop"}
    assert manifest["version"] == project["version"] == __version__
