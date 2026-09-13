"""Runtime configuration and ICE server assembly."""

from __future__ import annotations

import os

DEFAULT_SIGNAL_HOST = os.environ.get("PFS_SIGNAL_HOST", "127.0.0.1")
DEFAULT_SIGNAL_PORT = int(os.environ.get("PFS_SIGNAL_PORT", "8765"))
DEFAULT_STUN = os.environ.get("PFS_STUN", "stun:stun.l.google.com:19302")


def build_ice_servers(
    stun: str | None = DEFAULT_STUN,
    turn_url: str | None = None,
    turn_user: str | None = None,
    turn_pass: str | None = None,
) -> list:
    """Return ``RTCIceServer`` objects for aiortc.

    Imports aiortc lazily so the pure-python helpers stay importable without it.
    """
    from aiortc import RTCIceServer

    servers = []
    if stun:
        servers.append(RTCIceServer(urls=stun))
    if turn_url:
        servers.append(RTCIceServer(urls=turn_url, username=turn_user, credential=turn_pass))
    return servers
