"""WebSocket signaling client.

Only SDP/ICE envelopes flow through here; file bytes never do.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets

from .tls import build_client_ssl_context

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
        kwargs: dict = {"max_size": None}
        if self.url.startswith("wss"):
            kwargs["ssl"] = build_client_ssl_context()
        self.ws = await asyncio.wait_for(websockets.connect(self.url, **kwargs), timeout)
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
        """Idempotent shutdown; never raises so it is safe from a loop teardown."""
        recv, self._recv_task = self._recv_task, None
        if recv is not None:
            recv.cancel()
            try:
                await recv
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                log.debug("signaling receive loop error on close", exc_info=True)
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                log.debug("error closing signaling websocket", exc_info=True)
