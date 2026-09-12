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
    assert manifest["ui"] == {"type": "application", "entry": "ui/index.html"}
    defaults = json.loads((ROOT / "config.default.json").read_text(encoding="utf-8"))
    assert manifest["config"]["defaults"] == defaults
    assert manifest["version"] == project["version"] == __version__


def test_settings_ui_assets_exist() -> None:
    for name in ("index.html", "app.js", "styles.css", "meshzork-openhop.png"):
        assert (ROOT / "ui" / name).is_file()
    assert (ROOT / "meshzork_plugin" / "assets" / "meshzork-openhop.png").is_file()
