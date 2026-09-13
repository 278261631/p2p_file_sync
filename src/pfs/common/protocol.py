"""Wire protocol shared by publisher and receiver.

Control channel (``ctrl``) carries JSON text messages.  The data channel
(``data``) carries a fixed binary frame::

    +--------+--------+----------+-----------------+
    | rid:4  | off:8  | sha256:32| payload ...     |
    +--------+--------+----------+-----------------+

All integers are big-endian (network order).
"""

from __future__ import annotations

import json
import struct
from typing import Any

PROTOCOL_VERSION = 1

# --- control message types -------------------------------------------------
MSG_HELLO = "hello"
MSG_MANIFEST_REQ = "manifest_req"
MSG_MANIFEST = "manifest"
MSG_REQUEST = "request"
MSG_VERIFY = "verify"
MSG_DONE = "done"
MSG_ERROR = "error"

# --- binary data frame -----------------------------------------------------
CHUNK_HEADER = struct.Struct("!IQ32s")
HEADER_SIZE = CHUNK_HEADER.size  # 44 bytes


def dumps(obj: Any) -> str:
    """Compact JSON for control messages."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def loads(raw: str | bytes) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def encode_chunk(request_id: int, offset: int, digest: bytes, payload: bytes) -> bytes:
    if len(digest) != 32:
        raise ValueError("digest must be 32 bytes (sha256)")
    return CHUNK_HEADER.pack(request_id, offset, digest) + payload


def decode_chunk(buf: bytes) -> tuple[int, int, bytes, bytes]:
    """Return ``(request_id, offset, digest, payload)``."""
    if len(buf) < HEADER_SIZE:
        raise ValueError("chunk frame too short")
    request_id, offset, digest = CHUNK_HEADER.unpack_from(buf, 0)
    return request_id, offset, digest, buf[HEADER_SIZE:]
