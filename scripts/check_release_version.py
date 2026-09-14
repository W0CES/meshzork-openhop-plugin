"""Verify that a release tag matches every MeshZork version declaration."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

CANONICAL_TAG = re.compile(r"v(?P<version>\d+\.\d+\.\d+)")


def check_release_version(tag: str, root: Path) -> str:
    match = CANONICAL_TAG.fullmatch(tag)
    if match is None:
        raise ValueError("release tag must use the form vMAJOR.MINOR.PATCH")

    expected = match.group("version")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = json.loads((root / "openhop-plugin.json").read_text(encoding="utf-8"))
    init_text = (root / "meshzork_plugin" / "__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.MULTILINE)
    if init_match is None:
        raise ValueError("meshzork_plugin.__version__ could not be read")

    declared = {
        "pyproject.toml": str(project["project"]["version"]),
        "openhop-plugin.json": str(manifest["version"]),
        "meshzork_plugin/__init__.py": init_match.group(1),
    }
    mismatches = {path: version for path, version in declared.items() if version != expected}
    if mismatches:
        details = ", ".join(f"{path}={version}" for path, version in mismatches.items())
        raise ValueError(f"tag {tag} does not match {details}")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()
    version = check_release_version(args.tag, args.root.resolve())
    print(f"release version verified: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
