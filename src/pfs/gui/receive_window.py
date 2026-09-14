"""Standalone receiver window."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QTabWidget

from .async_runner import AsyncRunner
from .receive_tab import ReceiveTab
from .status_tab import StatusTab


class ReceiveWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pfs - 接收方")
        self.resize(820, 700)

        self.runner = AsyncRunner(self)
        self.tab = ReceiveTab(self.runner)
        self.status_tab = StatusTab(self.runner, lambda: self.tab.service)

        tabs = QTabWidget()
        tabs.addTab(self.tab, "接收")
        tabs.addTab(self.status_tab, "状态")
        self.setCentralWidget(tabs)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.status_tab.shutdown()
        self.tab.shutdown()
        self.runner.stop()
        event.accept()
