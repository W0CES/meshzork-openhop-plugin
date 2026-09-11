from pathlib import Path

import pytest

from meshzork_plugin.config import Settings
from meshzork_plugin.game import GameStore
from meshzork_plugin.meshcore_client import IncomingMessage
from meshzork_plugin.service import MeshZorkService


class FakeMeshCore:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, str]] = []

    async def send_text(self, recipient: bytes, text: str) -> bool:
        self.sent.append((recipient, text))
        return True


def settings(tmp_path: Path) -> Settings:
    return Settings(
        meshcore_host="127.0.0.1",
        meshcore_port=5001,
        database_path=tmp_path / "sessions.sqlite3",
        max_reply_bytes=80,
        max_command_bytes=160,
        duplicate_ttl_seconds=600,
        frotz_path="/usr/games/dfrotz",
        story_path=None,
        random_seed=117,
        log_level="INFO",
    )


@pytest.mark.asyncio
async def test_dm_creates_session_and_sends_one_short_reply(tmp_path) -> None:
    mesh = FakeMeshCore()
    service = MeshZorkService(settings(tmp_path), mesh, GameStore(tmp_path / "sessions.sqlite3"))
    message = IncomingMessage(b"ABCDEF", "look", 123, 0, 1, 4.5)

    await service.handle_message(message)

    assert len(mesh.sent) == 1
    assert mesh.sent[0][0] == b"ABCDEF"
    assert len(mesh.sent[0][1].encode("utf-8")) <= 80


@pytest.mark.asyncio
async def test_non_plain_message_is_ignored(tmp_path) -> None:
    mesh = FakeMeshCore()
    service = MeshZorkService(settings(tmp_path), mesh, GameStore(tmp_path / "sessions.sqlite3"))
    await service.handle_message(IncomingMessage(b"ABCDEF", "look", 1, 1, 0, None))
    assert mesh.sent == []
