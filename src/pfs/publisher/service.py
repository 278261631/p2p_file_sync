"""Publisher side: expose a folder and accept receivers."""

from __future__ import annotations

import asyncio
import logging

from ..common.invite import Invite
from ..net.peer import Peer
from ..net.signaling_client import SignalingClient
from ..net.transfer import FileServer

log = logging.getLogger(__name__)


async def _noop_data(_buf: bytes) -> None:
    return None


class PublisherService:
    def __init__(
        self,
        root: str,
        signal_host: str,
        signal_port: int,
        host: str | None = None,
        port: int | None = None,
        tls: bool = False,
        ice_servers: list | None = None,
    ):
        self.root = root
        self.signal_host = signal_host
        self.signal_port = signal_port
        self.host = host or signal_host
        self.port = port or signal_port
        self.tls = tls
        self.ice_servers = ice_servers or []

        self.signaling: SignalingClient | None = None
        self.invite: Invite | None = None
        self.peers: dict[str, Peer] = {}
        self.servers: dict[str, FileServer] = {}
        self._created: asyncio.Future | None = None
        self._peer_events: asyncio.Queue = asyncio.Queue()

    @property
    def peer_count(self) -> int:
        return len(self.peers)

    async def start(self) -> Invite:
        url = f"ws://{self.signal_host}:{self.signal_port}/ws"
        self.signaling = SignalingClient(url, self._on_message)
        await self.signaling.connect()
        self._created = asyncio.get_event_loop().create_future()
        await self.signaling.send({"t": "create"})
        info = await asyncio.wait_for(self._created, 10.0)
        self.invite = Invite(self.host, self.port, info["sid"], info["token"], self.tls)
        return self.invite

    async def next_peer_event(self) -> tuple[str, str]:
        """Await ``(kind, peer_id)`` where kind is ``joined`` or ``left``."""
        return await self._peer_events.get()

    async def _on_message(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "created":
            if self._created and not self._created.done():
                self._created.set_result(msg)
        elif kind == "peer_joined":
            self._add_peer(msg["peer_id"])
        elif kind == "signal":
            peer = self.peers.get(msg.get("from"))
            if peer:
                await peer.handle_signal(msg["payload"])
        elif kind == "peer_left":
            await self._drop_peer(msg["peer_id"])

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
        self._peer_events.put_nowait(("joined", peer_id))
        log.info("receiver joined: %s", peer_id)

    async def _drop_peer(self, peer_id: str) -> None:
        peer = self.peers.pop(peer_id, None)
        self.servers.pop(peer_id, None)
        if peer:
            await peer.close()
            self._peer_events.put_nowait(("left", peer_id))
            log.info("receiver left: %s", peer_id)

    async def close(self) -> None:
        for peer in list(self.peers.values()):
            await peer.close()
        self.peers.clear()
        self.servers.clear()
        if self.signaling:
            await self.signaling.close()
