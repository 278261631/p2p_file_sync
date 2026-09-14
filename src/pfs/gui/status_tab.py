"""Status tab: signaling-server connection, online accounts and shares.

Polls the signaling server through the active publisher/receiver service, so it
works in both windows without owning a connection of its own.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..common.human import exc_text, fmt_size
from .async_runner import AsyncRunner, GuiBridge

ServiceProvider = Callable[[], object]


class StatusTab(QWidget):
    def __init__(self, runner: AsyncRunner, service_provider: ServiceProvider, interval_ms: int = 5000) -> None:
        super().__init__()
        self.runner = runner
        self._provider = service_provider
        self._bridge = GuiBridge(self)
        self._busy = False
        self._future = None
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.status = QLabel("未登录")
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.status, 1)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        layout.addWidget(QLabel("在线账号："))
        self.accounts = QListWidget()
        layout.addWidget(self.accounts)

        layout.addWidget(QLabel("在线共享："))
        self.shares = QTreeWidget()
        self.shares.setHeaderLabels(["共享名称", "发布方", "文件数", "大小"])
        self.shares.setColumnWidth(0, 220)
        layout.addWidget(self.shares)

    # -- refresh ------------------------------------------------------------
    def refresh(self) -> None:
        service = self._provider()
        if service is None or getattr(service, "signaling", None) is None:
            self._busy = False
            self.status.setText("未登录")
            self.accounts.clear()
            self.shares.clear()
            return
        if self._busy:
            return
        self._busy = True
        self._future = self.runner.submit(self._do_refresh(service))

    async def _do_refresh(self, service) -> None:
        try:
            shares = await service.list_shares()
        except Exception as exc:  # noqa: BLE001
            self._bridge.post(lambda m=exc_text(exc): self._on_error(m))
            return
        presence = list(getattr(service, "presence", []) or [])
        self._bridge.post(lambda: self._on_data(service, presence, shares))

    def _on_data(self, service, presence: list, shares: list) -> None:
        self._busy = False
        self.accounts.clear()
        for name in presence:
            self.accounts.addItem(name)
        self.shares.clear()
        for share in shares:
            item = QTreeWidgetItem(
                [share["name"], share["owner"], str(share["file_count"]), fmt_size(share["total_size"])]
            )
            item.setData(0, Qt.UserRole, share["id"])
            self.shares.addTopLevelItem(item)
        scheme = "wss" if getattr(service, "tls", False) else "ws"
        endpoint = f"{scheme}://{service.signal_host}:{service.signal_port}"
        self.status.setText(
            f"已连接 {endpoint} · {time.strftime('%H:%M:%S')} · 共享 {len(shares)} · 在线 {len(presence)}"
        )

    def _on_error(self, message: str) -> None:
        self._busy = False
        self.status.setText(f"刷新失败：{message}")

    def shutdown(self) -> None:
        self._timer.stop()
        if self._future and not self._future.done():
            self._future.cancel()
