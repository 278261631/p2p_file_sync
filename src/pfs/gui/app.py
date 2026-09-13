"""Desktop entrypoints: separate publisher and receiver apps.

The Qt event loop runs on the main thread; asyncio runs on a worker thread
(see :mod:`pfs.gui.async_runner`).
"""

from __future__ import annotations

import sys


def _run(window_cls, app_name: str) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # noqa: BLE001
        print("GUI dependencies missing. Install with: pip install 'pfs[gui]'", file=sys.stderr)
        print(f"  ({exc})", file=sys.stderr)
        return 1

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
