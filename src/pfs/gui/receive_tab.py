"""Receiver tab: log in, browse online shares, download."""

from __future__ import annotations

import asyncio
import os
import time

from PySide6.QtCore import Qt, QTimer
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
from ..common.human import exc_text, fmt_duration, fmt_size
from ..common.manifest import TYPE_DIR, Entry, expand_selection
from ..common.settings import load_settings
from ..receiver.service import ReceiverService
from .async_runner import AsyncRunner, GuiBridge
from .login_form import LoginForm


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
        self._current_share: str | None = None
        self._updating = False
        self._download_future = None
        self._settings = load_settings()
        self._bridge = GuiBridge(self)
        self._build()
        self._restore()

        self._traffic_timer = QTimer(self)
        self._traffic_timer.setInterval(1000)
        self._traffic_timer.timeout.connect(self._update_traffic)
        self._traffic_timer.start()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        login_box = QGroupBox("登录")
        login_layout = QVBoxLayout(login_box)
        self.login_form = LoginForm()
        self.login_form.login_requested.connect(self._on_login)
        login_layout.addWidget(self.login_form)
        layout.addWidget(login_box)

        shares_box = QGroupBox("在线共享")
        shares_layout = QVBoxLayout(shares_box)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self._refresh)
        self.open_btn = QPushButton("打开所选")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_selected)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        shares_layout.addLayout(row)
        self.shares = QTreeWidget()
        self.shares.setHeaderLabels(["共享名称", "发布方", "文件数", "大小"])
        self.shares.setColumnWidth(0, 240)
        shares_layout.addWidget(self.shares)
        layout.addWidget(shares_box)

        layout.addWidget(QLabel("文件（勾选要下载的内容）："))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "大小"])
        self.tree.setColumnWidth(0, 440)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

        form = QFormLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setReadOnly(True)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._choose_dest)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self.dest_edit)
        dest_row.addWidget(browse)
        form.addRow("保存到", _wrap(dest_row))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(4)
        form.addRow("并行块数", self.concurrency_spin)
        layout.addLayout(form)

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

        traffic_box = QGroupBox("流量统计")
        traffic_form = QFormLayout(traffic_box)
        self.direct_label = QLabel("0B")
        self.relay_label = QLabel("0B")
        self.unknown_label = QLabel("0B")
        traffic_form.addRow("直连 P2P", self.direct_label)
        traffic_form.addRow("中转 TURN", self.relay_label)
        traffic_form.addRow("未知路径", self.unknown_label)
        layout.addWidget(traffic_box)

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

    def _restore(self) -> None:
        self.dest_edit.setText(str(self._settings.value("receive/dest", "") or ""))
        self.concurrency_spin.setValue(int(self._settings.value("receive/concurrency", self.concurrency_spin.value())))
        self.login_form.host_edit.setText(str(self._settings.value("server/host", self.login_form.host_edit.text())))
        self.login_form.port_spin.setValue(int(self._settings.value("server/port", self.login_form.port_spin.value())))
        self.login_form.user_edit.setText(str(self._settings.value("server/user", "") or ""))
        self.login_form.password_edit.setText(str(self._settings.value("server/password", "") or ""))
        self.login_form.tls_check.setChecked(self._settings.value("server/tls", False, type=bool))
        self.turn_edit.setText(str(self._settings.value("turn/url", "") or ""))
        self.turn_user_edit.setText(str(self._settings.value("turn/user", "") or ""))
        self.turn_pass_edit.setText(str(self._settings.value("turn/pass", "") or ""))

    def _save_settings(self) -> None:
        form = self.login_form
        self._settings.setValue("server/host", form.host_edit.text().strip())
        self._settings.setValue("server/port", form.port_spin.value())
        self._settings.setValue("server/user", form.user_edit.text().strip())
        self._settings.setValue("server/password", form.password_edit.text())
        self._settings.setValue("server/tls", form.tls_check.isChecked())
        self._settings.setValue("turn/url", self.turn_edit.text().strip())
        self._settings.setValue("turn/user", self.turn_user_edit.text().strip())
        self._settings.setValue("turn/pass", self.turn_pass_edit.text())
        self._settings.setValue("receive/dest", self.dest_edit.text())
        self._settings.setValue("receive/concurrency", self.concurrency_spin.value())

    def _choose_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if path:
            self.dest_edit.setText(path)
            self._settings.setValue("receive/dest", path)

    def _ice(self) -> list:
        return build_ice_servers(
            turn_url=self.turn_edit.text().strip() or None,
            turn_user=self.turn_user_edit.text().strip() or None,
            turn_pass=self.turn_pass_edit.text() or None,
        )

    # -- login --------------------------------------------------------------
    def _on_login(self) -> None:
        values = self.login_form.values()
        if not values["user"]:
            QMessageBox.warning(self, "提示", "请输入账号")
            return
        self._save_settings()
        self.login_form.set_busy(True)
        self.service = ReceiverService(
            signal_host=values["host"],
            signal_port=values["port"],
            account=values["user"],
            password=values["password"],
            dest=self.dest_edit.text() or ".",
            tls=values["tls"],
            ice_servers=self._ice(),
            concurrency=self.concurrency_spin.value(),
        )
        self.runner.submit(self._do_login(values))

    async def _do_login(self, values: dict) -> None:
        try:
            await self.service.start()
        except Exception as exc:  # noqa: BLE001
            await self.service.close()
            self.service = None
            self._bridge.post(lambda m=exc_text(exc): self._on_login_failed(m))
            return
        self._bridge.post(lambda: self._on_logged_in(values))

    def _on_login_failed(self, message: str) -> None:
        self.login_form.set_busy(False)
        QMessageBox.critical(self, "登录失败", message)

    def _on_logged_in(self, values: dict) -> None:
        self.login_form.set_logged_in(values["user"])
        self.refresh_btn.setEnabled(True)
        self._refresh()

    # -- shares -------------------------------------------------------------
    def _refresh(self) -> None:
        if self.service:
            self.runner.submit(self._do_refresh())

    async def _do_refresh(self) -> None:
        try:
            shares = await self.service.list_shares()
        except Exception as exc:  # noqa: BLE001
            self._bridge.post(lambda m=exc_text(exc): self.log.appendPlainText(f"刷新失败：{m}"))
            return
        self._bridge.post(lambda: self._on_shares(shares))

    def _on_shares(self, shares: list) -> None:
        self.shares.clear()
        for share in shares:
            item = QTreeWidgetItem(
                [share["name"], share["owner"], str(share["file_count"]), fmt_size(share["total_size"])]
            )
            item.setData(0, Qt.UserRole, share["id"])
            self.shares.addTopLevelItem(item)
        self.open_btn.setEnabled(self.shares.topLevelItemCount() > 0)

    def _open_selected(self) -> None:
        item = self.shares.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择一个共享")
            return
        share_id = item.data(0, Qt.UserRole)
        self.open_btn.setEnabled(False)
        self.runner.submit(self._do_open(share_id))

    async def _do_open(self, share_id: str) -> None:
        try:
            entries = await self.service.get_manifest(share_id)
        except Exception as exc:  # noqa: BLE001
            self._bridge.post(lambda m=exc_text(exc): self._on_open_failed(m))
            return
        self._current_share = share_id
        self._bridge.post(lambda: self._on_manifest(entries))

    def _on_open_failed(self, message: str) -> None:
        self.open_btn.setEnabled(True)
        QMessageBox.critical(self, "打开失败", message)

    def _on_manifest(self, entries: list) -> None:
        self.entries = entries
        self._populate()
        self.download_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        self.log.appendPlainText(f"已打开共享，共 {len(entries)} 项")

    # -- file tree ----------------------------------------------------------
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
        if not self.service or not self._current_share:
            return
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "提示", "请先勾选要下载的文件或文件夹")
            return
        files = expand_selection(self.entries, paths)
        if not files:
            QMessageBox.information(self, "提示", "没有匹配的文件")
            return
        dest = self.dest_edit.text() or "."
        self.service.dest = dest
        self.service.concurrency = self.concurrency_spin.value()
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._download_future = self.runner.submit(self._download(files, dest))

    def _cancel_download(self) -> None:
        if self._download_future and not self._download_future.done():
            self._download_future.cancel()
            self.log.appendPlainText("已请求取消，已下载的分块会保留以便续传")

    async def _download(self, files: list[Entry], dest: str) -> None:
        try:
            self._log(f"正在连接 {self._current_share} ...")
            await self.service.open_share(self._current_share)

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
            self._bridge.post(lambda m=exc_text(exc): QMessageBox.critical(self, "下载失败", m))
        finally:
            self._bridge.post(self._on_download_finished)

    def _set_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.progress.setFormat(text)

    def _update_traffic(self) -> None:
        snapshot = self.service.traffic_snapshot() if self.service else {"totals": {}}
        totals = snapshot.get("totals", {})
        self.direct_label.setText(fmt_size(totals.get("direct", 0)))
        self.relay_label.setText(fmt_size(totals.get("relay", 0)))
        self.unknown_label.setText(fmt_size(totals.get("unknown", 0)))

    def _on_download_finished(self) -> None:
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")

    def _log(self, message: str) -> None:
        self._bridge.post(lambda m=message: self.log.appendPlainText(m))

    def shutdown(self) -> None:
        self._save_settings()
        self._traffic_timer.stop()
        if self._download_future and not self._download_future.done():
            self._download_future.cancel()
        if self.service:
            self.runner.submit(self.service.close())
            self.service = None
