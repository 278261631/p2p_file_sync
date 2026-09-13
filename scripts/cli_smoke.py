"""End-to-end CLI smoke test using real subprocesses.

Starts the signaling server (with a temp accounts file) and a publisher, then
drives ``pfs list`` and ``pfs get`` as separate processes.

Usage::

    python scripts/cli_smoke.py
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PFS_SMOKE_PORT", "8799"))


def _popen(args, env=None, **kwargs):
    return subprocess.Popen(
        args,
        cwd=str(REPO),
        stdout=kwargs.pop("stdout", subprocess.PIPE),
        stderr=kwargs.pop("stderr", subprocess.PIPE),
        text=True,
        env=env,
        **kwargs,
    )


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="pfs_smoke_"))
    share = work / "share"
    dest = work / "dest"
    (share / "docs").mkdir(parents=True)
    dest.mkdir(parents=True)
    (share / "hello.txt").write_text("hello from cli", encoding="utf-8")
    (share / "docs" / "note.txt").write_text("note body", encoding="utf-8")
    (share / "blob.bin").write_bytes(os.urandom(9 * 1024 * 1024))

    accounts = work / "accounts.json"
    accounts.write_text(
        json.dumps({"users": [{"name": "alice", "password": "pw1"}, {"name": "bob", "password": "pw2"}]}),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PFS_ACCOUNTS"] = str(accounts)

    server = _popen(
        [sys.executable, "-m", "uvicorn", "server.signal_server:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        env=env,
        stderr=subprocess.DEVNULL,
    )
    publisher = None
    pub_err = open(work / "publisher.err", "w", encoding="utf-8")
    try:
        time.sleep(3.0)
        publisher = _popen(
            [
                sys.executable, "-m", "pfs.cli.main", "serve",
                "--root", str(share),
                "--name", "share1",
                "--server", "127.0.0.1",
                "--port", str(PORT),
                "--user", "alice",
                "--password", "pw1",
            ],
            env=env,
            stderr=pub_err,
        )
        published = publisher.stdout.readline().strip()
        if not published:
            pub_err.flush()
            print("publisher produced no output:")
            print((work / "publisher.err").read_text(encoding="utf-8", errors="replace"))
            return 1
        print(f"published: {published}")
        share_name = published.split("\t")[0]

        listing = subprocess.run(
            [sys.executable, "-m", "pfs.cli.main", "list", "--server", "127.0.0.1", "--port", str(PORT), "--user", "bob", "--password", "pw2"],
            cwd=str(REPO), capture_output=True, text=True, timeout=90, env=env,
        )
        print(listing.stdout.strip())
        assert listing.returncode == 0, listing.stderr
        assert share_name in listing.stdout

        get = subprocess.run(
            [
                sys.executable, "-m", "pfs.cli.main", "get", share_name, "docs", "hello.txt", "blob.bin",
                "--dest", str(dest), "--server", "127.0.0.1", "--port", str(PORT), "--user", "bob", "--password", "pw2",
            ],
            cwd=str(REPO), capture_output=True, text=True, timeout=180, env=env,
        )
        assert get.returncode == 0, get.stderr

        assert (dest / "hello.txt").read_text(encoding="utf-8") == "hello from cli"
        assert (dest / "docs" / "note.txt").read_text(encoding="utf-8") == "note body"
        assert (dest / "blob.bin").read_bytes() == (share / "blob.bin").read_bytes()

        print("CLI SMOKE: PASS")
        return 0
    finally:
        for proc in (publisher, server):
            if proc and proc.poll() is None:
                if os.name == "nt":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGINT)
        time.sleep(0.5)
        for proc in (publisher, server):
            if proc and proc.poll() is None:
                proc.kill()
        pub_err.close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
