"""Receiver side: join a room and download selected files."""

from __future__ import annotations

import asyncio
import logging

from ..common.invite import Invite
from ..common.manifest import Entry
from ..net.peer import Peer
from ..net.signaling_client import SignalingClient
from ..net.transfer import FileClient

log = logging.getLogger(__name__)


class ReceiverService:
    def __init__(
        self,
        invite: Invite,
        dest: str,
        ice_servers: list | None = None,
        concurrency: int = 4,
        max_retries: int = 3,
    ):
        self.invite = invite
        self.dest = dest
        self.ice_servers = ice_servers or []
        self.concurrency = concurrency
        self.max_retries = max_retries

        self.signaling: SignalingClient | None = None
        self.peer: Peer | None = None
        self.client: FileClient | None = None
        self._joined: asyncio.Future | None = None
        self._open: asyncio.Future | None = None

    async def start(self, timeout: float = 20.0) -> None:
        self.signaling = SignalingClient(self.invite.ws_url, self._on_message)
        await self.signaling.connect()

        self._joined = asyncio.get_event_loop().create_future()
        self._open = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "join", "sid": self.invite.sid, "token": self.invite.token})

        info = await asyncio.wait_for(self._joined, timeout)
        publisher_id = info["publisher"]

        self.client = FileClient(None, self.dest, concurrency=self.concurrency, max_retries=self.max_retries)
        self.peer = Peer(
            self.signaling,
            publisher_id,
            self.ice_servers,
            on_ctrl=self.client.on_ctrl,
            on_data=self.client.on_data,
            on_open=self._on_open,
        )
        self.client.peer = self.peer
        self.peer.create_channels()
        await self.peer.offer()
        await asyncio.wait_for(self._open, timeout)

    def _on_open(self) -> None:
        if self._open and not self._open.done():
            self._open.set_result(True)

    async def _on_message(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "joined":
            if self._joined and not self._joined.done():
                self._joined.set_result(msg)
        elif kind == "signal":
            if self.peer:
                await self.peer.handle_signal(msg["payload"])
        elif kind == "error":
            exc = RuntimeError(msg.get("msg", "signaling error"))
            for fut in (self._joined, self._open):
                if fut and not fut.done():
                    fut.set_exception(exc)

    async def get_manifest(self) -> list[Entry]:
        assert self.client is not None
        return await self.client.request_manifest()

    async def download_file(self, path: str, size: int, progress=None) -> str:
        assert self.client is not None
        return await self.client.download_file(path, size, progress=progress)

    async def close(self) -> None:
        if self.peer:
            await self.peer.close()
        if self.signaling:
            await self.signaling.close()
