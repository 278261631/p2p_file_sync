"""Standalone publisher window."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QTabWidget

from .async_runner import AsyncRunner
from .publish_tab import PublishTab
from .status_tab import StatusTab


class PublishWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pfs - 发布方")
        self.resize(720, 600)

        self.runner = AsyncRunner(self)
        self.tab = PublishTab(self.runner)
        self.status_tab = StatusTab(self.runner, lambda: self.tab.service)

        tabs = QTabWidget()
        tabs.addTab(self.tab, "发布")
        tabs.addTab(self.status_tab, "状态")
        self.setCentralWidget(tabs)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.status_tab.shutdown()
        self.tab.shutdown()
        self.runner.stop()
        event.accept()
