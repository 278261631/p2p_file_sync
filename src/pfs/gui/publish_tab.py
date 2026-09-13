"""Publisher tab: pick a folder, publish it, show the invite code."""

from __future__ import annotations

import asyncio

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..common.config import DEFAULT_SIGNAL_HOST, DEFAULT_SIGNAL_PORT, build_ice_servers
from ..common.settings import load_settings
from ..publisher.service import PublisherService
from .async_runner import AsyncRunner, GuiBridge


def _wrap(layout) -> QWidget:
    box = QWidget()
    box.setLayout(layout)
    return box


class PublishTab(QWidget):
    def __init__(self, runner: AsyncRunner) -> None:
        super().__init__()
        self.runner = runner
        self.service: PublisherService | None = None
        self._watch_future = None
        self._settings = load_settings()
        self._bridge = GuiBridge(self)
        self._build()
        self._restore()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.root_edit = QLineEdit()
        self.root_edit.setReadOnly(True)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._choose_root)
        row = QHBoxLayout()
        row.addWidget(self.root_edit)
        row.addWidget(browse)
        form.addRow("共享文件夹", _wrap(row))

        self.host_edit = QLineEdit(DEFAULT_SIGNAL_HOST)
        form.addRow("信令服务器", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_SIGNAL_PORT)
        form.addRow("信令端口", self.port_spin)
        layout.addLayout(form)

        advanced = QGroupBox("高级（跨网时配置 TURN 中继）")
        adv_form = QFormLayout(advanced)
        self.turn_edit = QLineEdit()
        self.turn_edit.setPlaceholderText("turn:relay.example.com:3478")
        self.turn_user_edit = QLineEdit()
        self.turn_pass_edit = QLineEdit()
        self.turn_pass_edit.setEchoMode(QLineEdit.Password)
        adv_form.addRow("TURN 地址", self.turn_edit)
        adv_form.addRow("用户名", self.turn_user_edit)
        adv_form.addRow("密码", self.turn_pass_edit)
        layout.addWidget(advanced)

        self.start_btn = QPushButton("开始发布")
        self.start_btn.clicked.connect(self._toggle)
        layout.addWidget(self.start_btn)

        layout.addWidget(QLabel("邀请码（发给接收方）："))
        self.code_edit = QLineEdit()
        self.code_edit.setReadOnly(True)
        copy = QPushButton("复制")
        copy.clicked.connect(self._copy_code)
        row2 = QHBoxLayout()
        row2.addWidget(self.code_edit)
        row2.addWidget(copy)
        layout.addLayout(row2)

        layout.addWidget(QLabel("已连接的接收方："))
        self.peers = QListWidget()
        layout.addWidget(self.peers)

    def _restore(self) -> None:
        root = self._settings.value("publish/root", "")
        if root:
            self.root_edit.setText(str(root))

    def _choose_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择要共享的文件夹")
        if path:
            self.root_edit.setText(path)
            self._settings.setValue("publish/root", path)

    def _copy_code(self) -> None:
        if self.code_edit.text():
            QApplication.clipboard().setText(self.code_edit.text())

    def _toggle(self) -> None:
        if self.service is None:
            self.start_btn.setEnabled(False)
            self.start_btn.setText("连接中...")
            self.runner.submit(self._start())
        else:
            self.start_btn.setEnabled(False)
            self.runner.submit(self._stop())

    async def _start(self) -> None:
        root = self.root_edit.text()
        if not root:
            self._bridge.post(lambda: self._fail("请先选择要共享的文件夹"))
            return
        host = self.host_edit.text().strip() or DEFAULT_SIGNAL_HOST
        port = self.port_spin.value()
        self.service = PublisherService(
            root=root,
            signal_host=host,
            signal_port=port,
            host=host,
            port=port,
            ice_servers=build_ice_servers(
                turn_url=self.turn_edit.text().strip() or None,
                turn_user=self.turn_user_edit.text().strip() or None,
                turn_pass=self.turn_pass_edit.text() or None,
            ),
        )
        try:
            invite = await self.service.start()
        except Exception as exc:  # noqa: BLE001
            await self.service.close()
            self.service = None
            self._bridge.post(lambda: self._fail(f"发布失败：{exc}"))
            return

        code = invite.to_code()
        self._bridge.post(lambda: self._on_started(code))
        self._watch_future = self.runner.submit(self._watch())

    def _on_started(self, code: str) -> None:
        self.code_edit.setText(code)
        self.start_btn.setText("停止发布")
        self.start_btn.setEnabled(True)

    def _fail(self, message: str) -> None:
        self.start_btn.setText("开始发布")
        self.start_btn.setEnabled(True)
        QMessageBox.critical(self, "发布失败", message)

    async def _stop(self) -> None:
        if self._watch_future:
            self._watch_future.cancel()
            self._watch_future = None
        if self.service:
            await self.service.close()
            self.service = None
        self._bridge.post(self._on_stopped)

    def _on_stopped(self) -> None:
        self.code_edit.clear()
        self.start_btn.setText("开始发布")
        self.start_btn.setEnabled(True)
        self.peers.clear()

    async def _watch(self) -> None:
        try:
            while self.service is not None:
                kind, peer_id = await self.service.next_peer_event()
                if kind == "joined":
                    self._bridge.post(lambda pid=peer_id: self.peers.addItem(pid))
                else:
                    self._bridge.post(lambda pid=peer_id: self._remove_peer(pid))
        except asyncio.CancelledError:
            pass

    def _remove_peer(self, peer_id: str) -> None:
        for index in range(self.peers.count()):
            if self.peers.item(index).text() == peer_id:
                self.peers.takeItem(index)
                return

    def shutdown(self) -> None:
        if self._watch_future:
            self._watch_future.cancel()
            self._watch_future = None
        if self.service:
            self.runner.submit(self.service.close())
            self.service = None
