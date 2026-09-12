import json
import os
import sqlite3
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from meshzork_plugin.zork import YazmRunner, ZorkStore, paginate_text


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def run(self, commands: list[str], sender_id: str) -> str:
        self.calls.append((commands, sender_id))
        if not commands:
            return "ZORK I\nWest of House\nYou are standing in an open field."
        return f"West of House. Result of {commands[-1]}. " + ("Long description. " * 20)


def test_history_is_persistent_and_independent(tmp_path) -> None:
    database = tmp_path / "sessions.sqlite3"
    runner = FakeRunner()
    game = ZorkStore(database, runner, max_reply_bytes=80)

    assert game.handle("alice", "open mailbox", timestamp=1).startswith("1/")
    game.handle("alice", "north", timestamp=2)
    game.handle("bob", "look", timestamp=1)

    assert runner.calls[1] == (["open mailbox", "north"], "alice")
    assert runner.calls[2] == (["look"], "bob")

    with sqlite3.connect(database) as connection:
        saved = connection.execute(
            "SELECT history_json FROM zork_sessions WHERE sender_id='alice'"
        ).fetchone()[0]
    assert json.loads(saved) == ["open mailbox", "north"]


def test_next_delivers_pending_pages_without_advancing_game(tmp_path) -> None:
    runner = FakeRunner()
    game = ZorkStore(tmp_path / "sessions.sqlite3", runner, max_reply_bytes=70)
    first = game.handle("alice", "look", timestamp=1)
    second = game.handle("alice", "next", timestamp=2)

    assert first.startswith("1/") and first.endswith(" NEXT")
    assert second.startswith("2/")
    assert len(runner.calls) == 1
    assert len(first.encode("utf-8")) <= 70
    assert len(second.encode("utf-8")) <= 70


def test_reset_clears_history_and_save_restore_are_automatic(tmp_path) -> None:
    runner = FakeRunner()
    game = ZorkStore(tmp_path / "sessions.sqlite3", runner, max_reply_bytes=145)
    game.handle("alice", "north", timestamp=1)
    assert "automatically" in game.handle("alice", "save", timestamp=2)
    reset = game.handle("alice", "reset", timestamp=3)

    assert "ZORK I" in reset
    assert runner.calls[-1] == ([], "alice")


def test_duplicate_radio_delivery_is_ignored(tmp_path) -> None:
    runner = FakeRunner()
    game = ZorkStore(tmp_path / "sessions.sqlite3", runner)
    assert game.handle("alice", "north", timestamp=9) is not None
    assert game.handle("alice", "north", timestamp=9) is None
    assert len(runner.calls) == 1


def test_paginate_text_is_utf8_safe() -> None:
    pages = paginate_text("cafe \N{GRINNING FACE} " * 80, 75)
    assert len(pages) > 1
    assert all(len(page.encode("utf-8")) <= 75 for page in pages)


def test_zmachine_status_line_is_removed() -> None:
    output = YazmRunner._clean(
        "West of House                      Score: 0 Moves: 3\r\n"
        "West of House\r\nThere is a mailbox here.\r\n"
    )
    assert output == "West of House\nThere is a mailbox here."


def test_bundled_python_interpreter_runs_zork(tmp_path) -> None:
    story = Path(str(files("meshzork_plugin").joinpath("assets/zork1.z3")))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "meshzork_plugin.yazm_cli",
            "--seed",
            "117",
            "--session-dir",
            str(tmp_path / "files"),
            str(story),
        ],
        input="look\n",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert "West of House" in result.stdout
    assert "small mailbox" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="pexpect.spawn requires POSIX")
def test_yazm_runner_returns_only_the_latest_turn(tmp_path) -> None:
    story = Path(str(files("meshzork_plugin").joinpath("assets/zork1.z3")))
    runner = YazmRunner(story, tmp_path / "files", seed=117, timeout_seconds=10)

    output = runner.run(["open mailbox"], "alice")

    assert "Opening the small mailbox reveals a leaflet." in output
    assert "Copyright" not in output


def test_pending_pages_can_be_reserved_and_requeued(tmp_path) -> None:
    game = ZorkStore(tmp_path / "sessions.sqlite3", FakeRunner(), max_reply_bytes=70)
    game.handle("alice", "look", timestamp=1)
    pages = game.take_pending_pages("alice", 2)
    assert len(pages) == 2

    game.requeue_pending_pages("alice", pages)
    assert game.handle("alice", "next", timestamp=2) == pages[0]


def test_active_player_limit_expires_without_losing_saves(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("meshzork_plugin.zork.time.time", lambda: 1000)
    runner = FakeRunner()
    game = ZorkStore(
        tmp_path / "sessions.sqlite3",
        runner,
        max_active_players=2,
        active_player_timeout_seconds=900,
        busy_notice_ttl_seconds=300,
    )
    game.handle("alice", "north", timestamp=1)
    game.handle("bob", "south", timestamp=2)

    assert game.handle("charlie", "look", timestamp=3).startswith("MeshZork is busy (2/2)")
    assert game.handle("charlie", "look", timestamp=4) is None

    monkeypatch.setattr("meshzork_plugin.zork.time.time", lambda: 2000)
    assert game.handle("charlie", "look", timestamp=5).startswith("1/")
    game.handle("alice", "look", timestamp=6)
    assert runner.calls[-1][0] == ["north", "look"]


def test_inactive_save_expires(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("meshzork_plugin.zork.time.time", lambda: 1000)
    runner = FakeRunner()
    game = ZorkStore(
        tmp_path / "sessions.sqlite3",
        runner,
        save_retention_seconds=30 * 86400,
    )
    game.handle("alice", "north", timestamp=1)

    monkeypatch.setattr("meshzork_plugin.zork.time.time", lambda: 1000 + 31 * 86400)
    game.handle("alice", "look", timestamp=2)

    assert runner.calls[-1][0] == ["look"]
