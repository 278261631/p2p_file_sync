"""Publisher tab: log in, share a folder, watch online accounts."""

from __future__ import annotations

import asyncio

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..common.config import build_ice_servers
from ..common.human import exc_text, fmt_size
from ..common.settings import load_settings
from ..publisher.service import PublisherService
from .async_runner import AsyncRunner, GuiBridge
from .login_form import LoginForm


class PublishTab(QWidget):
    def __init__(self, runner: AsyncRunner) -> None:
        super().__init__()
        self.runner = runner
        self.service: PublisherService | None = None
        self._publishing = False
        self._watch_future = None
        self._settings = load_settings()
        self._bridge = GuiBridge(self)
        self._build()
        self._restore()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        login_box = QGroupBox("登录")
        login_layout = QVBoxLayout(login_box)
        self.login_form = LoginForm()
        self.login_form.login_requested.connect(self._on_login)
        login_layout.addWidget(self.login_form)
        layout.addWidget(login_box)

        publish_box = QGroupBox("发布")
        form = QFormLayout(publish_box)
        self.root_edit = QLineEdit()
        self.root_edit.setReadOnly(True)
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._choose_root)
        row = QHBoxLayout()
        row.addWidget(self.root_edit)
        row.addWidget(browse)
        form.addRow("共享文件夹", _wrap(row))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("留空则用文件夹名")
        form.addRow("共享名称", self.name_edit)
        layout.addWidget(publish_box)

        self.publish_btn = QPushButton("发布")
        self.publish_btn.setEnabled(False)
        self.publish_btn.clicked.connect(self._toggle_publish)
        layout.addWidget(self.publish_btn)
        self.status_label = QLabel("未发布")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("已连接的接收方："))
        self.peers = QListWidget()
        layout.addWidget(self.peers)

        layout.addWidget(QLabel("当前在线账号："))
        self.accounts = QListWidget()
        layout.addWidget(self.accounts)

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
        self.root_edit.setText(str(self._settings.value("publish/root", "") or ""))
        self.name_edit.setText(str(self._settings.value("publish/name", "") or ""))
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
        self._settings.setValue("publish/root", self.root_edit.text())
        self._settings.setValue("publish/name", self.name_edit.text().strip())

    def _choose_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择要共享的文件夹")
        if path:
            self.root_edit.setText(path)
            self._settings.setValue("publish/root", path)

    # -- login --------------------------------------------------------------
    def _on_login(self) -> None:
        values = self.login_form.values()
        if not values["user"]:
            QMessageBox.warning(self, "提示", "请输入账号")
            return
        self._save_settings()
        self.login_form.set_busy(True)
        self.service = PublisherService(
            signal_host=values["host"],
            signal_port=values["port"],
            account=values["user"],
            password=values["password"],
            tls=values["tls"],
            ice_servers=self._ice(),
        )
        self.runner.submit(self._do_login(values))

    def _ice(self) -> list:
        return build_ice_servers(
            turn_url=self.turn_edit.text().strip() or None,
            turn_user=self.turn_user_edit.text().strip() or None,
            turn_pass=self.turn_pass_edit.text() or None,
        )

    async def _do_login(self, values: dict) -> None:
        try:
            await self.service.connect_and_login()
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
        self.publish_btn.setEnabled(True)
        self._watch_future = self.runner.submit(self._watch())

    # -- publish ------------------------------------------------------------
    def _toggle_publish(self) -> None:
        if self._publishing:
            self.publish_btn.setEnabled(False)
            self.runner.submit(self._do_stop())
            return
        root = self.root_edit.text()
        if not root:
            QMessageBox.warning(self, "提示", "请先选择要共享的文件夹")
            return
        name = self.name_edit.text().strip()
        self.publish_btn.setEnabled(False)
        self.publish_btn.setText("发布中...")
        self.runner.submit(self._do_publish(root, name))

    async def _do_publish(self, root: str, name: str) -> None:
        try:
            share_id = await self.service.publish(root, name)
        except Exception as exc:  # noqa: BLE001
            self._bridge.post(lambda m=exc_text(exc): self._on_publish_failed(m))
            return
        self._bridge.post(lambda: self._on_published(share_id))

    def _on_published(self, share_id: str) -> None:
        self._publishing = True
        self.publish_btn.setText("停止发布")
        self.publish_btn.setEnabled(True)
        self.status_label.setText(f"已发布：{self.service.share_name} ({share_id})")
        self._settings.setValue("publish/name", self.service.share_name)
        self._set_traffic({})

    def _on_publish_failed(self, message: str) -> None:
        self.publish_btn.setText("发布")
        self.publish_btn.setEnabled(True)
        QMessageBox.critical(self, "发布失败", message)

    async def _do_stop(self) -> None:
        try:
            await self.service.unpublish()
        finally:
            self._bridge.post(self._on_stopped)

    def _on_stopped(self) -> None:
        self._publishing = False
        self.publish_btn.setText("发布")
        self.publish_btn.setEnabled(True)
        self.status_label.setText("未发布")
        self.peers.clear()
        self._set_traffic({})

    # -- events -------------------------------------------------------------
    async def _watch(self) -> None:
        try:
            while self.service is not None:
                kind, payload = await self.service.next_event()
                if kind == "joined":
                    self._bridge.post(lambda pid=payload: self.peers.addItem(pid))
                elif kind == "left":
                    self._bridge.post(lambda pid=payload: self._remove(self.peers, pid))
                elif kind == "presence":
                    self._bridge.post(lambda items=payload: self._set_accounts(items))
                elif kind == "traffic":
                    self._bridge.post(lambda snap=payload: self._set_traffic(snap))
        except asyncio.CancelledError:
            pass

    def _set_traffic(self, snapshot: dict) -> None:
        totals = snapshot.get("totals", {})
        self.direct_label.setText(fmt_size(totals.get("direct", 0)))
        self.relay_label.setText(fmt_size(totals.get("relay", 0)))
        self.unknown_label.setText(fmt_size(totals.get("unknown", 0)))

    def _remove(self, widget: QListWidget, text: str) -> None:
        for index in range(widget.count()):
            if widget.item(index).text() == text:
                widget.takeItem(index)
                return

    def _set_accounts(self, accounts: list) -> None:
        self.accounts.clear()
        for name in accounts:
            self.accounts.addItem(name)

    def shutdown(self) -> None:
        self._save_settings()
        if self._watch_future:
            self._watch_future.cancel()
            self._watch_future = None
        if self.service:
            self.runner.submit(self.service.close())
            self.service = None


def _wrap(layout) -> QWidget:
    box = QWidget()
    box.setLayout(layout)
    return box
