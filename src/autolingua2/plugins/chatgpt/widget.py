from __future__ import annotations

from typing import Callable
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpacerItem,
    QSizePolicy, QWidget,
)

from .auth import ChatGptAuthManager


class ChatGptSettingsWidget(QWidget):
    """ChatGPT プラグイン固有の設定画面ウィジェット（4F UI）。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        token: str = "",
        on_token_changed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_token_changed = on_token_changed
        self._auth = ChatGptAuthManager(self)
        self._auth.set_token(token)

        self._auth.auth_succeeded.connect(self._on_auth_succeeded)
        self._auth.auth_failed.connect(self._on_auth_failed)
        self._auth.auth_status_changed.connect(self._on_status_changed)

        self._setup_ui()
        self._update_display()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_signin = QPushButton("ChatGPT でサインイン", self)
        self.btn_signin.clicked.connect(self._start_signin)
        layout.addWidget(self.btn_signin)

        self.lbl_status = QLabel("未ログイン", self)
        layout.addWidget(self.lbl_status)

        self.btn_signout = QPushButton("ログアウト", self)
        self.btn_signout.clicked.connect(self._sign_out)
        layout.addWidget(self.btn_signout)

        spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addItem(spacer)

    def _update_display(self) -> None:
        is_logged_in = self._auth.is_authenticated
        if is_logged_in:
            email = self._auth.user_email
            self.lbl_status.setText(f"✅ ログイン中 ({email})" if email else "✅ ログイン中")
        else:
            self.lbl_status.setText("未ログイン")

        self.btn_signin.setVisible(not is_logged_in)
        self.btn_signin.setEnabled(True)
        self.btn_signout.setVisible(is_logged_in)

    def _start_signin(self) -> None:
        self.btn_signin.setEnabled(False)
        self._auth.start_sign_in()

    def _sign_out(self) -> None:
        self._auth.sign_out()
        self._update_display()
        if self._on_token_changed is not None:
            self._on_token_changed("")

    def _on_auth_succeeded(self, token: str, email: str) -> None:
        self._update_display()
        if self._on_token_changed is not None:
            self._on_token_changed(token)
        msg = f"ChatGPT に正常にサインインしました。\n{email}" if email else "ChatGPT に正常にサインインしました。"
        QMessageBox.information(self, "ChatGPT サインイン", msg)

    def _on_auth_failed(self, error_msg: str) -> None:
        self._update_display()
        QMessageBox.warning(self, "ChatGPT サインイン", error_msg)

    def _on_status_changed(self, status_text: str) -> None:
        self.lbl_status.setText(status_text)
