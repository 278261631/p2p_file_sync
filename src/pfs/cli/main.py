"""Command line interface (headless) for pfs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

from ..common.config import DEFAULT_SIGNAL_HOST, DEFAULT_SIGNAL_PORT, build_ice_servers
from ..common.human import fmt_duration, fmt_size
from ..common.invite import Invite
from ..common.manifest import expand_selection
from ..publisher.service import PublisherService
from ..receiver.service import ReceiverService


def _add_ice_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--turn", default=None, help="TURN url, e.g. turn:relay.example.com:3478")
    parser.add_argument("--turn-user", default=None)
    parser.add_argument("--turn-pass", default=None)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pfs", description="P2P folder sharing over WebRTC")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="publish a folder and wait for receivers")
    serve.add_argument("--root", required=True, help="folder to share")
    serve.add_argument("--signal-host", default=DEFAULT_SIGNAL_HOST)
    serve.add_argument("--signal-port", type=int, default=DEFAULT_SIGNAL_PORT)
    serve.add_argument("--host", default=None, help="host advertised inside the invite code")
    serve.add_argument("--port", type=int, default=None, help="port advertised inside the invite code")
    _add_ice_args(serve)

    lst = sub.add_parser("list", help="print the remote file listing")
    lst.add_argument("invite", help="invite code from the publisher")
    _add_ice_args(lst)

    get = sub.add_parser("get", help="download files or folders")
    get.add_argument("invite", help="invite code from the publisher")
    get.add_argument("paths", nargs="+", help="file/folder paths as shown by `pfs list`")
    get.add_argument("--dest", default=".", help="destination directory")
    get.add_argument("--concurrency", type=int, default=4, help="chunks requested in parallel")
    get.add_argument("--retries", type=int, default=3, help="retries per chunk")
    _add_ice_args(get)
    return parser


def _ice(args):
    return build_ice_servers(
        turn_url=getattr(args, "turn", None),
        turn_user=getattr(args, "turn_user", None),
        turn_pass=getattr(args, "turn_pass", None),
    )


async def _cmd_serve(args) -> int:
    service = PublisherService(
        root=args.root,
        signal_host=args.signal_host,
        signal_port=args.signal_port,
        host=args.host,
        port=args.port,
        ice_servers=_ice(args),
    )
    invite = await service.start()
    print(invite.to_code(), flush=True)
    print("Share the code above. Waiting for receivers (Ctrl+C to stop).", file=sys.stderr, flush=True)

    async def watch() -> None:
        while True:
            kind, peer_id = await service.next_peer_event()
            print(f"[{kind}] {peer_id}", file=sys.stderr, flush=True)

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
    invite = Invite.from_code(args.invite)
    service = ReceiverService(invite, dest=".", ice_servers=_ice(args))
    try:
        await service.start()
        entries = await service.get_manifest()
    finally:
        await service.close()
    for entry in entries:
        if entry.type == "dir":
            print(f"{'DIR':>4} {'':>12}  {entry.path}/")
        else:
            print(f"{'FILE':>4} {entry.size:>12}  {entry.path}")
    return 0


async def _cmd_get(args) -> int:
    invite = Invite.from_code(args.invite)
    service = ReceiverService(
        invite,
        dest=args.dest,
        ice_servers=_ice(args),
        concurrency=args.concurrency,
        max_retries=args.retries,
    )
    await service.start()
    try:
        entries = await service.get_manifest()
        selected = expand_selection(entries, args.paths)
        if not selected:
            print("no matching files", file=sys.stderr)
            return 1

        for entry in entries:
            if entry.type == "dir":
                os.makedirs(os.path.join(args.dest, entry.path), exist_ok=True)

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
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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
