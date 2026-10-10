from __future__ import annotations

import base64
import json
import logging
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetworkAuth import (
    QOAuth2AuthorizationCodeFlow,
    QOAuthHttpServerReplyHandler,
)

logger = logging.getLogger(__name__)

# ChatGPT 固有の OAuth 2.0 PKCE 設定
AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
SCOPE = "openid profile email offline_access"
CLIENT_ID = "autolingua-desktop"


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """JWTトークンのペイロード部分を簡易デコードする。"""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    rem = len(payload_b64) % 4
    if rem:
        payload_b64 += "=" * (4 - rem)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        result = json.loads(decoded)
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        logger.debug("JWTデコード失敗: %s", exc)
        return {}


class ChatGptAuthManager(QObject):
    """ChatGPT プラグイン内部で自己完結する OAuth 2.0 PKCE 認証管理。"""

    auth_succeeded = Signal(str, str)  # (access_token, user_email)
    auth_failed = Signal(str)          # (error_message)
    auth_status_changed = Signal(str)  # (status_message)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._oauth: QOAuth2AuthorizationCodeFlow | None = None
        self._reply_handler: QOAuthHttpServerReplyHandler | None = None
        self._access_token: str = ""
        self._user_email: str = ""

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def user_email(self) -> str:
        return self._user_email

    @property
    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def set_token(self, token: str) -> None:
        self._access_token = token.strip()
        if self._access_token:
            payload = decode_jwt_payload(self._access_token)
            self._user_email = str(payload.get("email") or payload.get("sub") or "")
        else:
            self._user_email = ""

    def start_sign_in(self) -> None:
        self.auth_status_changed.emit("ブラウザで認証待機中...")

        self._reply_handler = QOAuthHttpServerReplyHandler(self)
        self._oauth = QOAuth2AuthorizationCodeFlow(self)
        self._oauth.setReplyHandler(self._reply_handler)

        self._oauth.setAuthorizationUrl(QUrl(AUTH_URL))
        self._oauth.setAccessTokenUrl(QUrl(TOKEN_URL))
        self._oauth.setClientIdentifier(CLIENT_ID)
        self._oauth.setScope(SCOPE)
        self._oauth.setPkceMethod(QOAuth2AuthorizationCodeFlow.PkceMethod.S256)

        self._oauth.authorizeWithBrowser.connect(QDesktopServices.openUrl)
        self._oauth.granted.connect(self._on_granted)
        self._oauth.requestFailed.connect(self._on_request_failed)

        self._oauth.grant()

    def sign_out(self) -> None:
        self._access_token = ""
        self._user_email = ""
        if self._oauth is not None:
            self._oauth.setToken("")
        self.auth_status_changed.emit("未ログイン")

    def _on_granted(self) -> None:
        if self._oauth is None:
            return
        token = self._oauth.token()
        self._access_token = token
        id_token = getattr(self._oauth, "idToken", lambda: "")()
        target_jwt = id_token if id_token else token
        payload = decode_jwt_payload(target_jwt)
        self._user_email = str(payload.get("email") or payload.get("sub") or "")

        self.auth_status_changed.emit("✅ ログイン中")
        self.auth_succeeded.emit(self._access_token, self._user_email)

    def _on_request_failed(self, error: Any) -> None:
        msg = f"ChatGPT 認証失敗: {error}"
        logger.warning(msg)
        self.auth_status_changed.emit("認証エラー")
        self.auth_failed.emit(msg)
