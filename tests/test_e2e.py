"""End-to-end tests: signaling server + publisher + receivers in one loop."""

import asyncio
import hashlib
import json
import os

import pytest
import uvicorn

from pfs.common.manifest import TYPE_FILE
from pfs.publisher.service import PublisherService
from pfs.receiver.service import ReceiverService
from server import signal_server
from server.accounts import AccountStore
from server.signal_server import app

USERS = [
    {"name": "alice", "password": "pw1"},
    {"name": "bob", "password": "pw2"},
    {"name": "carol", "password": "pw3"},
]


def _accounts_file(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"users": USERS}), encoding="utf-8")
    return path


async def _start_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


async def _run(root, dest, accounts_path):
    signal_server.hub.store = AccountStore(accounts_path)
    server, task, port = await _start_server()
    publisher = None
    receiver = None
    try:
        publisher = PublisherService("127.0.0.1", port, "alice", "pw1", ice_servers=[])
        share_id = await publisher.start(str(root), "share1")

        receiver = ReceiverService("127.0.0.1", port, "bob", "pw2", str(dest), ice_servers=[])
        await receiver.start()

        shares = await receiver.list_shares()
        assert any(s["id"] == share_id and s["name"] == "share1" and s["owner"] == "alice" for s in shares)

        entries = await receiver.get_manifest(share_id)
        files = [e for e in entries if e.type == TYPE_FILE]
        assert {f.path for f in files} == {"alpha.txt", "sub/beta.bin"}

        await receiver.open_share(share_id)
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

    asyncio.run(_run(root, dest, _accounts_file(tmp_path)))


async def _run_multi(root, dests, accounts_path):
    signal_server.hub.store = AccountStore(accounts_path)
    server, task, port = await _start_server()
    publisher = None
    receivers = []
    try:
        publisher = PublisherService("127.0.0.1", port, "alice", "pw1", ice_servers=[])
        share_id = await publisher.start(str(root), "share1")

        receivers = [
            ReceiverService("127.0.0.1", port, user, pw, str(d), ice_servers=[])
            for (user, pw, d) in [("bob", "pw2", dests[0]), ("carol", "pw3", dests[1])]
        ]
        await asyncio.gather(*(r.start() for r in receivers))

        manifests = await asyncio.gather(*(r.get_manifest(share_id) for r in receivers))
        for entries in manifests:
            assert {e.path for e in entries if e.type == TYPE_FILE} == {"alpha.txt", "sub/beta.bin"}

        async def download(receiver, entries):
            await receiver.open_share(share_id)
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
    for name in ("d1", "d2"):
        d = tmp_path / name
        d.mkdir()
        dests.append(d)

    asyncio.run(_run_multi(root, dests, _accounts_file(tmp_path)))


async def _run_bad_login(accounts_path):
    signal_server.hub.store = AccountStore(accounts_path)
    server, task, port = await _start_server()
    receiver = ReceiverService("127.0.0.1", port, "bob", "wrong-password", ".", ice_servers=[])
    try:
        with pytest.raises(RuntimeError):
            await receiver.start()
    finally:
        await receiver.close()
        server.should_exit = True
        await task


def test_login_rejects_wrong_password(tmp_path):
    asyncio.run(_run_bad_login(_accounts_file(tmp_path)))
