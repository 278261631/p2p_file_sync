"""End-to-end CLI smoke test using real subprocesses.

Starts the signaling server and a publisher, then drives ``pfs list`` and
``pfs get`` as separate processes and verifies the downloaded bytes.

Usage::

    python scripts/cli_smoke.py
"""

from __future__ import annotations

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


def _popen(args, **kwargs):
    return subprocess.Popen(
        args,
        cwd=str(REPO),
        stdout=kwargs.pop("stdout", subprocess.PIPE),
        stderr=kwargs.pop("stderr", subprocess.PIPE),
        text=True,
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

    server = _popen(
        [sys.executable, "-m", "uvicorn", "server.signal_server:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
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
                "--signal-host", "127.0.0.1",
                "--signal-port", str(PORT),
                "--host", "127.0.0.1",
                "--port", str(PORT),
            ],
            stderr=pub_err,
        )
        invite = publisher.stdout.readline().strip()
        if not invite.startswith("PFS1."):
            pub_err.flush()
            print("no invite code, publisher stderr:")
            print((work / "publisher.err").read_text(encoding="utf-8", errors="replace"))
            return 1
        print(f"invite: {invite}")

        listing = subprocess.run(
            [sys.executable, "-m", "pfs.cli.main", "list", invite],
            cwd=str(REPO), capture_output=True, text=True, timeout=90,
        )
        print(listing.stdout.strip())
        assert listing.returncode == 0, listing.stderr
        assert "hello.txt" in listing.stdout and "docs/note.txt" in listing.stdout

        get = subprocess.run(
            [sys.executable, "-m", "pfs.cli.main", "get", invite, "docs", "hello.txt", "blob.bin", "--dest", str(dest)],
            cwd=str(REPO), capture_output=True, text=True, timeout=180,
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
