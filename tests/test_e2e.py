"""End-to-end smoke test: signaling server + publisher + receiver in one loop."""

import asyncio
import hashlib
import os

import pytest
import uvicorn

from pfs.common.manifest import TYPE_FILE
from pfs.publisher.service import PublisherService
from pfs.receiver.service import ReceiverService
from server.signal_server import app


async def _start_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


async def _run(root, dest):
    server, task, port = await _start_server()
    publisher = None
    receiver = None
    try:
        publisher = PublisherService(str(root), "127.0.0.1", port, ice_servers=[])
        invite = await publisher.start()

        receiver = ReceiverService(invite, str(dest), ice_servers=[])
        await receiver.start()

        entries = await receiver.get_manifest()
        files = [e for e in entries if e.type == TYPE_FILE]
        assert {f.path for f in files} == {"alpha.txt", "sub/beta.bin"}

        for entry in files:
            await receiver.download_file(entry.path, entry.size)

        assert (dest / "alpha.txt").read_bytes() == b"hello pfs\n"
        expected = (root / "sub" / "beta.bin").read_bytes()
        got = (dest / "sub" / "beta.bin").read_bytes()
        assert hashlib.sha256(got).digest() == hashlib.sha256(expected).digest()
    finally:
        if receiver:
            await receiver.close()
        if publisher:
            await publisher.close()
        server.should_exit = True
        await task


def test_end_to_end(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "alpha.txt").write_bytes(b"hello pfs\n")
    (root / "sub" / "beta.bin").write_bytes(os.urandom(9 * 1024 * 1024))
    dest = tmp_path / "dest"
    dest.mkdir()

    asyncio.run(_run(root, dest))


async def _run_multi(root, dests):
    server, task, port = await _start_server()
    publisher = None
    receivers = []
    try:
        publisher = PublisherService(str(root), "127.0.0.1", port, ice_servers=[])
        invite = await publisher.start()

        receivers = [ReceiverService(invite, str(d), ice_servers=[]) for d in dests]
        await asyncio.gather(*(r.start() for r in receivers))

        manifests = await asyncio.gather(*(r.get_manifest() for r in receivers))
        for entries in manifests:
            assert {e.path for e in entries if e.type == TYPE_FILE} == {"alpha.txt", "sub/beta.bin"}

        async def download(receiver, entries):
            for entry in entries:
                if entry.type == TYPE_FILE:
                    await receiver.download_file(entry.path, entry.size)

        await asyncio.gather(*(download(r, m) for r, m in zip(receivers, manifests)))

        expected = (root / "sub" / "beta.bin").read_bytes()
        for dest in dests:
            assert (dest / "alpha.txt").read_bytes() == b"hello pfs\n"
            got = (dest / "sub" / "beta.bin").read_bytes()
            assert hashlib.sha256(got).digest() == hashlib.sha256(expected).digest()
    finally:
        for receiver in receivers:
            await receiver.close()
        if publisher:
            await publisher.close()
        server.should_exit = True
        await task


def test_multi_receiver(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "alpha.txt").write_bytes(b"hello pfs\n")
    (root / "sub" / "beta.bin").write_bytes(os.urandom(5 * 1024 * 1024))

    dests = []
    for name in ("d1", "d2", "d3"):
        d = tmp_path / name
        d.mkdir()
        dests.append(d)

    asyncio.run(_run_multi(root, dests))
