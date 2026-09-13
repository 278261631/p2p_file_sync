"""Standalone publisher window."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

from .async_runner import AsyncRunner
from .publish_tab import PublishTab


class PublishWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pfs - 发布方")
        self.resize(640, 540)

        self.runner = AsyncRunner(self)
        self.tab = PublishTab(self.runner)
        self.setCentralWidget(self.tab)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.tab.shutdown()
        self.runner.stop()
        event.accept()
