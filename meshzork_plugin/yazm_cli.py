"""Plain deterministic yazm entrypoint used by the isolated game runner."""

from __future__ import annotations

import argparse
from pathlib import Path

from yazm.zmachine import ZMachine
from yazm.zui_std import ZUIStd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("story", type=Path)
    args = parser.parse_args()

    args.session_dir.mkdir(parents=True, exist_ok=True)
    machine = ZMachine(args.story.read_bytes())
    machine.options.rand_seed = args.seed
    machine.rng.seed(args.seed)
    machine.options.save_dir = str(args.session_dir)
    machine.save_dir = str(args.session_dir)
    machine.options.highlight_objects = False
    machine.ui = ZUIStd(plain=True)
    try:
        machine.run()
    finally:
        machine.ui.reset()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
