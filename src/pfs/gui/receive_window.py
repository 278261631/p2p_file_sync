"""Standalone receiver window."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

from .async_runner import AsyncRunner
from .receive_tab import ReceiveTab


class ReceiveWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pfs - 接收方")
        self.resize(760, 640)

        self.runner = AsyncRunner(self)
        self.tab = ReceiveTab(self.runner)
        self.setCentralWidget(self.tab)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.tab.shutdown()
        self.runner.stop()
        event.accept()
