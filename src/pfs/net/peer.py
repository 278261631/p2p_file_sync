"""aiortc peer-connection wrapper with ctrl/data channels."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiortc import (
    RTCConfiguration,
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)

from .ice import classify_path

log = logging.getLogger(__name__)

CTRL_LABEL = "ctrl"
DATA_LABEL = "data"


class Peer:
    """One WebRTC connection to a remote peer.

    The *offerer* (receiver) creates the ``ctrl``/``data`` channels; the
    *answerer* (publisher) picks them up from the ``datachannel`` event.
    """

    def __init__(
        self,
        signaling,
        remote_id: str,
        ice_servers: list,
        on_ctrl: Callable[[dict], None],
        on_data: Callable[[bytes], None],
        on_open: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ):
        self.signaling = signaling
        self.remote_id = remote_id
        self.on_ctrl = on_ctrl
        self.on_data = on_data
        self.on_open = on_open
        self.on_close = on_close

        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))
        self.ctrl = None
        self.data = None
        self._ready = False

        self.pc.on("icecandidate", self._on_ice)
        self.pc.on("connectionstatechange", self._on_state)
        self.pc.on("datachannel", self._on_datachannel)

    # -- events -------------------------------------------------------------
    def _on_ice(self, candidate) -> None:
        if candidate is None:
            return
        payload = {
            "type": "candidate",
            "candidate": {
                "candidate": candidate.candidate,
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
            },
        }
        asyncio.ensure_future(self.signaling.send({"t": "signal", "to": self.remote_id, "payload": payload}))

    def _on_state(self) -> None:
        state = self.pc.connectionState
        log.debug("peer %s state=%s", self.remote_id, state)
        if state in ("failed", "closed") and self.on_close:
            self.on_close()

    def _on_datachannel(self, channel) -> None:
        if channel.label == CTRL_LABEL:
            self.ctrl = channel
        elif channel.label == DATA_LABEL:
            self.data = channel
        self._bind(channel)

    def _bind(self, channel) -> None:
        @channel.on("message")
        def _on_message(message):
            try:
                if channel.label == CTRL_LABEL:
                    import json

                    result = self.on_ctrl(json.loads(message))
                    if asyncio.iscoroutine(result):
                        asyncio.ensure_future(result)
                else:
                    self.on_data(message)
            except Exception:  # noqa: BLE001
                log.exception("error handling channel message")

        @channel.on("open")
        def _on_open():
            log.debug("channel %s open", channel.label)
            self._maybe_ready()

        @channel.on("close")
        def _on_close():
            if self.on_close:
                self.on_close()

    def _maybe_ready(self) -> None:
        if self._ready:
            return
        if self.ctrl and self.data and self.ctrl.readyState == "open" and self.data.readyState == "open":
            self._ready = True
            if self.on_open:
                self.on_open()

    # -- negotiation --------------------------------------------------------
    def create_channels(self) -> None:
        """Offerer side: create the ctrl/data channels before the offer."""
        self.ctrl = self.pc.createDataChannel(CTRL_LABEL)
        self.data = self.pc.createDataChannel(DATA_LABEL)
        self._bind(self.ctrl)
        self._bind(self.data)

    async def offer(self) -> None:
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        local = self.pc.localDescription
        await self.signaling.send(
            {"t": "signal", "to": self.remote_id, "payload": {"type": "sdp", "sdp": local.sdp, "sdpType": local.type}}
        )

    async def handle_signal(self, payload: dict) -> None:
        kind = payload.get("type")
        if kind == "sdp":
            desc = RTCSessionDescription(sdp=payload["sdp"], type=payload["sdpType"])
            await self.pc.setRemoteDescription(desc)
            if desc.type == "offer":
                answer = await self.pc.createAnswer()
                await self.pc.setLocalDescription(answer)
                local = self.pc.localDescription
                await self.signaling.send(
                    {
                        "t": "signal",
                        "to": self.remote_id,
                        "payload": {"type": "sdp", "sdp": local.sdp, "sdpType": local.type},
                    }
                )
        elif kind == "candidate":
            cand = payload["candidate"]
            await self.pc.addIceCandidate(
                RTCIceCandidate(
                    sdpMid=cand.get("sdpMid"),
                    sdpMLineIndex=cand.get("sdpMLineIndex"),
                    candidate=cand["candidate"],
                )
            )

    async def ice_path(self) -> str | None:
        """Classify the active ICE path: ``"relay"``, ``"direct"`` or ``None``.

        ``"relay"`` means at least one side of the selected candidate pair is a
        TURN-relayed address, so this connection's bytes are relayed.
        """
        try:
            report = await self.pc.getStats()
        except Exception:  # noqa: BLE001 - stats are best-effort
            return None
        return classify_path(report)

    async def close(self) -> None:
        try:
            await self.pc.close()
        except Exception:  # noqa: BLE001
            pass
