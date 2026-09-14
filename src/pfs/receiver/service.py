"""Receiver side: log in, browse shares, download over WebRTC."""

from __future__ import annotations

import asyncio
import logging

from ..common.manifest import Entry
from ..net.peer import Peer
from ..net.signaling_client import SignalingClient
from ..net.transfer import FileClient

log = logging.getLogger(__name__)


class ReceiverService:
    def __init__(
        self,
        signal_host: str,
        signal_port: int,
        account: str,
        password: str,
        dest: str,
        tls: bool = False,
        ice_servers: list | None = None,
        concurrency: int = 4,
        max_retries: int = 3,
    ):
        self.signal_host = signal_host
        self.signal_port = signal_port
        self.account = account
        self.password = password
        self.dest = dest
        self.tls = tls
        self.ice_servers = ice_servers or []
        self.concurrency = concurrency
        self.max_retries = max_retries

        self.signaling: SignalingClient | None = None
        self.peer: Peer | None = None
        self.client: FileClient | None = None
        self.entries: list[Entry] = []
        self.share_id: str | None = None
        self.presence: list[str] = []

        self._login: asyncio.Future | None = None
        self._shares: asyncio.Future | None = None
        self._manifest: asyncio.Future | None = None
        self._peer_ready: asyncio.Future | None = None
        self._open: asyncio.Future | None = None

    async def start(self, timeout: float = 15.0) -> None:
        scheme = "wss" if self.tls else "ws"
        url = f"{scheme}://{self.signal_host}:{self.signal_port}/ws"
        self.signaling = SignalingClient(url, self._on_message)
        await self.signaling.connect()
        self._login = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "login", "name": self.account, "password": self.password})
        await asyncio.wait_for(self._login, timeout)

    async def list_shares(self, timeout: float = 15.0) -> list[dict]:
        assert self.signaling is not None
        self._shares = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "list_shares"})
        return await asyncio.wait_for(self._shares, timeout)

    async def get_manifest(self, share_id: str, timeout: float = 15.0) -> list[Entry]:
        assert self.signaling is not None
        self._manifest = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "get_manifest", "share_id": share_id})
        data = await asyncio.wait_for(self._manifest, timeout)
        self.entries = [Entry.from_dict(d) for d in data["entries"]]
        self.share_id = share_id
        return self.entries

    async def open_share(self, share_id: str, timeout: float = 20.0) -> None:
        """Connect to the share owner and wait for the data channels."""
        assert self.signaling is not None
        if self.peer is not None:
            await self.peer.close()
            self.peer = None
            self.client = None
        self._peer_ready = asyncio.get_event_loop().create_future()
        self._open = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "connect", "share_id": share_id})

        info = await asyncio.wait_for(self._peer_ready, timeout)
        owner = info["owner"]
        self.client = FileClient(None, self.dest, concurrency=self.concurrency, max_retries=self.max_retries)
        self.peer = Peer(
            self.signaling,
            owner,
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
        if kind == "login_ok":
            if self._login and not self._login.done():
                self._login.set_result(msg)
        elif kind == "shares":
            if self._shares and not self._shares.done():
                self._shares.set_result(list(msg.get("items", [])))
        elif kind == "manifest":
            if self._manifest and not self._manifest.done():
                self._manifest.set_result(msg)
        elif kind == "presence":
            self.presence = list(msg.get("accounts", []))
        elif kind == "peer_ready":
            if self._peer_ready and not self._peer_ready.done():
                self._peer_ready.set_result(msg)
        elif kind == "signal":
            if self.peer:
                await self.peer.handle_signal(msg["payload"])
        elif kind == "error":
            self._fail_pending(RuntimeError(msg.get("msg", "server error")))

    def _fail_pending(self, exc: Exception) -> None:
        for fut in (self._login, self._shares, self._manifest, self._peer_ready, self._open):
            if fut and not fut.done():
                fut.set_exception(exc)

    async def download_file(self, path: str, size: int, progress=None) -> str:
        assert self.client is not None
        return await self.client.download_file(path, size, progress=progress)

    async def close(self) -> None:
        if self.peer:
            try:
                await self.peer.close()
            except Exception:  # noqa: BLE001
                log.debug("error closing peer", exc_info=True)
            self.peer = None
        if self.signaling:
            await self.signaling.close()
            self.signaling = None
