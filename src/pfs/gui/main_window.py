"""Main application window."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QTabWidget

from .async_runner import AsyncRunner
from .publish_tab import PublishTab
from .receive_tab import ReceiveTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pfs - P2P 文件同步")
        self.resize(820, 640)

        self.runner = AsyncRunner(self)
        self.publish_tab = PublishTab(self.runner)
        self.receive_tab = ReceiveTab(self.runner)

        tabs = QTabWidget()
        tabs.addTab(self.publish_tab, "发布")
        tabs.addTab(self.receive_tab, "接收")
        self.setCentralWidget(tabs)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.publish_tab.shutdown()
        self.receive_tab.shutdown()
        self.runner.stop()
        event.accept()
