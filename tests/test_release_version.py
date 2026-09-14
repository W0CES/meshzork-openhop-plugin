import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CURRENT_VERSION = "0.3.1"
check_release_version = runpy.run_path(str(ROOT / "scripts" / "check_release_version.py"))[
    "check_release_version"
]


def copy_version_files(destination: Path) -> None:
    for path in ("pyproject.toml", "openhop-plugin.json"):
        (destination / path).write_bytes((ROOT / path).read_bytes())
    package = destination / "meshzork_plugin"
    package.mkdir()
    (package / "__init__.py").write_bytes((ROOT / "meshzork_plugin" / "__init__.py").read_bytes())


def test_current_release_version_matches() -> None:
    assert check_release_version(f"v{CURRENT_VERSION}", ROOT) == CURRENT_VERSION


@pytest.mark.parametrize(
    "tag",
    ["release-0.3.1", "V0.3.1", "v0.3", "v0.3.1-rc1", "refs/tags/v0.3.1"],
)
def test_noncanonical_release_tag_is_rejected(tag: str) -> None:
    with pytest.raises(ValueError, match="vMAJOR.MINOR.PATCH"):
        check_release_version(tag, ROOT)


def test_mismatched_package_version_is_rejected(tmp_path: Path) -> None:
    copy_version_files(tmp_path)
    project_path = tmp_path / "pyproject.toml"
    project_path.write_text(
        project_path.read_text(encoding="utf-8").replace('version = "0.3.1"', 'version = "0.4.0"'),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pyproject.toml=0.4.0"):
        check_release_version("v0.3.1", tmp_path)


def test_mismatched_manifest_version_is_rejected(tmp_path: Path) -> None:
    copy_version_files(tmp_path)
    manifest_path = tmp_path / "openhop-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "0.4.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="openhop-plugin.json=0.4.0"):
        check_release_version("v0.3.1", tmp_path)


def test_mismatched_python_version_is_rejected(tmp_path: Path) -> None:
    copy_version_files(tmp_path)
    init_path = tmp_path / "meshzork_plugin" / "__init__.py"
    init_path.write_text('__version__ = "0.4.0"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="meshzork_plugin/__init__.py=0.4.0"):
        check_release_version("v0.3.1", tmp_path)
