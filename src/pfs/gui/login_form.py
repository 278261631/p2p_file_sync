"""Reusable account login form (server + credentials)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ..common.config import DEFAULT_SIGNAL_HOST, DEFAULT_SIGNAL_PORT


class LoginForm(QWidget):
    login_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)

        self.host_edit = QLineEdit(DEFAULT_SIGNAL_HOST)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_SIGNAL_PORT)
        self.tls_check = QCheckBox("使用 wss（互联网必须开启）")
        self.user_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.login_btn = QPushButton("登录")
        self.login_btn.clicked.connect(self.login_requested.emit)
        self.status = QLabel("未登录")

        form.addRow("服务器", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("", self.tls_check)
        form.addRow("账号", self.user_edit)
        form.addRow("密码", self.password_edit)
        form.addRow("", self.login_btn)
        form.addRow("状态", self.status)

    def values(self) -> dict:
        return {
            "host": self.host_edit.text().strip() or DEFAULT_SIGNAL_HOST,
            "port": self.port_spin.value(),
            "tls": self.tls_check.isChecked(),
            "user": self.user_edit.text().strip(),
            "password": self.password_edit.text(),
        }

    def set_busy(self, busy: bool) -> None:
        self.login_btn.setEnabled(not busy)
        self.login_btn.setText("登录中..." if busy else "登录")

    def set_logged_in(self, account: str | None) -> None:
        logged = account is not None
        for widget in (self.host_edit, self.port_spin, self.tls_check, self.user_edit, self.password_edit):
            widget.setEnabled(not logged)
        self.login_btn.setText("已登录" if logged else "登录")
        self.login_btn.setEnabled(not logged)
        self.status.setText(f"已登录：{account}" if logged else "未登录")
