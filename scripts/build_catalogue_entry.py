"""Create release checksums and schema-2 openHop catalogue metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 development environments
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
HEX_REVISION = re.compile(r"[0-9a-f]{7,64}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_entry(wheel: Path, repository: str, revision: str, tag: str) -> dict[str, object]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    manifest = json.loads((ROOT / "openhop-plugin.json").read_text(encoding="utf-8"))
    version = project["version"]

    if manifest["version"] != version:
        raise ValueError("pyproject.toml and openhop-plugin.json versions do not match")
    if tag != f"v{version}":
        raise ValueError(f"release tag {tag!r} must be v{version}")
    if not HEX_REVISION.fullmatch(revision):
        raise ValueError("source revision must be a lowercase hexadecimal Git commit")
    if repository.count("/") != 1 or repository.startswith(("http://", "https://")):
        raise ValueError("repository must use GitHub owner/repository form")

    normalized_distribution = re.sub(r"[-_.]+", "_", project["name"])
    expected_wheel = f"{normalized_distribution}-{version}-py3-none-any.whl"
    if wheel.name != expected_wheel:
        raise ValueError(f"expected wheel {expected_wheel!r}, got {wheel.name!r}")

    release_base = f"https://github.com/{repository}/releases/download/{tag}"
    plugin = {
        "id": manifest["id"],
        "name": manifest["name"],
        "description": manifest["description"],
        "repository": repository,
        "category": "games",
        "logo": f"{release_base}/meshzork-card.png",
        "distribution": project["name"],
        "source_revision": revision,
        "version": version,
        "wheel_url": f"{release_base}/{wheel.name}",
        "sha256": file_sha256(wheel),
        "min_repeater_version": "1.1.4",
        "homepage": f"https://github.com/{repository}",
        "tags": ["game", "meshcore", "interactive-fiction", "zork"],
    }
    return {"schema": 2, "plugins": [plugin]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    catalogue = build_entry(args.wheel, args.repository, args.revision, args.tag)
    digest = catalogue["plugins"][0]["sha256"]
    args.output.write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")
    checksum_path = args.wheel.with_suffix(args.wheel.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {args.wheel.name}\n", encoding="ascii")


if __name__ == "__main__":
    main()
