"""Command line interface (headless) for pfs."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
import time

from ..common.config import DEFAULT_SIGNAL_HOST, DEFAULT_SIGNAL_PORT, build_ice_servers
from ..common.human import fmt_duration, fmt_size
from ..common.logging_setup import setup_logging
from ..common.manifest import expand_selection
from ..publisher.service import PublisherService
from ..receiver.service import ReceiverService


def _add_conn_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", default=DEFAULT_SIGNAL_HOST, help="signaling server host")
    parser.add_argument("--port", type=int, default=DEFAULT_SIGNAL_PORT, help="signaling server port")
    parser.add_argument("--user", required=True, help="account name")
    parser.add_argument("--password", default=None, help="account password (prompted if omitted)")
    parser.add_argument("--tls", action="store_true", help="use wss:// (required over the internet)")


def _add_ice_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--turn", default=None, help="TURN url, e.g. turn:relay.example.com:3478")
    parser.add_argument("--turn-user", default=None)
    parser.add_argument("--turn-pass", default=None)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pfs", description="P2P folder sharing over WebRTC")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="publish a folder")
    serve.add_argument("--root", required=True, help="folder to share")
    serve.add_argument("--name", default=None, help="share name (defaults to folder name)")
    _add_conn_args(serve)
    _add_ice_args(serve)

    lst = sub.add_parser("list", help="list available shares")
    _add_conn_args(lst)

    get = sub.add_parser("get", help="download from a share")
    get.add_argument("share", help="share name or id (see `pfs list`)")
    get.add_argument("paths", nargs="+", help="file/folder paths within the share")
    get.add_argument("--dest", default=".", help="destination directory")
    get.add_argument("--concurrency", type=int, default=4, help="chunks requested in parallel")
    get.add_argument("--retries", type=int, default=3, help="retries per chunk")
    _add_conn_args(get)
    _add_ice_args(get)
    return parser


def _ice(args):
    return build_ice_servers(
        turn_url=getattr(args, "turn", None),
        turn_user=getattr(args, "turn_user", None),
        turn_pass=getattr(args, "turn_pass", None),
    )


def _password(args) -> str:
    if getattr(args, "password", None):
        return args.password
    return getpass.getpass(f"password for {args.user}: ")


async def _cmd_serve(args) -> int:
    service = PublisherService(
        signal_host=args.server,
        signal_port=args.port,
        account=args.user,
        password=_password(args),
        tls=args.tls,
        ice_servers=_ice(args),
    )
    share_id = await service.start(args.root, args.name)
    print(f"{service.share_name}\t{share_id}", flush=True)
    print(
        f"published '{service.share_name}' as {args.user}; waiting for receivers (Ctrl+C to stop).",
        file=sys.stderr,
        flush=True,
    )

    async def watch() -> None:
        while True:
            kind, payload = await service.next_event()
            print(f"[{kind}] {payload}", file=sys.stderr, flush=True)

    watcher = asyncio.create_task(watch())
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        watcher.cancel()
        await service.close()
    return 0


async def _cmd_list(args) -> int:
    service = ReceiverService(
        signal_host=args.server,
        signal_port=args.port,
        account=args.user,
        password=_password(args),
        dest=".",
        tls=args.tls,
        ice_servers=_ice(args),
    )
    try:
        await service.start()
        shares = await service.list_shares()
    finally:
        await service.close()
    if not shares:
        print("(no shares online)")
        return 0
    for share in shares:
        print(f"{share['id']}  {share['owner']:<16} {share['name']:<24} {share['file_count']:>6} files  {fmt_size(share['total_size'])}")
    return 0


async def _cmd_get(args) -> int:
    service = ReceiverService(
        signal_host=args.server,
        signal_port=args.port,
        account=args.user,
        password=_password(args),
        dest=args.dest,
        tls=args.tls,
        ice_servers=_ice(args),
        concurrency=args.concurrency,
        max_retries=args.retries,
    )
    await service.start()
    try:
        shares = await service.list_shares()
        share = next((s for s in shares if s["name"] == args.share or s["id"] == args.share), None)
        if share is None:
            names = ", ".join(s["name"] for s in shares) or "(none)"
            print(f"share not found: {args.share}; available: {names}", file=sys.stderr)
            return 1

        entries = await service.get_manifest(share["id"])
        selected = expand_selection(entries, args.paths)
        if not selected:
            print("no matching files", file=sys.stderr)
            return 1

        for entry in entries:
            if entry.type == "dir":
                os.makedirs(os.path.join(args.dest, entry.path), exist_ok=True)

        print(f"connecting to {share['owner']} / {share['name']} ...", file=sys.stderr)
        await service.open_share(share["id"])

        for entry in selected:
            start = time.monotonic()

            def progress(done: int, total: int, name: str = entry.path, start: float = start) -> None:
                elapsed = max(time.monotonic() - start, 1e-6)
                speed = done / elapsed
                pct = 100 if total == 0 else int(done * 100 / total)
                eta = ""
                if speed > 0 and total > done:
                    eta = f" ETA {fmt_duration((total - done) / speed)}"
                print(
                    f"\r  {name}  {fmt_size(done)}/{fmt_size(total)} ({pct}%) {fmt_size(speed)}/s{eta}",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )

            print(f"downloading {entry.path} ({entry.size} bytes)", file=sys.stderr)
            await service.download_file(entry.path, entry.size, progress=progress)
            print(file=sys.stderr, flush=True)
        return 0
    finally:
        await service.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    setup_logging(f"pfs-{args.cmd}", level=logging.DEBUG if args.verbose else logging.INFO)
    handlers = {
        "serve": _cmd_serve,
        "list": _cmd_list,
        "get": _cmd_get,
    }
    try:
        return asyncio.run(handlers[args.cmd](args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
