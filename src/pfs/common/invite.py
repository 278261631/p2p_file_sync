"""Compact, copy-pasteable invite codes.

An invite bundles everything a receiver needs to reach a publisher: the
signaling endpoint plus a one-time room id/token.
"""

from __future__ import annotations

import base64
import json
import zlib
from dataclasses import dataclass

PREFIX = "PFS1."


@dataclass
class Invite:
    host: str
    port: int
    sid: str
    token: str
    tls: bool = False

    def to_code(self) -> str:
        payload = {
            "h": self.host,
            "p": self.port,
            "s": self.sid,
            "t": self.token,
            "x": 1 if self.tls else 0,
        }
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        blob = zlib.compress(raw, 9)
        return PREFIX + base64.b32encode(blob).decode("ascii").rstrip("=")

    @staticmethod
    def from_code(code: str) -> "Invite":
        code = (code or "").strip()
        if not code.startswith(PREFIX):
            raise ValueError("invalid invite code prefix")
        body = code[len(PREFIX):]
        pad = "=" * ((8 - len(body) % 8) % 8)
        try:
            raw = zlib.decompress(base64.b32decode(body + pad))
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - normalize any decode error
            raise ValueError("corrupt invite code") from exc
        return Invite(
            host=str(data["h"]),
            port=int(data["p"]),
            sid=str(data["s"]),
            token=str(data["t"]),
            tls=bool(data.get("x", 0)),
        )

    @property
    def ws_url(self) -> str:
        scheme = "wss" if self.tls else "ws"
        return f"{scheme}://{self.host}:{self.port}/ws"
