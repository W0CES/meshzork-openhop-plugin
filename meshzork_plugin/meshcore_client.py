"""Async client for openHop's MeshCore Companion TCP frame server.

The protocol flow mirrors openHop's official openhop-nomad-plugin example:
start/query, wait for MSG_WAITING, drain direct messages, and send plain-text DMs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from openhop_core.companion.constants import (
    CMD_APP_START,
    CMD_DEVICE_QUERY,
    CMD_SEND_TXT_MSG,
    CMD_SYNC_NEXT_MESSAGE,
    FRAME_INBOUND_PREFIX,
    FRAME_OUTBOUND_PREFIX,
    PUSH_CODE_MSG_WAITING,
    RESP_CODE_CHANNEL_MSG_RECV,
    RESP_CODE_CHANNEL_MSG_RECV_V3,
    RESP_CODE_CONTACT_MSG_RECV,
    RESP_CODE_CONTACT_MSG_RECV_V3,
    RESP_CODE_CURR_TIME,
    RESP_CODE_ERR,
    RESP_CODE_NO_MORE_MESSAGES,
    RESP_CODE_SENT,
    TXT_TYPE_PLAIN,
)

logger = logging.getLogger(__name__)


class MeshCoreProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class IncomingMessage:
    sender_prefix: bytes
    text: str
    timestamp: int
    txt_type: int
    path_len: int
    snr: float | None


class MeshCoreClient:
    def __init__(self, *, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._command_lock = asyncio.Lock()
        self._response_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._message_waiting = asyncio.Event()
        self._stop_requested = asyncio.Event()
        self._reader_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        self._stop_requested.set()
        self._message_waiting.set()
        await self._teardown_connection()

    async def run(
        self,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        backoff = [1, 2, 4, 8, 15, 30]
        attempt = 0
        while not stop_event.is_set() and not self._stop_requested.is_set():
            try:
                await self._connect_and_process(on_message, stop_event)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect after any transport failure
                logger.warning("MeshCore connection lost: %s", exc)
            if stop_event.is_set() or self._stop_requested.is_set():
                break
            delay = backoff[min(attempt, len(backoff) - 1)]
            attempt += 1
            logger.info("Reconnecting to MeshCore in %ss", delay)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def send_text(self, recipient_prefix: bytes, text: str) -> bool:
        if len(recipient_prefix) < 6:
            raise ValueError("recipient_prefix must contain at least 6 bytes")
        for attempt in range(3):
            try:
                async with self._command_lock:
                    payload = (
                        bytes([CMD_SEND_TXT_MSG, TXT_TYPE_PLAIN, 1])
                        + struct.pack("<I", 0)
                        + recipient_prefix[:6]
                        + text.encode("utf-8", errors="replace")
                    )
                    frame = await self._send_command_expect(
                        payload,
                        expected_codes={RESP_CODE_SENT, RESP_CODE_ERR},
                        max_unexpected=4,
                    )
                if frame[0] == RESP_CODE_SENT:
                    return True
                if frame[0] == RESP_CODE_ERR:
                    logger.warning("MeshCore rejected outgoing DM")
                    return False
            except TimeoutError:
                if attempt == 2:
                    return False
                await asyncio.sleep(2**attempt)
        return False

    async def _connect_and_process(
        self,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        self._response_queue = asyncio.Queue()
        self._message_waiting.clear()
        self._reader_task = asyncio.create_task(self._reader_loop())
        try:
            async with self._command_lock:
                await self._send_command_expect(bytes([CMD_APP_START]) + b"\x00" * 7)
                await self._send_command_expect(bytes([CMD_DEVICE_QUERY, 3]))
            logger.info("Connected to Companion %s:%s", self._host, self._port)
            while not stop_event.is_set() and not self._stop_requested.is_set():
                try:
                    await asyncio.wait_for(self._message_waiting.wait(), timeout=2)
                except TimeoutError:
                    self._message_waiting.set()
                self._message_waiting.clear()
                await self._drain_messages(on_message)
                if self._reader_task.done():
                    error = self._reader_task.exception()
                    if error:
                        raise error
                    raise ConnectionError("MeshCore reader stopped")
        finally:
            await self._teardown_connection()

    async def _drain_messages(
        self, on_message: Callable[[IncomingMessage], Awaitable[None]]
    ) -> None:
        response_codes = {
            RESP_CODE_NO_MORE_MESSAGES,
            RESP_CODE_CHANNEL_MSG_RECV,
            RESP_CODE_CHANNEL_MSG_RECV_V3,
            RESP_CODE_CONTACT_MSG_RECV,
            RESP_CODE_CONTACT_MSG_RECV_V3,
        }
        while True:
            async with self._command_lock:
                frame = await self._send_command_expect(
                    bytes([CMD_SYNC_NEXT_MESSAGE]),
                    expected_codes=response_codes,
                    max_unexpected=4,
                )
            if frame[0] == RESP_CODE_NO_MORE_MESSAGES:
                return
            if frame[0] in {RESP_CODE_CONTACT_MSG_RECV, RESP_CODE_CONTACT_MSG_RECV_V3}:
                message = self._parse_contact_message(frame)
                if message is not None:
                    await on_message(message)

    @staticmethod
    def _parse_contact_message(frame: bytes) -> IncomingMessage | None:
        if frame[0] == RESP_CODE_CONTACT_MSG_RECV_V3:
            if len(frame) < 16:
                return None
            return IncomingMessage(
                sender_prefix=frame[4:10],
                text=frame[16:].decode("utf-8", errors="replace").rstrip("\x00"),
                timestamp=struct.unpack("<I", frame[12:16])[0],
                txt_type=frame[11],
                path_len=frame[10],
                snr=struct.unpack("b", frame[1:2])[0] / 4.0,
            )
        if len(frame) < 13:
            return None
        return IncomingMessage(
            sender_prefix=frame[1:7],
            text=frame[13:].decode("utf-8", errors="replace").rstrip("\x00"),
            timestamp=struct.unpack("<I", frame[9:13])[0],
            txt_type=frame[8],
            path_len=frame[7],
            snr=None,
        )

    async def _reader_loop(self) -> None:
        if self._reader is None:
            raise ConnectionError("reader not initialized")
        while True:
            prefix = await self._reader.readexactly(1)
            if prefix[0] != FRAME_OUTBOUND_PREFIX:
                raise MeshCoreProtocolError(f"unexpected frame prefix {prefix[0]:#x}")
            length = struct.unpack("<H", await self._reader.readexactly(2))[0]
            payload = await self._reader.readexactly(length)
            if not payload:
                continue
            if payload[0] >= 0x80:
                if payload[0] == PUSH_CODE_MSG_WAITING:
                    self._message_waiting.set()
                continue
            await self._response_queue.put(payload)

    async def _send_command(self, payload: bytes) -> None:
        if self._writer is None:
            raise ConnectionError("MeshCore socket not connected")
        self._writer.write(
            bytes([FRAME_INBOUND_PREFIX]) + struct.pack("<H", len(payload)) + payload
        )
        await self._writer.drain()

    async def _next_response(self) -> bytes:
        while True:
            frame = await asyncio.wait_for(self._response_queue.get(), timeout=30)
            if frame and frame[0] != RESP_CODE_CURR_TIME:
                return frame

    async def _send_command_expect(
        self,
        payload: bytes,
        *,
        expected_codes: set[int] | None = None,
        max_unexpected: int = 2,
    ) -> bytes:
        await self._send_command(payload)
        unexpected = 0
        while True:
            frame = await self._next_response()
            if expected_codes is None or frame[0] in expected_codes:
                return frame
            unexpected += 1
            if unexpected >= max_unexpected:
                return frame

    async def _teardown_connection(self) -> None:
        task, self._reader_task = self._reader_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
