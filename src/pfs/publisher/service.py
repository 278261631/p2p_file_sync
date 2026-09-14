"""Publisher side: log in, publish a folder listing, serve receivers."""

from __future__ import annotations

import asyncio
import logging
import os

from ..common.manifest import scan_folder
from ..net.peer import Peer
from ..net.signaling_client import SignalingClient
from ..net.transfer import FileServer

log = logging.getLogger(__name__)


async def _noop_data(_buf: bytes) -> None:
    return None


class PublisherService:
    def __init__(
        self,
        signal_host: str,
        signal_port: int,
        account: str,
        password: str,
        tls: bool = False,
        ice_servers: list | None = None,
    ):
        self.signal_host = signal_host
        self.signal_port = signal_port
        self.account = account
        self.password = password
        self.tls = tls
        self.ice_servers = ice_servers or []

        self.root: str | None = None
        self.share_name: str | None = None
        self.signaling: SignalingClient | None = None
        self.share_id: str | None = None
        self.peers: dict[str, Peer] = {}
        self.servers: dict[str, FileServer] = {}
        self.presence: list[str] = []
        self._login: asyncio.Future | None = None
        self._published: asyncio.Future | None = None
        self._shares: asyncio.Future | None = None
        self._events: asyncio.Queue = asyncio.Queue()

    @property
    def peer_count(self) -> int:
        return len(self.peers)

    async def connect_and_login(self, timeout: float = 15.0) -> None:
        scheme = "wss" if self.tls else "ws"
        url = f"{scheme}://{self.signal_host}:{self.signal_port}/ws"
        self.signaling = SignalingClient(url, self._on_message)
        await self.signaling.connect()
        self._login = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "login", "name": self.account, "password": self.password})
        await asyncio.wait_for(self._login, timeout)

    async def publish(self, root: str, share_name: str | None = None, timeout: float = 15.0) -> str:
        assert self.signaling is not None
        self.root = root
        self.share_name = share_name or os.path.basename(os.path.abspath(root)) or "share"
        entries = scan_folder(root)
        self._published = asyncio.get_event_loop().create_future()
        await self.signaling.send(
            {"t": "publish", "share": {"name": self.share_name, "entries": [e.to_dict() for e in entries]}}
        )
        self.share_id = await asyncio.wait_for(self._published, timeout)
        return self.share_id

    async def start(self, root: str, share_name: str | None = None) -> str:
        await self.connect_and_login()
        return await self.publish(root, share_name)

    async def list_shares(self, timeout: float = 15.0) -> list[dict]:
        """List shares currently advertised on the signaling server."""
        assert self.signaling is not None
        self._shares = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "list_shares"})
        return await asyncio.wait_for(self._shares, timeout)

    async def next_event(self) -> tuple[str, object]:
        """Await ``(kind, payload)`` where kind is joined/left/presence."""
        return await self._events.get()

    async def unpublish(self) -> None:
        if self.signaling and self.share_id:
            await self.signaling.send({"t": "unpublish"})
        for peer in list(self.peers.values()):
            await peer.close()
        self.peers.clear()
        self.servers.clear()
        self.share_id = None

    async def _on_message(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "login_ok":
            if self._login and not self._login.done():
                self._login.set_result(msg)
        elif kind == "published":
            if self._published and not self._published.done():
                self._published.set_result(msg["share_id"])
        elif kind == "error":
            self._fail_pending(RuntimeError(msg.get("msg", "server error")))
        elif kind == "peer_request":
            self._add_peer(msg["peer_id"])
        elif kind == "signal":
            peer = self.peers.get(msg.get("from"))
            if peer:
                await peer.handle_signal(msg["payload"])
        elif kind == "peer_left":
            await self._drop_peer(msg["peer_id"])
        elif kind == "shares":
            if self._shares and not self._shares.done():
                self._shares.set_result(list(msg.get("items", [])))
        elif kind == "presence":
            self.presence = list(msg.get("accounts", []))
            self._events.put_nowait(("presence", self.presence))

    def _fail_pending(self, exc: Exception) -> None:
        for fut in (self._login, self._published, self._shares):
            if fut and not fut.done():
                fut.set_exception(exc)

    def _add_peer(self, peer_id: str) -> None:
        if peer_id in self.peers:
            return
        server = FileServer(None, self.root)
        peer = Peer(
            self.signaling,
            peer_id,
            self.ice_servers,
            on_ctrl=server.on_ctrl,
            on_data=_noop_data,
            on_close=lambda pid=peer_id: asyncio.ensure_future(self._drop_peer(pid)),
        )
        server.peer = peer
        self.peers[peer_id] = peer
        self.servers[peer_id] = server
        self._events.put_nowait(("joined", peer_id))
        log.info("receiver connected: %s", peer_id)

    async def _drop_peer(self, peer_id: str) -> None:
        peer = self.peers.pop(peer_id, None)
        self.servers.pop(peer_id, None)
        if peer:
            await peer.close()
            self._events.put_nowait(("left", peer_id))
            log.info("receiver disconnected: %s", peer_id)

    async def close(self) -> None:
        for peer in list(self.peers.values()):
            await peer.close()
        self.peers.clear()
        self.servers.clear()
        if self.signaling:
            await self.signaling.close()
