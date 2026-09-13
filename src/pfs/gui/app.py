"""Desktop entrypoint: Qt event loop on the main thread, asyncio on a worker."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # noqa: BLE001
        print("GUI dependencies missing. Install with: pip install 'pfs[gui]'", file=sys.stderr)
        print(f"  ({exc})", file=sys.stderr)
        return 1

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("pfs")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
