"""Chunk sizing, hashing and resumable partial-file bookkeeping."""

from __future__ import annotations

import hashlib
import json
import os

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB
_HASH_BUF = 1 << 20


def chunk_count(size: int) -> int:
    if size <= 0:
        return 0
    return (size + CHUNK_SIZE - 1) // CHUNK_SIZE


def chunk_length(size: int, index: int) -> int:
    offset = index * CHUNK_SIZE
    return min(CHUNK_SIZE, size - offset)


def chunk_ranges(size: int):
    for index in range(chunk_count(size)):
        yield index, index * CHUNK_SIZE, chunk_length(size, index)


def file_sha256(path: str, bufsize: int = _HASH_BUF) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(bufsize), b""):
            h.update(block)
    return h.hexdigest()


class PartialFile:
    """A resumable download target backed by ``<target>.pfs-part`` + ``.pfs-state``."""

    def __init__(self, target_path: str, size: int):
        self.target = target_path
        self.part = target_path + ".pfs-part"
        self.state_path = target_path + ".pfs-state"
        self.size = size
        self.total_chunks = chunk_count(size)
        self.received: set[int] = set()
        parent = os.path.dirname(os.path.abspath(target_path))
        os.makedirs(parent, exist_ok=True)
        self._load_state()

    def _load_state(self) -> None:
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
            if int(state.get("size", -1)) == self.size:
                self.received = {int(i) for i in state.get("received", [])}
        except (OSError, ValueError, TypeError):
            self.received = set()

    def save_state(self) -> None:
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"size": self.size, "received": sorted(self.received)}, fh)
        os.replace(tmp, self.state_path)

    def missing(self) -> list[int]:
        return [i for i in range(self.total_chunks) if i not in self.received]

    def write_chunk(self, index: int, data: bytes) -> None:
        offset = index * CHUNK_SIZE
        mode = "r+b" if os.path.exists(self.part) else "w+b"
        with open(self.part, mode) as fh:
            fh.seek(offset)
            fh.write(data)
        self.received.add(index)

    def compute_sha256(self) -> str:
        if not os.path.exists(self.part):
            return hashlib.sha256(b"").hexdigest()
        return file_sha256(self.part)

    def finish(self) -> str:
        """Promote the partial file to its final name and clean up state."""
        if self.size == 0 and not os.path.exists(self.part):
            with open(self.part, "wb"):
                pass
        actual = os.path.getsize(self.part)
        if actual != self.size:
            with open(self.part, "r+b") as fh:
                fh.truncate(self.size)
        os.replace(self.part, self.target)
        if os.path.exists(self.state_path):
            os.remove(self.state_path)
        return self.target
