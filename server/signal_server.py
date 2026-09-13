"""Signaling + directory server for pfs.

Replaces the old invite-code room model with account/password login, a share
registry, and presence.  Clients authenticate over the WebSocket, publish a
folder listing, and get brokered to each other for WebRTC data transfer.  File
bytes never pass through this server.

Run::

    uvicorn server.signal_server:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .accounts import AccountStore
from .registry import Registry

log = logging.getLogger("pfs.signal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="pfs signaling")


class Client:
    def __init__(self, peer_id: str, ws: WebSocket):
        self.peer_id = peer_id
        self.ws = ws
        self.account: str | None = None

    @property
    def logged_in(self) -> bool:
        return self.account is not None


class Hub:
    def __init__(self) -> None:
        self.clients: dict[str, Client] = {}
        self.accounts: dict[str, set[str]] = {}
        self.registry = Registry()
        self.store = AccountStore()

    def online_accounts(self) -> list[str]:
        return sorted(self.accounts)

    async def send(self, peer_id: str, obj: dict) -> None:
        client = self.clients.get(peer_id)
        if client is None:
            return
        try:
            await client.ws.send_text(json.dumps(obj))
        except Exception:  # noqa: BLE001 - peer vanished
            log.debug("failed to send to %s", peer_id)

    async def broadcast(self, obj: dict) -> None:
        for client in list(self.clients.values()):
            if client.logged_in:
                await self.send(client.peer_id, obj)

    async def broadcast_presence(self) -> None:
        await self.broadcast({"t": "presence", "accounts": self.online_accounts()})


hub = Hub()


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "clients": len(hub.clients),
        "online_accounts": hub.online_accounts(),
        "shares": len(hub.registry.list()),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    peer_id = uuid.uuid4().hex
    client = Client(peer_id, ws)
    hub.clients[peer_id] = client
    await hub.send(peer_id, {"t": "welcome", "peer_id": peer_id})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            await _handle(client, msg)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("websocket error for %s", peer_id)
    finally:
        await _cleanup(client)


async def _handle(client: Client, msg: dict) -> None:
    kind = msg.get("t")

    if kind == "login":
        if not hub.store.verify(str(msg.get("name", "")), str(msg.get("password", ""))):
            await hub.send(client.peer_id, {"t": "error", "msg": "账号或密码错误"})
            return
        account = str(msg["name"])
        if client.logged_in:
            hub.accounts.get(client.account, set()).discard(client.peer_id)
        client.account = account
        hub.accounts.setdefault(account, set()).add(client.peer_id)
        await hub.send(client.peer_id, {"t": "login_ok", "account": account})
        log.info("login: %s (%s)", account, client.peer_id)
        await hub.broadcast_presence()
        return

    if not client.logged_in:
        await hub.send(client.peer_id, {"t": "error", "msg": "未登录"})
        return

    if kind == "publish":
        share = msg.get("share") or {}
        name = str(share.get("name") or "share")
        entries = list(share.get("entries") or [])
        record = hub.registry.publish(client.account, client.peer_id, name, entries)
        await hub.send(client.peer_id, {"t": "published", "share_id": record.id})
        log.info("share published: %s by %s (%d entries)", name, client.account, len(entries))
        await hub.broadcast({"t": "shares_changed"})

    elif kind == "unpublish":
        hub.registry.remove_peer(client.peer_id)
        await hub.send(client.peer_id, {"t": "unpublished"})
        await hub.broadcast({"t": "shares_changed"})

    elif kind == "list_shares":
        await hub.send(client.peer_id, {"t": "shares", "items": [s.summary() for s in hub.registry.list()]})

    elif kind == "get_manifest":
        share = hub.registry.get(msg.get("share_id"))
        if share is None:
            await hub.send(client.peer_id, {"t": "error", "msg": "共享不存在或已离线"})
            return
        await hub.send(
            client.peer_id,
            {"t": "manifest", "share_id": share.id, "name": share.name, "entries": share.entries},
        )

    elif kind == "connect":
        share = hub.registry.get(msg.get("share_id"))
        if share is None:
            await hub.send(client.peer_id, {"t": "error", "msg": "共享不存在或已离线"})
            return
        owner = hub.clients.get(share.peer_id)
        if owner is None or not owner.logged_in:
            await hub.send(client.peer_id, {"t": "error", "msg": "发布方已离线"})
            return
        await hub.send(
            owner.peer_id,
            {"t": "peer_request", "peer_id": client.peer_id, "share_id": share.id, "account": client.account},
        )
        await hub.send(client.peer_id, {"t": "peer_ready", "owner": owner.peer_id, "share_id": share.id})

    elif kind == "signal":
        target = msg.get("to")
        if target:
            await hub.send(target, {"t": "signal", "from": client.peer_id, "payload": msg.get("payload")})

    elif kind == "ping":
        await hub.send(client.peer_id, {"t": "pong"})


async def _cleanup(client: Client) -> None:
    hub.clients.pop(client.peer_id, None)
    hub.registry.remove_peer(client.peer_id)
    if client.account:
        peers = hub.accounts.get(client.account)
        if peers:
            peers.discard(client.peer_id)
            if not peers:
                hub.accounts.pop(client.account, None)
    log.info("disconnected: %s", client.peer_id)
    await hub.broadcast_presence()
    await hub.broadcast({"t": "shares_changed"})
