import json
import sqlite3

from meshzork_plugin.zork import ZorkStore, paginate_text


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
