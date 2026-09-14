"""Signaling + directory server for pfs.

Replaces the old invite-code room model with account/password login, a share
registry, and presence.  Clients authenticate over the WebSocket, publish a
folder listing, and get brokered to each other for WebRTC data transfer.  File
bytes never pass through this server.

Run::

    uvicorn server.signal_server:app --host 0.0.0.0 --port 18765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .accounts import AccountStore
from .registry import Registry

log = logging.getLogger("pfs.signal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="pfs signaling")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class LoginThrottle:
    """Sliding-window failed-login limiter keyed by client address.

    After ``max_attempts`` failures inside ``window`` seconds the key is locked
    for ``lockout`` seconds.  A successful login clears the key.  State is
    in-memory (per worker process).
    """

    def __init__(
        self,
        max_attempts: int | None = None,
        window: float | None = None,
        lockout: float | None = None,
    ):
        self.max_attempts = max_attempts if max_attempts is not None else _env_int("PFS_LOGIN_MAX_ATTEMPTS", 5)
        self.window = window if window is not None else _env_float("PFS_LOGIN_WINDOW", 60.0)
        self.lockout = lockout if lockout is not None else _env_float("PFS_LOGIN_LOCKOUT", 300.0)
        self._failures: dict[str, deque[float]] = {}
        self._locked: dict[str, float] = {}

    def _prune(self, now: float) -> None:
        for key, until in list(self._locked.items()):
            if until <= now:
                self._locked.pop(key, None)
        for key, stamps in list(self._failures.items()):
            while stamps and now - stamps[0] > self.window:
                stamps.popleft()
            if not stamps:
                self._failures.pop(key, None)

    def retry_after(self, key: str) -> float:
        """Seconds the caller must wait before another attempt (0 if allowed)."""
        now = time.monotonic()
        self._prune(now)
        until = self._locked.get(key)
        if until is not None and until > now:
            return until - now
        return 0.0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._prune(now)
        stamps = self._failures.setdefault(key, deque())
        stamps.append(now)
        if len(stamps) >= self.max_attempts:
            self._locked[key] = now + self.lockout
            self._failures.pop(key, None)
            log.warning("login locked for %s after %d failures (%.0fs)", key, len(stamps), self.lockout)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked.pop(key, None)


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
        self.throttle = LoginThrottle()

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

_TRUTHY = ("1", "true", "yes", "on")


def _allow_insecure() -> bool:
    """Dev escape hatch: ``PFS_ALLOW_INSECURE=1`` accepts plaintext ``ws://``."""
    return os.environ.get("PFS_ALLOW_INSECURE", "").strip().lower() in _TRUTHY


def _trusted_proxies() -> set[str]:
    raw = (
        os.environ.get("PFS_TRUSTED_PROXIES")
        or os.environ.get("FORWARDED_ALLOW_IPS")
        or "127.0.0.1,::1"
    )
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_secure_request(ws: WebSocket) -> bool:
    """True when the client reached us over TLS (``wss://``).

    Plaintext is rejected unless ``PFS_ALLOW_INSECURE`` is set.  When a trusted
    reverse proxy terminates TLS, the original scheme is read from
    ``X-Forwarded-Proto`` (run uvicorn with ``--proxy-headers``).
    """
    if _allow_insecure():
        return True
    if ws.url.scheme in ("wss", "https"):
        return True
    client = ws.client
    if client and client.host in _trusted_proxies():
        proto = ws.headers.get("x-forwarded-proto", "")
        if proto:
            return proto.split(",")[0].strip().lower() in ("https", "wss")
    return False


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
    if not is_secure_request(ws):
        peer = ws.client.host if ws.client else "unknown"
        log.warning("rejected insecure signaling connection from %s (wss:// required)", peer)
        await ws.close(code=1008)  # policy violation
        return
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
        key = client.ws.client.host if client.ws.client else "unknown"
        retry_after = hub.throttle.retry_after(key)
        if retry_after > 0:
            await hub.send(
                client.peer_id,
                {"t": "error", "msg": f"登录尝试过多，请 {int(retry_after) + 1} 秒后再试"},
            )
            log.warning("login throttled for %s (%.0fs left)", key, retry_after)
            return
        if not hub.store.verify(str(msg.get("name", "")), str(msg.get("password", ""))):
            hub.throttle.record_failure(key)
            await asyncio.sleep(0.25)
            await hub.send(client.peer_id, {"t": "error", "msg": "账号或密码错误"})
            return
        hub.throttle.reset(key)
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
