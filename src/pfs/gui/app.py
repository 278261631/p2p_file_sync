"""Desktop entrypoints: separate publisher and receiver apps.

The Qt event loop runs on the main thread; asyncio runs on a worker thread
(see :mod:`pfs.gui.async_runner`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _startup_error(message: str, app_name: str) -> None:
    """Report a startup failure; ``pythonw`` has no stderr, so also log to file."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        log_dir = Path(os.environ.get("PFS_LOG_DIR", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / f"{app_name}-startup.log").open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


def _run(window_cls, app_name: str) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # noqa: BLE001
        _startup_error(
            f"GUI dependencies missing. Install with: pip install 'pfs[gui]'\n  ({exc})",
            app_name,
        )
        return 1

    from ..common.logging_setup import setup_logging

    setup_logging(app_name, console=sys.stderr is not None)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(app_name)
    window = window_cls()
    window.show()
    return app.exec()


def run_publish() -> int:
    from .publish_window import PublishWindow

    return _run(PublishWindow, "pfs-publish")


def run_receive() -> int:
    from .receive_window import ReceiveWindow

    return _run(ReceiveWindow, "pfs-receive")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    mode = args[0].lower() if args else "publish"
    return run_receive() if mode == "receive" else run_publish()


if __name__ == "__main__":
    raise SystemExit(main())
