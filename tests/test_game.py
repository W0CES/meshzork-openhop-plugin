from meshzork_plugin.game import GameStore, fit_utf8


def test_each_sender_has_an_independent_persistent_session(tmp_path) -> None:
    database = tmp_path / "sessions.sqlite3"
    game = GameStore(database)

    assert "Faded Trail" in game.handle("alice", "look", timestamp=1)
    assert "Whisper Hollow" in game.handle("alice", "east", timestamp=2)
    assert "Taken" in game.handle("alice", "take key", timestamp=3)

    restarted = GameStore(database)
    assert restarted.handle("alice", "inventory", timestamp=4) == "You carry: brass key."
    assert restarted.handle("bob", "inventory", timestamp=1) == "You carry nothing."


def test_winning_path_and_locked_door(tmp_path) -> None:
    game = GameStore(tmp_path / "sessions.sqlite3")
    assert "locked" in game.handle("player", "north", timestamp=1)
    game.handle("player", "south", timestamp=2)
    game.handle("player", "east", timestamp=3)
    game.handle("player", "take key", timestamp=4)
    game.handle("player", "west", timestamp=5)
    game.handle("player", "north", timestamp=6)
    assert "Victory" in game.handle("player", "north", timestamp=7)
    assert game.handle("player", "score", timestamp=8).startswith("Score 10/10")


def test_radio_retry_is_deduplicated(tmp_path) -> None:
    game = GameStore(tmp_path / "sessions.sqlite3")
    assert game.handle("player", "east", timestamp=10) is not None
    assert game.handle("player", "east", timestamp=10) is None


def test_reply_fits_one_utf8_packet() -> None:
    result = fit_utf8("cafe \N{GRINNING FACE} " * 30, 50)
    assert len(result.encode("utf-8")) <= 50
    assert result.endswith("...")
