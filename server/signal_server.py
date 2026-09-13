"""Minimal WebSocket signaling server for pfs.

Rooms are created by publishers and joined by receivers using the room id +
token embedded in the invite code.  The server only relays SDP/ICE envelopes
between peers; file bytes never pass through it.

Run::

    uvicorn server.signal_server:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

log = logging.getLogger("pfs.signal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="pfs signaling")


class Room:
    def __init__(self) -> None:
        self.sid = uuid.uuid4().hex[:12]
        self.token = secrets.token_urlsafe(12)
        self.publisher: str | None = None
        self.receivers: set[str] = set()


class Hub:
    def __init__(self) -> None:
        self.connections: dict[str, WebSocket] = {}
        self.rooms: dict[str, Room] = {}
        self.peer_room: dict[str, str] = {}

    async def send(self, peer_id: str, obj: dict) -> None:
        ws = self.connections.get(peer_id)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(obj))
        except Exception:  # noqa: BLE001 - peer vanished
            log.debug("failed to send to %s", peer_id)


hub = Hub()


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "rooms": len(hub.rooms), "peers": len(hub.connections)}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    peer_id = uuid.uuid4().hex
    hub.connections[peer_id] = ws
    await ws.send_text(json.dumps({"t": "welcome", "peer_id": peer_id}))
    log.info("peer connected: %s", peer_id)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            await _handle(peer_id, msg)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("websocket error for %s", peer_id)
    finally:
        await _cleanup(peer_id)


async def _handle(peer_id: str, msg: dict) -> None:
    kind = msg.get("t")
    if kind == "create":
        room = Room()
        room.publisher = peer_id
        hub.rooms[room.sid] = room
        hub.peer_room[peer_id] = room.sid
        await hub.send(peer_id, {"t": "created", "sid": room.sid, "token": room.token})
        log.info("room created %s by %s", room.sid, peer_id)

    elif kind == "join":
        room = hub.rooms.get(msg.get("sid"))
        if room is None or room.token != msg.get("token"):
            await hub.send(peer_id, {"t": "error", "msg": "invalid room or token"})
            return
        room.receivers.add(peer_id)
        hub.peer_room[peer_id] = room.sid
        await hub.send(peer_id, {"t": "joined", "sid": room.sid, "publisher": room.publisher})
        await hub.send(room.publisher, {"t": "peer_joined", "peer_id": peer_id})
        log.info("peer %s joined room %s", peer_id, room.sid)

    elif kind == "signal":
        target = msg.get("to")
        if target:
            await hub.send(target, {"t": "signal", "from": peer_id, "payload": msg.get("payload")})


async def _cleanup(peer_id: str) -> None:
    hub.connections.pop(peer_id, None)
    sid = hub.peer_room.pop(peer_id, None)
    log.info("peer disconnected: %s", peer_id)
    if sid is None:
        return
    room = hub.rooms.get(sid)
    if room is None:
        return
    if room.publisher == peer_id:
        for receiver in list(room.receivers):
            await hub.send(receiver, {"t": "peer_left", "peer_id": peer_id})
        hub.rooms.pop(sid, None)
        log.info("room closed %s", sid)
    else:
        room.receivers.discard(peer_id)
        await hub.send(room.publisher, {"t": "peer_left", "peer_id": peer_id})
