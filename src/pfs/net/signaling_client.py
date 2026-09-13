"""WebSocket signaling client.

Only SDP/ICE envelopes flow through here; file bytes never do.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets

log = logging.getLogger(__name__)

MessageHandler = Callable[[dict], Awaitable[None]]


class SignalingError(RuntimeError):
    pass


class SignalingClient:
    def __init__(self, url: str, on_message: MessageHandler | None = None):
        self.url = url
        self.on_message = on_message
        self.ws = None
        self.peer_id: str | None = None
        self._recv_task: asyncio.Task | None = None

    async def connect(self, timeout: float = 10.0) -> str:
        self.ws = await asyncio.wait_for(websockets.connect(self.url, max_size=None), timeout)
        welcome = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
        if welcome.get("t") != "welcome":
            raise SignalingError(f"unexpected greeting: {welcome!r}")
        self.peer_id = welcome["peer_id"]
        self._recv_task = asyncio.create_task(self._recv_loop())
        return self.peer_id

    async def _recv_loop(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    log.warning("dropping malformed signaling frame")
                    continue
                if self.on_message:
                    await self.on_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - connection dropped
            log.debug("signaling receive loop ended: %s", exc)

    async def send(self, obj: dict) -> None:
        if self.ws is None:
            raise SignalingError("not connected")
        await self.ws.send(json.dumps(obj))

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._recv_task = None
        if self.ws is not None:
            await self.ws.close()
            self.ws = None
