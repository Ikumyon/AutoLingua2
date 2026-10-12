from __future__ import annotations

import logging
from typing import Callable
from PySide6.QtCore import QObject
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QSpacerItem, QWidget,
)

from autolingua2.plugins.api import AiModel, AiSetupCallbacks, AiSetupPanel, AiSetupValues
from .auth import ChatGptAuthManager
from .chatgpt import ChatGptModelFetcher, ChatGptProvider

logger = logging.getLogger(__name__)


class ChatGptSetupPanel(QObject):
    """初期設定ウィザード（AiSetupPanel プロトコル）用の ChatGPT 認証＆モデル管理パネル。"""

    def __init__(
        self,
        parent: QWidget,
        initial: AiSetupValues,
        callbacks: AiSetupCallbacks,
    ) -> None:
        super().__init__(parent)
        self._callbacks = callbacks
        self._auth = ChatGptAuthManager(self)
        self._fetcher = ChatGptModelFetcher(self)
        self._models: list[AiModel] = list(initial.models)

        # UI ウィジェットの構築
        self._widget = QWidget(parent)
        layout = QHBoxLayout(self._widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_signin = QPushButton("ChatGPT でサインイン", self._widget)
        self.btn_signin.clicked.connect(self._start_signin)
        layout.addWidget(self.btn_signin)

        self.lbl_status = QLabel("未ログイン", self._widget)
        layout.addWidget(self.lbl_status)

        self.btn_signout = QPushButton("ログアウト", self._widget)
        self.btn_signout.clicked.connect(self._sign_out)
        layout.addWidget(self.btn_signout)

        self.btn_refresh = QPushButton("モデル再取得", self._widget)
        self.btn_refresh.clicked.connect(self._fetch_models)
        layout.addWidget(self.btn_refresh)

        spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addItem(spacer)

        # シグナル接続
        self._auth.auth_succeeded.connect(self._on_auth_succeeded)
        self._auth.auth_failed.connect(self._on_auth_failed)
        self._auth.auth_status_changed.connect(self._on_auth_status)
        self._fetcher.models_fetched.connect(self._on_models_fetched)
        self._fetcher.fetch_failed.connect(self._on_fetch_failed)

        if initial.api_key:
            self._auth.set_token(initial.api_key)
        self._update_display()

    @property
    def widget(self) -> QWidget:
        return self._widget

    @property
    def ready(self) -> bool:
        return self._auth.is_authenticated

    def read_settings(self) -> AiSetupValues:
        return AiSetupValues(
            api_key=self._auth.access_token,
            models=tuple(self._models),
        )

    def save_settings(self) -> None:
        pass

    def cancel(self) -> None:
        self._auth.cancel()
        self._fetcher.cancel()
        self._update_display()

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
        self.btn_refresh.setVisible(is_logged_in)

    def _start_signin(self) -> None:
        self.btn_signin.setEnabled(False)
        self._auth.start_sign_in()

    def _sign_out(self) -> None:
        self._auth.sign_out()
        self._fetcher.cancel()
        self._update_display()
        self._callbacks.changed()
        self._callbacks.ready_changed(False)

    def _fetch_models(self) -> None:
        if not self._auth.access_token:
            return
        self.lbl_status.setText("モデル一覧を取得中...")
        self.btn_refresh.setEnabled(False)
        self._fetcher.fetch_models(self._auth.access_token)

    def _on_auth_succeeded(self, token: str, email: str) -> None:
        self._update_display()
        self.lbl_status.setText(f"✅ ログイン中 ({email}) - モデル取得中..." if email else "✅ ログイン中 - モデル取得中...")
        self._fetch_models()

    def _on_auth_failed(self, error_msg: str) -> None:
        self._update_display()
        self._callbacks.changed()
        self._callbacks.ready_changed(False)
        QMessageBox.warning(self._widget, "ChatGPT サインイン", error_msg)

    def _on_auth_status(self, status_text: str) -> None:
        self.lbl_status.setText(status_text)

    def _on_models_fetched(self, models: list[tuple[str, str]]) -> None:
        self.btn_refresh.setEnabled(True)
        self._update_display()
        if models:
            self._models = [AiModel(name=name, model=slug, enabled=True) for name, slug in models]
        self._callbacks.changed()
        self._callbacks.ready_changed(self.ready)

    def _on_fetch_failed(self, error_msg: str) -> None:
        self.btn_refresh.setEnabled(True)
        self._update_display()
        logger.warning("ChatGPT モデル自動取得失敗: %s", error_msg)
        if not self._models:
            self._models = [
                AiModel(name=name, model=slug, enabled=True)
                for name, slug in ChatGptProvider.default_models
            ]
        self._callbacks.changed()
        self._callbacks.ready_changed(self.ready)


class ChatGptSettingsWidget(QWidget):
    """本体設定ダイアログ用の ChatGPT 設定ウィジェット。"""

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

        self._update_display()

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

