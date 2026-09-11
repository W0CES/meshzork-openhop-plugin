"""Zork I adapter with per-sender replayable sessions and LoRa paging."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Protocol

import pexpect

from .game import fit_utf8


class ZorkEngineError(RuntimeError):
    """Raised when the isolated Z-machine interpreter cannot complete a turn."""


class StoryRunner(Protocol):
    def run(self, commands: list[str], sender_id: str) -> str: ...


class FrotzRunner:
    """Run a deterministic, filesystem-restricted dfrotz replay for one turn."""

    _PROMPT = re.compile(r"(?m)^(?:>|\)|T|t|D|}) ?(?=\r?$)")
    _ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    _STATUS_LINE = re.compile(r"\bScore:\s*-?\d+\s+Moves:\s*\d+\b", re.IGNORECASE)

    def __init__(
        self,
        executable: str,
        story_path: Path,
        session_root: Path,
        *,
        seed: int = 117,
        timeout_seconds: int = 15,
    ) -> None:
        self.executable = executable
        self.story_path = story_path
        self.session_root = session_root
        self.seed = seed
        self.timeout_seconds = timeout_seconds

    def run(self, commands: list[str], sender_id: str) -> str:
        session_dir = self.session_root / sender_id
        session_dir.mkdir(parents=True, exist_ok=True)
        args = [
            "-q",
            "-m",
            "-p",
            "-s",
            str(self.seed),
            "-w",
            "120",
            "-R",
            str(session_dir),
            str(self.story_path),
        ]
        child: pexpect.spawn | None = None
        try:
            child = pexpect.spawn(
                self.executable,
                args=args,
                encoding="utf-8",
                codec_errors="replace",
                timeout=self.timeout_seconds,
                echo=False,
            )
            output = self._read_turn(child)
            for command in commands:
                child.sendline(command)
                output = self._read_turn(child)
        except (OSError, pexpect.ExceptionPexpect) as exc:
            raise ZorkEngineError(f"dfrotz failed: {exc}") from exc
        finally:
            if child is not None and child.isalive():
                child.close(force=True)
        return self._clean(output)

    def _read_turn(self, child: pexpect.spawn) -> str:
        index = child.expect([self._PROMPT, pexpect.EOF, pexpect.TIMEOUT])
        if index == 2:
            raise ZorkEngineError("dfrotz timed out waiting for the next prompt")
        return child.before or ""

    @classmethod
    def _clean(cls, text: str) -> str:
        text = cls._ANSI.sub("", text).replace("\r", "")
        lines = [
            line.rstrip()
            for line in text.splitlines()
            if not cls._STATUS_LINE.search(line)
        ]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines).strip()


class ZorkStore:
    """Persist each player's command history and replay it deterministically."""

    def __init__(
        self,
        database_path: Path | str,
        runner: StoryRunner,
        *,
        max_reply_bytes: int = 145,
        duplicate_ttl_seconds: int = 600,
        max_history_commands: int = 2500,
    ) -> None:
        self.database_path = Path(database_path)
        self.runner = runner
        self.max_reply_bytes = max_reply_bytes
        self.duplicate_ttl_seconds = duplicate_ttl_seconds
        self.max_history_commands = max_history_commands
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS zork_sessions (
                    sender_id TEXT PRIMARY KEY,
                    history_json TEXT NOT NULL DEFAULT '[]',
                    pending_json TEXT NOT NULL DEFAULT '[]',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_messages (
                    dedupe_key TEXT PRIMARY KEY,
                    processed_at INTEGER NOT NULL
                );
                """
            )

    def handle(self, sender_id: str, command: str, *, timestamp: int | None = None) -> str | None:
        normalized = " ".join(command.strip().split())
        lower = normalized.lower()
        now = int(time.time())
        digest = hashlib.sha256(lower.encode("utf-8")).hexdigest()[:20]
        dedupe_key = f"{sender_id}:{int(timestamp or 0)}:{digest}"

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

            history, pending = self._load_session(connection, sender_id, now)
            if lower in {"next", "more"}:
                return self._next_page(connection, sender_id, history, pending, now)
            if lower in {"help", "?"}:
                return fit_utf8(
                    "Send one Zork command per DM. Replies continue automatically; NEXT retrieves "
                    "any remaining text. RESET starts over. SAVE is automatic.",
                    self.max_reply_bytes,
                )
            if lower in {"save", "restore"}:
                return "Your game is saved automatically after every accepted command."
            if lower in {"quit", "restart", "reset", "new", "/reset", "/new"}:
                history = []
                try:
                    output = self.runner.run(history, sender_id)
                except ZorkEngineError:
                    return "The Zork engine is unavailable. Your previous game is still saved."
                return self._save_response(connection, sender_id, history, output, now)
            if lower.startswith("\\"):
                return "Interpreter control commands are disabled. Send HELP for MeshZork commands."
            if len(history) >= self.max_history_commands:
                return "This game reached its command limit. Send RESET to start a new game."

            candidate = [*history, normalized]
            try:
                output = self.runner.run(candidate, sender_id)
            except ZorkEngineError:
                return "The Zork engine had a problem. Your previous turn is still saved; try again."
            return self._save_response(connection, sender_id, candidate, output, now)

    def _load_session(
        self, connection: sqlite3.Connection, sender_id: str, now: int
    ) -> tuple[list[str], list[str]]:
        row = connection.execute(
            "SELECT history_json, pending_json FROM zork_sessions WHERE sender_id=?",
            (sender_id,),
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO zork_sessions(sender_id, history_json, pending_json, updated_at) "
                "VALUES (?, '[]', '[]', ?)",
                (sender_id, now),
            )
            return [], []
        return json.loads(row["history_json"]), json.loads(row["pending_json"])

    def _save_response(
        self,
        connection: sqlite3.Connection,
        sender_id: str,
        history: list[str],
        output: str,
        now: int,
    ) -> str:
        pages = paginate_text(output or "The game produced no text. Try LOOK.", self.max_reply_bytes)
        connection.execute(
            "UPDATE zork_sessions SET history_json=?, pending_json=?, updated_at=? WHERE sender_id=?",
            (json.dumps(history), json.dumps(pages[1:]), now, sender_id),
        )
        return pages[0]

    def _next_page(
        self,
        connection: sqlite3.Connection,
        sender_id: str,
        history: list[str],
        pending: list[str],
        now: int,
    ) -> str:
        if not pending:
            return "No more text is waiting. Send LOOK or another game command."
        page = pending.pop(0)
        connection.execute(
            "UPDATE zork_sessions SET history_json=?, pending_json=?, updated_at=? WHERE sender_id=?",
            (json.dumps(history), json.dumps(pending), now, sender_id),
        )
        return page

    def take_pending_pages(self, sender_id: str, limit: int) -> list[str]:
        """Atomically reserve pending pages for automatic radio delivery."""
        if limit <= 0:
            return []
        now = int(time.time())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT pending_json FROM zork_sessions WHERE sender_id=?",
                (sender_id,),
            ).fetchone()
            if row is None:
                return []
            pending = json.loads(row["pending_json"])
            selected = pending[:limit]
            connection.execute(
                "UPDATE zork_sessions SET pending_json=?, updated_at=? WHERE sender_id=?",
                (json.dumps(pending[limit:]), now, sender_id),
            )
            return selected

    def requeue_pending_pages(self, sender_id: str, pages: list[str]) -> None:
        """Put unsent automatic pages back so the player can request NEXT."""
        if not pages:
            return
        now = int(time.time())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT pending_json FROM zork_sessions WHERE sender_id=?",
                (sender_id,),
            ).fetchone()
            if row is None:
                return
            pending = json.loads(row["pending_json"])
            connection.execute(
                "UPDATE zork_sessions SET pending_json=?, updated_at=? WHERE sender_id=?",
                (json.dumps([*pages, *pending]), now, sender_id),
            )


def paginate_text(text: str, max_bytes: int) -> list[str]:
    """Split output into numbered UTF-8-safe radio packets."""
    compact = " ".join(text.replace("\t", " ").split())
    if len(compact.encode("utf-8")) <= max_bytes:
        return [compact]

    body_budget = max(20, max_bytes - 18)
    words = compact.split(" ")
    bodies: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate.encode("utf-8")) <= body_budget:
            current = candidate
            continue
        if current:
            bodies.append(current)
        current = fit_utf8(word, body_budget)
    if current:
        bodies.append(current)

    total = len(bodies)
    return [
        fit_utf8(f"{index}/{total} {body}" + (" NEXT" if index < total else ""), max_bytes)
        for index, body in enumerate(bodies, start=1)
    ]
