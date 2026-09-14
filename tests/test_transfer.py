import asyncio
import hashlib
import json
import os

import pytest

import pfs.net.transfer as transfer
from pfs.common import protocol as P
from pfs.net.transfer import FileClient, FileServer


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list = []
        self.bufferedAmount = 0

    def send(self, data) -> None:
        self.sent.append(data)


class FakePeer:
    def __init__(self) -> None:
        self.ctrl = FakeChannel()
        self.data = FakeChannel()


def test_file_server_manifest_and_chunk(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello")

    peer = FakePeer()
    server = FileServer(peer, str(root))

    asyncio.run(server.on_ctrl({"t": P.MSG_MANIFEST_REQ}))
    manifest = json.loads(peer.ctrl.sent[-1])
    assert manifest["t"] == P.MSG_MANIFEST
    assert any(entry["path"] == "a.txt" for entry in manifest["entries"])

    asyncio.run(server._serve_chunk({"id": 5, "path": "a.txt", "offset": 0, "length": 5}))
    rid, offset, digest, payload = P.decode_chunk(peer.data.sent[-1])
    assert (rid, offset, payload) == (5, 0, b"hello")
    assert digest == hashlib.sha256(b"hello").digest()


def test_file_server_counts_sent_bytes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.bin").write_bytes(b"x" * 1000)

    peer = FakePeer()
    counts: list[int] = []
    server = FileServer(peer, str(root), on_sent=counts.append)

    asyncio.run(server._serve_chunk({"id": 0, "path": "a.bin", "offset": 0, "length": 1000}))
    frame_len = len(peer.data.sent[-1])
    assert server.bytes_sent == frame_len
    assert counts == [frame_len]

    asyncio.run(server._serve_chunk({"id": 1, "path": "a.bin", "offset": 0, "length": 500}))
    assert server.bytes_sent == frame_len + len(peer.data.sent[-1])
    assert counts[-1] == len(peer.data.sent[-1])


def test_file_server_rejects_path_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    server = FileServer(FakePeer(), str(root))
    assert server._resolve("../secret") is None
    assert server._resolve("a/../../secret") is None


def test_file_client_counts_received_bytes():
    counts: list[int] = []
    client = FileClient(FakePeer(), ".", on_recv=counts.append)

    frame = P.encode_chunk(0, 0, hashlib.sha256(b"hi").digest(), b"hi")
    client.on_data(frame)
    assert client.bytes_received == len(frame)
    assert counts == [len(frame)]

    client.on_data(b"short")  # malformed: not counted
    assert client.bytes_received == len(frame)
    assert counts == [len(frame)]


def test_chunk_retry_succeeds_after_failures(monkeypatch, tmp_path):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(transfer.asyncio, "sleep", no_sleep)
    client = FileClient(FakePeer(), str(tmp_path), max_retries=3)
    calls = {"n": 0}

    async def flaky(rel, offset, length, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return b"ok"

    client._request_chunk = flaky
    assert asyncio.run(client._request_chunk_retry("f", 0, 2, 1.0)) == b"ok"
    assert calls["n"] == 3


def test_chunk_retry_raises_after_exhaustion(monkeypatch, tmp_path):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(transfer.asyncio, "sleep", no_sleep)
    client = FileClient(FakePeer(), str(tmp_path), max_retries=2)
    calls = {"n": 0}

    async def always_fail(rel, offset, length, timeout):
        calls["n"] += 1
        raise RuntimeError("nope")

    client._request_chunk = always_fail
    with pytest.raises(RuntimeError):
        asyncio.run(client._request_chunk_retry("f", 0, 2, 1.0))
    assert calls["n"] == 3


def test_download_pipelines_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr("pfs.common.chunker.CHUNK_SIZE", 1000)
    monkeypatch.setattr("pfs.net.transfer.CHUNK_SIZE", 1000)
    client = FileClient(FakePeer(), str(tmp_path), concurrency=4, max_retries=0)
    size = 1000 * 3 + 10
    active = {"cur": 0, "max": 0}

    async def fake_request(rel, offset, length, timeout):
        active["cur"] += 1
        active["max"] = max(active["max"], active["cur"])
        await asyncio.sleep(0.02)
        active["cur"] -= 1
        return b"\x00" * length

    async def fake_verify(rel, timeout=60.0):
        return {}

    client._request_chunk = fake_request
    client._request_verify_retry = fake_verify

    target = asyncio.run(client.download_file("big.bin", size))
    assert os.path.getsize(target) == size
    assert active["max"] >= 2


def test_download_resumes_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr("pfs.common.chunker.CHUNK_SIZE", 1000)
    monkeypatch.setattr("pfs.net.transfer.CHUNK_SIZE", 1000)
    payload = bytes(range(256)) * 10
    size = len(payload)
    target = tmp_path / "data.bin"

    from pfs.common.chunker import PartialFile

    partial = PartialFile(str(target), size)
    partial.write_chunk(0, payload[:1000])
    partial.save_state()

    client = FileClient(FakePeer(), str(tmp_path), concurrency=2, max_retries=0)
    requested: list[int] = []

    async def fake_request(rel, offset, length, timeout):
        requested.append(offset)
        return payload[offset:offset + length]

    async def fake_verify(rel, timeout=60.0):
        return {"sha256": hashlib.sha256(payload).hexdigest()}

    client._request_chunk = fake_request
    client._request_verify_retry = fake_verify

    out = asyncio.run(client.download_file("data.bin", size))
    assert open(out, "rb").read() == payload
    assert sorted(requested) == [1000, 2000]

