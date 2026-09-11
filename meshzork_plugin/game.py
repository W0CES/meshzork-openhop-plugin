"""Small original interactive-fiction world with SQLite-backed player sessions."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

START_ROOM = "trail"


@dataclass(frozen=True)
class Room:
    title: str
    description: str
    exits: dict[str, str]


ROOMS = {
    "trail": Room(
        "Faded Trail",
        "Rain taps an iron door to the north. A narrow path runs east.",
        {"north": "gate", "east": "hollow"},
    ),
    "gate": Room(
        "Iron Door",
        "A locked iron door blocks the north. The trail is south.",
        {"south": "trail"},
    ),
    "hollow": Room(
        "Whisper Hollow",
        "A brass key glints under wet leaves. The trail is west.",
        {"west": "trail"},
    ),
    "tower": Room(
        "Moon Tower",
        "Starlight fills a silent observatory. You found the tower. Victory!",
        {"south": "gate"},
    ),
}

ALIASES = {"n": "north", "s": "south", "e": "east", "w": "west", "l": "look", "i": "inventory"}


class GameStore:
    """Owns all game state; each sender prefix has an independent saved session."""

    def __init__(self, database_path: Path | str, *, duplicate_ttl_seconds: int = 600) -> None:
        self.database_path = Path(database_path)
        self.duplicate_ttl_seconds = duplicate_ttl_seconds
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    sender_id TEXT PRIMARY KEY,
                    room TEXT NOT NULL,
                    has_key INTEGER NOT NULL DEFAULT 0,
                    moves INTEGER NOT NULL DEFAULT 0,
                    won INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_messages (
                    dedupe_key TEXT PRIMARY KEY,
                    processed_at INTEGER NOT NULL
                );
                """
            )

    def handle(self, sender_id: str, command: str, *, timestamp: int | None = None) -> str | None:
        """Apply one command atomically. None means an already-processed radio retry."""
        normalized = " ".join(command.strip().lower().split())
        now = int(time.time())
        radio_timestamp = int(timestamp or 0)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
        dedupe_key = f"{sender_id}:{radio_timestamp}:{digest}"

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM processed_messages WHERE processed_at < ?",
                (now - self.duplicate_ttl_seconds,),
            )
            try:
                connection.execute(
                    "INSERT INTO processed_messages(dedupe_key, processed_at) VALUES (?, ?)",
                    (dedupe_key, now),
                )
            except sqlite3.IntegrityError:
                return None

            row = connection.execute(
                "SELECT room, has_key, moves, won FROM sessions WHERE sender_id = ?",
                (sender_id,),
            ).fetchone()
            if row is None:
                state = {"room": START_ROOM, "has_key": 0, "moves": 0, "won": 0}
                connection.execute(
                    "INSERT INTO sessions(sender_id, room, has_key, moves, won, updated_at) "
                    "VALUES (?, ?, 0, 0, 0, ?)",
                    (sender_id, START_ROOM, now),
                )
            else:
                state = dict(row)

            response = self._apply(connection, sender_id, state, normalized, now)
            return response

    def _apply(
        self,
        connection: sqlite3.Connection,
        sender_id: str,
        state: dict[str, int | str],
        command: str,
        now: int,
    ) -> str:
        command = ALIASES.get(command, command)
        room_id = str(state["room"])
        room = ROOMS[room_id]

        if command in {"", "start", "look"}:
            return self._describe(room_id, state)
        if command in {"help", "?"}:
            return "Commands: LOOK, N/S/E/W, TAKE KEY, INVENTORY, SCORE, RESET. DM one command at a time."
        if command in {"reset", "new", "/reset", "/new"}:
            connection.execute(
                "UPDATE sessions SET room=?, has_key=0, moves=0, won=0, updated_at=? WHERE sender_id=?",
                (START_ROOM, now, sender_id),
            )
            return "New game. " + self._describe(START_ROOM, {"has_key": 0, "won": 0})
        if command in {"inventory", "inv"}:
            return "You carry: brass key." if state["has_key"] else "You carry nothing."
        if command == "score":
            score = 10 if state["won"] else (2 if state["has_key"] else 0)
            return f"Score {score}/10. Moves {state['moves']}."
        if command in {"take key", "get key", "take brass key"}:
            if room_id != "hollow":
                return "There is no key here."
            if state["has_key"]:
                return "You already have the brass key."
            connection.execute(
                "UPDATE sessions SET has_key=1, moves=moves+1, updated_at=? WHERE sender_id=?",
                (now, sender_id),
            )
            return "Taken. The brass key is warm. Exits: west."

        direction = command.removeprefix("go ")
        direction = ALIASES.get(direction, direction)
        if direction in {"north", "south", "east", "west"}:
            if room_id == "gate" and direction == "north":
                if not state["has_key"]:
                    return "The iron door is locked. A key may be nearby. Exit: south."
                destination = "tower"
            else:
                destination = room.exits.get(direction)
            if destination is None:
                return f"You cannot go {direction}. Exits: {', '.join(room.exits)}."
            won = 1 if destination == "tower" else int(state["won"])
            connection.execute(
                "UPDATE sessions SET room=?, moves=moves+1, won=?, updated_at=? WHERE sender_id=?",
                (destination, won, now, sender_id),
            )
            next_state = {**state, "room": destination, "won": won}
            return self._describe(destination, next_state)

        return "I do not understand. Try HELP, LOOK, N/S/E/W, TAKE KEY, INVENTORY, SCORE, or RESET."

    @staticmethod
    def _describe(room_id: str, state: dict[str, int | str]) -> str:
        room = ROOMS[room_id]
        description = room.description
        if room_id == "hollow" and state.get("has_key"):
            description = "Wet leaves whisper underfoot. The trail is west."
        exits = list(room.exits)
        if room_id == "gate":
            exits = ["north", "south"]
        return f"{room.title}: {description} Exits: {', '.join(exits)}."


def fit_utf8(text: str, max_bytes: int) -> str:
    """Return one valid UTF-8 packet no larger than max_bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = "..."
    budget = max_bytes - len(suffix)
    clipped = encoded[: max(0, budget)]
    while clipped:
        try:
            return clipped.decode("utf-8").rstrip() + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix[:max_bytes]
