"""Supervised MeshZork service entrypoint."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import signal
from importlib.resources import files
from pathlib import Path
from typing import Protocol

from .config import ConfigError, Settings
from .game import fit_utf8
from .meshcore_client import IncomingMessage, MeshCoreClient
from .zork import FrotzRunner, ZorkStore

logger = logging.getLogger(__name__)
_NUMBERED_PAGE = re.compile(r"^\d+/\d+\s")


class GameHandler(Protocol):
    def handle(self, sender_id: str, command: str, *, timestamp: int | None = None) -> str | None: ...


class MeshZorkService:
    def __init__(self, settings: Settings, meshcore: MeshCoreClient, game: GameHandler) -> None:
        self.settings = settings
        self.meshcore = meshcore
        self.game = game
        self.stop_event = asyncio.Event()

    async def run(self) -> None:
        self._register_signals()
        await self.meshcore.run(self.handle_message, self.stop_event)
        await self.meshcore.close()

    async def handle_message(self, message: IncomingMessage) -> None:
        if message.txt_type != 0:
            return
        command = message.text.strip()
        if not command:
            return
        if len(command.encode("utf-8")) > self.settings.max_command_bytes:
            await self.meshcore.send_text(
                message.sender_prefix,
                fit_utf8(
                    "Command too long. Send HELP for the command list.",
                    self.settings.max_reply_bytes,
                ),
            )
            return

        sender_id = message.sender_prefix[:6].hex()
        logger.info(
            "Game command from sender=%s command_sha=%s",
            sender_id,
            hashlib.sha256(command.encode()).hexdigest()[:10],
        )
        response = await asyncio.to_thread(
            self.game.handle,
            sender_id,
            command,
            timestamp=message.timestamp,
        )
        if response is not None:
            sent = await self.meshcore.send_text(
                message.sender_prefix,
                fit_utf8(response, self.settings.max_reply_bytes),
            )
            if sent and _NUMBERED_PAGE.match(response):
                await self._send_followup_pages(message.sender_prefix, sender_id)

    async def _send_followup_pages(self, recipient: bytes, sender_id: str) -> None:
        take_pages = getattr(self.game, "take_pending_pages", None)
        requeue_pages = getattr(self.game, "requeue_pending_pages", None)
        if not callable(take_pages):
            return
        pages = await asyncio.to_thread(
            take_pages,
            sender_id,
            self.settings.auto_page_limit - 1,
        )
        for index, page in enumerate(pages):
            await asyncio.sleep(self.settings.page_delay_seconds)
            if await self.meshcore.send_text(recipient, page):
                continue
            logger.warning("Could not send follow-up page to sender=%s", sender_id)
            if callable(requeue_pages):
                await asyncio.to_thread(requeue_pages, sender_id, pages[index:])
            break

    def _register_signals(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except NotImplementedError:
                signal.signal(sig, lambda *_: self.stop_event.set())


async def _async_main() -> int:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    meshcore = MeshCoreClient(host=settings.meshcore_host, port=settings.meshcore_port)
    story_path = settings.story_path or Path(
        str(files("meshzork_plugin").joinpath("assets/zork1.z3"))
    )
    runner = FrotzRunner(
        settings.frotz_path,
        story_path,
        settings.database_path.parent / "zork-files",
        seed=settings.random_seed,
    )
    game = ZorkStore(
        settings.database_path,
        runner,
        max_reply_bytes=settings.max_reply_bytes,
        duplicate_ttl_seconds=settings.duplicate_ttl_seconds,
    )
    await MeshZorkService(settings, meshcore, game).run()
    return 0


def main() -> int:
    try:
        return asyncio.run(_async_main())
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
