"""Receiver tab: paste an invite, pick files from the tree, download."""

from __future__ import annotations

import asyncio
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..common.config import build_ice_servers
from ..common.human import fmt_duration, fmt_size
from ..common.invite import Invite
from ..common.manifest import TYPE_DIR, Entry, expand_selection
from ..common.settings import load_settings
from ..receiver.service import ReceiverService
from .async_runner import AsyncRunner, GuiBridge


def _wrap(layout) -> QWidget:
    box = QWidget()
    box.setLayout(layout)
    return box


class ReceiveTab(QWidget):
    def __init__(self, runner: AsyncRunner) -> None:
        super().__init__()
        self.runner = runner
        self.service: ReceiverService | None = None
        self.entries: list[Entry] = []
        self._updating = False
        self._download_future = None
        self._settings = load_settings()
        self._bridge = GuiBridge(self)
        self._build()
        self._restore()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.invite_edit = QLineEdit()
        self.invite_edit.setPlaceholderText("PFS1....")
        form.addRow("邀请码", self.invite_edit)

        self.dest_edit = QLineEdit()
        self.dest_edit.setReadOnly(True)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._choose_dest)
        row = QHBoxLayout()
        row.addWidget(self.dest_edit)
        row.addWidget(browse)
        form.addRow("保存到", _wrap(row))
        layout.addLayout(form)

        advanced = QGroupBox("高级（跨网时配置 TURN 中继）")
        adv_form = QFormLayout(advanced)
        self.turn_edit = QLineEdit()
        self.turn_edit.setPlaceholderText("turn:relay.example.com:3478")
        self.turn_user_edit = QLineEdit()
        self.turn_pass_edit = QLineEdit()
        self.turn_pass_edit.setEchoMode(QLineEdit.Password)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(4)
        adv_form.addRow("TURN 地址", self.turn_edit)
        adv_form.addRow("用户名", self.turn_user_edit)
        adv_form.addRow("密码", self.turn_pass_edit)
        adv_form.addRow("并行块数", self.concurrency_spin)
        layout.addWidget(advanced)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self.connect_btn)

        layout.addWidget(QLabel("远程文件（勾选要下载的内容）："))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "大小"])
        self.tree.setColumnWidth(0, 460)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

        buttons = QHBoxLayout()
        self.download_btn = QPushButton("下载选中")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._start_download)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_download)
        buttons.addWidget(self.download_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def _restore(self) -> None:
        dest = self._settings.value("receive/dest", "")
        if dest:
            self.dest_edit.setText(str(dest))

    def _choose_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if path:
            self.dest_edit.setText(path)
            self._settings.setValue("receive/dest", path)

    # -- connection ---------------------------------------------------------
    def _on_connect_clicked(self) -> None:
        code = self.invite_edit.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请粘贴邀请码")
            return
        try:
            invite = Invite.from_code(code)
        except ValueError as exc:
            QMessageBox.critical(self, "邀请码错误", str(exc))
            return

        dest = self.dest_edit.text()
        if not dest:
            dest = QFileDialog.getExistingDirectory(self, "选择保存目录")
            if not dest:
                return
            self.dest_edit.setText(dest)

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("连接中...")
        self.download_btn.setEnabled(False)
        self.runner.submit(self._do_connect(invite, dest))

    async def _do_connect(self, invite: Invite, dest: str) -> None:
        if self.service:
            await self.service.close()
        self.service = ReceiverService(
            invite,
            dest,
            ice_servers=build_ice_servers(
                turn_url=self.turn_edit.text().strip() or None,
                turn_user=self.turn_user_edit.text().strip() or None,
                turn_pass=self.turn_pass_edit.text() or None,
            ),
            concurrency=self.concurrency_spin.value(),
        )
        try:
            await self.service.start()
            self.entries = await self.service.get_manifest()
        except Exception as exc:  # noqa: BLE001
            await self.service.close()
            self.service = None
            self._bridge.post(lambda m=str(exc): self._on_connect_failed(m))
            return
        self._bridge.post(self._on_connected)

    def _on_connected(self) -> None:
        self._populate()
        self.download_btn.setEnabled(True)
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("重新连接")
        self.log.appendPlainText(f"已连接，共 {len(self.entries)} 项")

    def _on_connect_failed(self, message: str) -> None:
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("连接")
        QMessageBox.critical(self, "连接失败", message)

    # -- tree ---------------------------------------------------------------
    def _populate(self) -> None:
        self._updating = True
        self.tree.clear()
        nodes: dict[str, QTreeWidgetItem] = {}
        for entry in self.entries:
            name = entry.path.rsplit("/", 1)[-1]
            item = QTreeWidgetItem()
            if entry.type == TYPE_DIR:
                item.setText(0, name + "/")
            else:
                item.setText(0, name)
                item.setText(1, str(entry.size))
            item.setData(0, Qt.UserRole, entry.path)
            item.setData(0, Qt.UserRole + 1, entry.type)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            parent_path = entry.path.rsplit("/", 1)[0] if "/" in entry.path else ""
            parent = nodes.get(parent_path, self.tree.invisibleRootItem())
            parent.addChild(item)
            nodes[entry.path] = item
        self.tree.expandAll()
        self._updating = False

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._updating:
            return
        self._updating = True
        self._set_children(item, item.checkState(0))
        self._updating = False

    def _set_children(self, item: QTreeWidgetItem, state) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            child.setCheckState(0, state)
            self._set_children(child, state)

    def _selected_paths(self) -> list[str]:
        paths: list[str] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item.checkState(0) == Qt.Checked:
                paths.append(item.data(0, Qt.UserRole))
            for index in range(item.childCount()):
                walk(item.child(index))

        for index in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(index))
        return paths

    # -- download -----------------------------------------------------------
    def _start_download(self) -> None:
        if self._download_future and not self._download_future.done():
            return
        if not self.service:
            return
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "提示", "请先勾选要下载的文件或文件夹")
            return
        files = expand_selection(self.entries, paths)
        if not files:
            QMessageBox.information(self, "提示", "没有匹配的文件")
            return
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._download_future = self.runner.submit(self._download(files, self.dest_edit.text()))

    def _cancel_download(self) -> None:
        if self._download_future and not self._download_future.done():
            self._download_future.cancel()
            self.log.appendPlainText("已请求取消，已下载的分块会保留以便续传")

    async def _download(self, files: list[Entry], dest: str) -> None:
        try:
            for entry in self.entries:
                if entry.type == TYPE_DIR:
                    os.makedirs(os.path.join(dest, entry.path), exist_ok=True)

            total_files = len(files)
            for index, entry in enumerate(files, 1):
                self._log(f"[{index}/{total_files}] {entry.path} ({fmt_size(entry.size)})")
                start = time.monotonic()

                def progress(done: int, total: int, _start: float = start) -> None:
                    elapsed = max(time.monotonic() - _start, 1e-6)
                    speed = done / elapsed
                    pct = 100 if total == 0 else int(done * 100 / total)
                    eta = ""
                    if speed > 0 and total > done:
                        eta = f"  ETA {fmt_duration((total - done) / speed)}"
                    text = f"{pct}%  {fmt_size(speed)}/s{eta}"
                    self._bridge.post(lambda p=pct, t=text: self._set_progress(p, t))

                await self.service.download_file(entry.path, entry.size, progress=progress)
                self._log(f"    完成 {entry.path}")
        except asyncio.CancelledError:
            self._log("下载已取消")
        except Exception as exc:  # noqa: BLE001
            self._bridge.post(lambda m=str(exc): QMessageBox.critical(self, "下载失败", m))
        finally:
            self._bridge.post(self._on_download_finished)

    def _set_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.progress.setFormat(text)

    def _on_download_finished(self) -> None:
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")

    def _log(self, message: str) -> None:
        self._bridge.post(lambda m=message: self.log.appendPlainText(m))

    def shutdown(self) -> None:
        if self._download_future and not self._download_future.done():
            self._download_future.cancel()
        if self.service:
            self.runner.submit(self.service.close())
            self.service = None
