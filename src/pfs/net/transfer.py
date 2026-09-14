"""File transfer over the ``ctrl``/``data`` data channels.

``FileServer`` runs on the publisher and answers manifest/chunk/verify
requests.  ``FileClient`` runs on the receiver and drives resumable,
per-chunk-verified downloads with a bounded request window.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Callable

from ..common import protocol as P
from ..common.chunker import CHUNK_SIZE, PartialFile, chunk_length, file_sha256
from ..common.manifest import Entry, scan_folder

log = logging.getLogger(__name__)

# progress(done_bytes, total_bytes)
ProgressFn = Callable[[int, int], None]
_BACKPRESSURE = 1 << 21  # pause when >2 MiB queued on the data channel


async def _drain(channel) -> None:
    while channel.bufferedAmount > _BACKPRESSURE:
        await asyncio.sleep(0.005)


class FileServer:
    """Serves a folder to one connected receiver."""

    def __init__(self, peer, root: str, on_sent: Callable[[int], None] | None = None):
        self.peer = peer
        self.root = os.path.abspath(root)
        self.on_sent = on_sent
        self.bytes_sent = 0
        self._entries: list[Entry] | None = None
        self._hash_cache: dict[str, str] = {}
        self._send_lock = asyncio.Lock()

    def entries(self) -> list[Entry]:
        if self._entries is None:
            self._entries = scan_folder(self.root)
        return self._entries

    async def on_ctrl(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == P.MSG_MANIFEST_REQ:
            payload = {"t": P.MSG_MANIFEST, "entries": [e.to_dict() for e in self.entries()]}
            self.peer.ctrl.send(P.dumps(payload))
        elif kind == P.MSG_REQUEST:
            asyncio.create_task(self._serve_chunk(msg))
        elif kind == P.MSG_VERIFY:
            asyncio.create_task(self._serve_verify(msg["path"]))

    async def _serve_chunk(self, msg: dict) -> None:
        rid = int(msg["id"])
        rel = str(msg["path"])
        offset = int(msg["offset"])
        length = int(msg["length"])
        full = self._resolve(rel)
        if full is None:
            await self._error(rid, "file not found or outside share root")
            return
        try:
            data = await asyncio.to_thread(_read_at, full, offset, length)
        except OSError as exc:
            await self._error(rid, str(exc))
            return
        frame = P.encode_chunk(rid, offset, hashlib.sha256(data).digest(), data)
        async with self._send_lock:
            await _drain(self.peer.data)
            self.peer.data.send(frame)
        self.bytes_sent += len(frame)
        if self.on_sent is not None:
            self.on_sent(len(frame))

    async def _serve_verify(self, rel: str) -> None:
        full = self._resolve(rel)
        if full is None:
            await self._error(None, "file not found or outside share root")
            return
        digest = self._hash_cache.get(rel)
        if digest is None:
            digest = await asyncio.to_thread(file_sha256, full)
            self._hash_cache[rel] = digest
        payload = {"t": P.MSG_DONE, "path": rel, "sha256": digest, "size": os.path.getsize(full)}
        self.peer.ctrl.send(P.dumps(payload))

    async def _error(self, rid, message: str) -> None:
        self.peer.ctrl.send(P.dumps({"t": P.MSG_ERROR, "id": rid, "msg": message}))

    def _resolve(self, rel: str) -> str | None:
        full = os.path.normpath(os.path.join(self.root, rel.replace("/", os.sep)))
        if full != self.root and not full.startswith(self.root + os.sep):
            return None
        if not os.path.isfile(full):
            return None
        return full


def _read_at(path: str, offset: int, length: int) -> bytes:
    with open(path, "rb") as fh:
        fh.seek(offset)
        return fh.read(length)


class FileClient:
    """Downloads files from a connected publisher.

    Chunk requests are pipelined up to ``concurrency`` in flight and retried
    with exponential backoff, so a dropped packet or a slow relay does not
    abort the whole file.
    """

    def __init__(
        self,
        peer,
        dest: str,
        concurrency: int = 4,
        max_retries: int = 3,
        on_recv: Callable[[int], None] | None = None,
    ):
        self.peer = peer
        self.dest = os.path.abspath(dest)
        self.entries: list[Entry] | None = None
        self.concurrency = max(1, concurrency)
        self.max_retries = max(0, max_retries)
        self.on_recv = on_recv
        self.bytes_received = 0
        self._rid = 0
        self._chunk_waiters: dict[int, asyncio.Future] = {}
        self._manifest_waiter: asyncio.Future | None = None
        self._verify_waiters: dict[str, asyncio.Future] = {}

    # -- inbound ------------------------------------------------------------
    async def on_ctrl(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == P.MSG_MANIFEST:
            if self._manifest_waiter and not self._manifest_waiter.done():
                self._manifest_waiter.set_result(msg["entries"])
        elif kind == P.MSG_DONE:
            fut = self._verify_waiters.get(msg.get("path"))
            if fut and not fut.done():
                fut.set_result(msg)
        elif kind == P.MSG_ERROR:
            self._fail(msg.get("id"), RuntimeError(msg.get("msg", "publisher error")))

    def on_data(self, buf: bytes) -> None:
        try:
            rid, _offset, digest, payload = P.decode_chunk(buf)
        except ValueError:
            log.warning("dropping malformed data frame")
            return
        self.bytes_received += len(buf)
        if self.on_recv is not None:
            self.on_recv(len(buf))
        fut = self._chunk_waiters.get(rid)
        if fut is None or fut.done():
            return
        if hashlib.sha256(payload).digest() != digest:
            fut.set_exception(RuntimeError("chunk checksum mismatch"))
        else:
            fut.set_result(payload)

    def _fail(self, rid, exc: Exception) -> None:
        if rid is None:
            return
        fut = self._chunk_waiters.get(int(rid))
        if fut and not fut.done():
            fut.set_exception(exc)

    # -- outbound -----------------------------------------------------------
    async def request_manifest(self, timeout: float = 30.0) -> list[Entry]:
        self._manifest_waiter = asyncio.get_event_loop().create_future()
        self.peer.ctrl.send(P.dumps({"t": P.MSG_MANIFEST_REQ}))
        raw = await asyncio.wait_for(self._manifest_waiter, timeout)
        self.entries = [Entry.from_dict(d) for d in raw]
        return self.entries

    async def download_file(
        self,
        rel: str,
        size: int,
        progress: ProgressFn | None = None,
        chunk_timeout: float = 120.0,
    ) -> str:
        target = os.path.join(self.dest, rel.replace("/", os.sep))
        partial = PartialFile(target, size)
        total_bytes = size
        done_bytes = sum(chunk_length(size, i) for i in partial.received if i < partial.total_chunks)
        if progress:
            progress(done_bytes, total_bytes)

        missing = partial.missing()
        queue: asyncio.Queue[int] = asyncio.Queue()
        for index in missing:
            queue.put_nowait(index)

        lock = asyncio.Lock()
        state = {"done": done_bytes}

        async def worker() -> None:
            while True:
                try:
                    index = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                offset = index * CHUNK_SIZE
                length = chunk_length(size, index)
                payload = await self._request_chunk_retry(rel, offset, length, chunk_timeout)
                async with lock:
                    await asyncio.to_thread(partial.write_chunk, index, payload)
                    await asyncio.to_thread(partial.save_state)
                    state["done"] += length
                    if progress:
                        progress(state["done"], total_bytes)

        workers = [asyncio.create_task(worker()) for _ in range(min(self.concurrency, len(missing)))]
        if workers:
            await asyncio.gather(*workers)

        expected = await self._request_verify_retry(rel)
        actual = await asyncio.to_thread(partial.compute_sha256)
        if expected.get("sha256") and expected["sha256"] != actual:
            raise RuntimeError(f"file checksum mismatch for {rel}")
        return await asyncio.to_thread(partial.finish)

    async def _request_chunk_retry(self, rel: str, offset: int, length: int, timeout: float) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._request_chunk(rel, offset, length, timeout)
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, RuntimeError, OSError) as exc:
                last_exc = exc
                log.warning(
                    "chunk %s@%d failed (attempt %d/%d): %s",
                    rel, offset, attempt + 1, self.max_retries + 1, exc,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(min(0.5 * (2 ** attempt), 5.0))
        assert last_exc is not None
        raise last_exc

    async def _request_chunk(self, rel: str, offset: int, length: int, timeout: float) -> bytes:
        rid = self._rid
        self._rid += 1
        fut = asyncio.get_event_loop().create_future()
        self._chunk_waiters[rid] = fut
        try:
            self.peer.ctrl.send(
                P.dumps({"t": P.MSG_REQUEST, "id": rid, "path": rel, "offset": offset, "length": length})
            )
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._chunk_waiters.pop(rid, None)

    async def _request_verify_retry(self, rel: str, timeout: float = 60.0) -> dict:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._request_verify(rel, timeout)
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, RuntimeError) as exc:
                last_exc = exc
                log.warning("verify %s failed (attempt %d/%d): %s", rel, attempt + 1, self.max_retries + 1, exc)
                if attempt < self.max_retries:
                    await asyncio.sleep(min(0.5 * (2 ** attempt), 5.0))
        assert last_exc is not None
        raise last_exc

    async def _request_verify(self, rel: str, timeout: float) -> dict:
        fut = asyncio.get_event_loop().create_future()
        self._verify_waiters[rel] = fut
        try:
            self.peer.ctrl.send(P.dumps({"t": P.MSG_VERIFY, "path": rel}))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._verify_waiters.pop(rel, None)
