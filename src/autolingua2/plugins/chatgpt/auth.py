from __future__ import annotations

import base64
from collections.abc import Callable
import hmac
import hashlib
import json
import logging
import secrets
import time
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from PySide6.QtCore import QByteArray, QCoreApplication, QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtNetworkAuth import QOAuthHttpServerReplyHandler

from autolingua2.plugins.api import PluginSettings

logger = logging.getLogger(__name__)

ISSUER = "https://auth.openai.com"
DISCOVERY_URL = ISSUER + "/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REGISTRATION_CLIENT_ID = "dynamic_agent_client"


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _verified_identity(token: str, jwks: dict[str, Any], client_id: str, nonce: str | None) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("IDトークンの形式が不正です。")
    header = json.loads(_decode_base64(parts[0]))
    claims = json.loads(_decode_base64(parts[1]))
    if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "RS256":
        raise ValueError("IDトークンの署名形式が不正です。")
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise ValueError("認証サーバーの署名鍵を取得できません。")
    key = next((item for item in keys if isinstance(item, dict)
                and item.get("kid") == header.get("kid") and item.get("kty") == "RSA"), None)
    if key is None:
        raise ValueError("IDトークンに対応する署名鍵がありません。")
    modulus, exponent = _text(key, "n"), _text(key, "e")
    if not modulus or not exponent:
        raise ValueError("認証サーバーの署名鍵が不正です。")
    public_key = rsa.RSAPublicNumbers(
        int.from_bytes(_decode_base64(exponent), "big"),
        int.from_bytes(_decode_base64(modulus), "big"),
    ).public_key()
    public_key.verify(_decode_base64(parts[2]), f"{parts[0]}.{parts[1]}".encode("ascii"),
                      padding.PKCS1v15(), hashes.SHA256())
    audience = claims.get("aud")
    if not (audience == client_id or isinstance(audience, list) and client_id in audience):
        raise ValueError("IDトークンの認証先が一致しません。")
    expiry = claims.get("exp")
    if (claims.get("iss") != ISSUER or not isinstance(expiry, (int, float))
            or isinstance(expiry, bool) or expiry <= time.time() or not _text(claims, "sub")):
        raise ValueError("IDトークンの発行元・有効期限・アカウントが不正です。")
    if nonce is not None and claims.get("nonce") != nonce:
        raise ValueError("IDトークンの認証要求が一致しません。")
    if "azp" in claims and claims["azp"] != client_id:
        raise ValueError("IDトークンのクライアントが一致しません。")
    return claims


class ChatGptAuthManager(QObject):
    """Plugin-owned OAuth registration, verified identity, renewal and sign-out."""

    auth_succeeded = Signal(str, str)
    auth_failed = Signal(str)
    auth_status_changed = Signal(str)

    def __init__(self, settings: PluginSettings) -> None:
        super().__init__()
        self._settings = settings
        stored = settings.load()
        host_id = stored.get("host_id")
        self._host_id = host_id if isinstance(host_id, str) and host_id else f"urn:uuid:{uuid4()}"
        credentials = stored.get("oauth")
        self._credentials: dict[str, Any] = dict(credentials) if isinstance(credentials, dict) else {}
        self._access_token = ""
        self._user_email = _text(self._credentials, "email")
        self._metadata: dict[str, Any] = {}
        self._reply_handler: QOAuthHttpServerReplyHandler | None = None
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._operation: Literal["signin", "refresh", "signout"] | None = None
        self._pending_client_id = ""
        self._nonce = ""
        self._pkce_verifier = ""
        self._state = ""
        self._redirect_uri = ""
        self._callback_consumed = False
        self._tokens: dict[str, Any] = {}
        self._revocation: tuple[str, str] | None = None
        self._renewal = QTimer(self)
        self._renewal.setSingleShot(True)
        self._renewal.timeout.connect(self._refresh)
        self._persist()
        expiry = self._credentials.get("expires_at", 0)
        if isinstance(expiry, (int, float)) and expiry > time.time():
            self._access_token = _text(self._credentials, "access_token")
            self._schedule_renewal()
        elif _text(self._credentials, "refresh_token"):
            QTimer.singleShot(0, self._refresh)

    @property
    def access_token(self) -> str:
        return self._access_token if self.is_authenticated else ""

    @property
    def user_email(self) -> str:
        return self._user_email

    @property
    def is_authenticated(self) -> bool:
        expiry = self._credentials.get("expires_at", 0)
        return bool(self._access_token and isinstance(expiry, (int, float)) and expiry > time.time())

    def _persist(self) -> None:
        self._settings.save({**self._settings.load(), "host_id": self._host_id, "oauth": self._credentials})

    def _request(self, url: str, callback: Callable[[dict[str, Any]], None],
                 form: dict[str, str] | None = None) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(15000)
        if form is None:
            reply = self._network.get(request)
        else:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/x-www-form-urlencoded")
            reply = self._network.post(request, QByteArray(urlencode(form).encode("ascii")))
        self._reply = reply
        reply.finished.connect(lambda: self._request_finished(reply, callback))

    def _request_finished(self, reply: QNetworkReply, callback: Callable[[dict[str, Any]], None]) -> None:
        if reply is not self._reply:
            return
        self._reply = None
        try:
            body = bytes(reply.readAll().data())
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() != QNetworkReply.NetworkError.NoError or not isinstance(status, int) or not 200 <= status < 300:
                error_code = ""
                try:
                    error_data = json.loads(body)
                    if isinstance(error_data, dict):
                        error = error_data.get("error")
                        error_code = error if isinstance(error, str) else _text(error, "code") if isinstance(error, dict) else ""
                except (ValueError, UnicodeDecodeError):
                    pass
                detail = f"HTTP {status}" if isinstance(status, int) else reply.errorString()
                if error_code:
                    detail += f" ({error_code})"
                raise ValueError(f"認証サーバーへの要求に失敗しました: {detail}")
            data = json.loads(body) if body else {}
            if not isinstance(data, dict):
                raise ValueError("認証サーバーの応答形式が不正です。")
            callback(data)
        except Exception as error:
            self._fail(str(error) or "認証情報の検証に失敗しました。")
        finally:
            reply.deleteLater()

    def _discovered(self, data: dict[str, Any]) -> None:
        if data.get("issuer") != ISSUER:
            raise ValueError("認証サーバーの発行元が一致しません。")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "revocation_endpoint"):
            url = QUrl(_text(data, key))
            if url.scheme() != "https" or url.host() != "auth.openai.com":
                raise ValueError("認証サーバーの接続先が不正です。")
        self._metadata = data
        if self._operation == "signin":
            self._authorize()
        elif self._operation == "refresh":
            self._request(_text(data, "token_endpoint"), self._tokens_received, {
                "grant_type": "refresh_token",
                "client_id": self._pending_client_id,
                "refresh_token": _text(self._credentials, "refresh_token"),
                "resource": RESOURCE,
            })
        elif self._operation == "signout" and self._revocation is not None:
            client_id, refresh_token = self._revocation
            self._request(_text(data, "revocation_endpoint"), self._revoked, {
                "client_id": client_id, "token": refresh_token, "token_type_hint": "refresh_token",
            })

    def start_sign_in(self) -> None:
        self._cancel_pending()
        self._renewal.stop()
        self._operation = "signin"
        self._pending_client_id = (_text(self._credentials, "client_id")
                                   or self._pending_client_id or REGISTRATION_CLIENT_ID)
        self._nonce = secrets.token_urlsafe(32)
        self._pkce_verifier = secrets.token_urlsafe(32)
        self._state = secrets.token_urlsafe(32)
        self._callback_consumed = False
        self.auth_status_changed.emit("ログインの準備中...")
        self._request(DISCOVERY_URL, self._discovered)

    def _authorize(self) -> None:
        handler = QOAuthHttpServerReplyHandler(QHostAddress.SpecialAddress.LocalHost, 0, self)
        handler.setCallbackHost("127.0.0.1")
        handler.setCallbackPath("/auth/callback")
        if not handler.isListening():
            handler.deleteLater()
            raise ValueError("ログイン応答を受け取るポートを開けません。")
        self._reply_handler = handler
        handler.callbackReceived.connect(self._callback_received)
        self._redirect_uri = handler.callback()
        digest = hashlib.sha256(self._pkce_verifier.encode("ascii")).digest()
        parameters = {
            "client_id": self._pending_client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": SCOPE,
            "resource": RESOURCE,
            "state": self._state,
            "nonce": self._nonce,
            "code_challenge": base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"),
            "code_challenge_method": "S256",
            "ext_agent_host_id": self._host_id,
        }
        if self._pending_client_id == REGISTRATION_CLIENT_ID:
            application_name = QCoreApplication.applicationName()
            if not application_name.strip():
                raise ValueError("アプリケーション名が設定されていません。")
            parameters["agent_name_hint"] = application_name
        else:
            id_token = _text(self._credentials, "id_token")
            if id_token:
                parameters["id_token_hint"] = id_token
        url = QUrl(_text(self._metadata, "authorization_endpoint"))
        query = QUrlQuery()
        for key, value in parameters.items():
            query.addQueryItem(key, value)
        url.setQuery(query)
        self._open_browser(url)

    def _open_browser(self, url: QUrl) -> None:
        query = QUrlQuery(url)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(self._pkce_verifier.encode("ascii")).digest(),
        ).rstrip(b"=").decode("ascii")
        if (not self._pkce_verifier or query.queryItemValue("code_challenge") != expected
                or query.queryItemValue("code_challenge_method") != "S256"):
            self._fail("ログイン要求のPKCE検証値が不正です。")
            return
        self.auth_status_changed.emit("ブラウザで認証待機中...")
        if not QDesktopServices.openUrl(url):
            self._fail("ログイン用のブラウザを開けません。")

    def _callback_received(self, data: dict[str, Any]) -> None:
        if self._reply_handler is None or self._operation != "signin" or self._callback_consumed:
            return
        state = _text(data, "state")
        if not state or not hmac.compare_digest(state, self._state):
            self._fail("ログイン応答の認証要求が一致しません。")
            return
        if data.get("error"):
            self._fail("ログインがキャンセルされたか、利用許可が拒否されました。")
            return
        issued_client_id = _text(data, "client_id")
        if self._pending_client_id == REGISTRATION_CLIENT_ID:
            if not issued_client_id or issued_client_id == REGISTRATION_CLIENT_ID:
                self._fail("アプリのクライアント登録が完了していません。")
                return
            self._pending_client_id = issued_client_id
        elif issued_client_id and issued_client_id != self._pending_client_id:
            self._fail("ログイン応答のクライアントが一致しません。")
            return
        code = _text(data, "code")
        if not code:
            self._fail("ログイン応答に認証コードがありません。")
            return
        self._callback_consumed = True
        self.auth_status_changed.emit("認証情報を確認中...")
        try:
            self._request(_text(self._metadata, "token_endpoint"), self._tokens_received, {
                "grant_type": "authorization_code",
                "client_id": self._pending_client_id,
                "code": code,
                "code_verifier": self._pkce_verifier,
                "redirect_uri": self._redirect_uri,
                "resource": RESOURCE,
            })
        except Exception as error:
            self._fail(str(error) or "認証情報の取得に失敗しました。")

    def _tokens_received(self, data: dict[str, Any]) -> None:
        self._tokens = dict(data)
        if not _text(data, "access_token"):
            raise ValueError("アクセストークンを取得できません。")
        self._request(_text(self._metadata, "jwks_uri"), self._accept_tokens)

    def _accept_tokens(self, jwks: dict[str, Any]) -> None:
        tokens = self._tokens
        id_token = _text(tokens, "id_token")
        if id_token:
            claims = _verified_identity(id_token, jwks, self._pending_client_id,
                                        self._nonce if self._operation == "signin" else None)
            subject = _text(claims, "sub")
            email = _text(claims, "email")
            previous_client = _text(self._credentials, "client_id")
            if (previous_client == self._pending_client_id and _text(self._credentials, "subject")
                    and subject != _text(self._credentials, "subject")):
                raise ValueError("登録済みのChatGPTアカウントと一致しません。")
        elif self._operation == "refresh" and _text(self._credentials, "subject"):
            subject = _text(self._credentials, "subject")
            email = _text(self._credentials, "email")
            id_token = _text(self._credentials, "id_token")
        else:
            raise ValueError("アカウント確認用のIDトークンを取得できません。")
        scope = tokens.get("scope")
        scopes = scope.split() if isinstance(scope, str) else self._credentials.get("scopes", [])
        if not isinstance(scopes, list) or "chatgpt.tokens.use.direct" not in scopes:
            raise ValueError("ChatGPTプランを利用する権限が許可されていません。")
        expires = tokens.get("expires_in")
        if not isinstance(expires, (int, float)) or isinstance(expires, bool) or expires <= 0:
            raise ValueError("アクセストークンの有効期限が不正です。")
        self._credentials = {
            "client_id": self._pending_client_id, "subject": subject, "email": email,
            "id_token": id_token, "access_token": _text(tokens, "access_token"),
            "refresh_token": _text(tokens, "refresh_token") or _text(self._credentials, "refresh_token"),
            "scopes": scopes, "expires_at": time.time() + expires,
        }
        self._persist()
        self._access_token = _text(self._credentials, "access_token")
        self._user_email = email
        self._operation = None
        self._dispose_callback()
        self._schedule_renewal()
        self.auth_status_changed.emit("ログイン中")
        self.auth_succeeded.emit(self._access_token, email)

    def _schedule_renewal(self) -> None:
        expiry = self._credentials.get("expires_at")
        if isinstance(expiry, (int, float)) and _text(self._credentials, "refresh_token"):
            self._renewal.start(min(2147483647, max(1000, int((expiry - time.time() - 60) * 1000))))

    def _refresh(self) -> None:
        if self._operation is not None or not _text(self._credentials, "refresh_token"):
            return
        self._operation = "refresh"
        self._pending_client_id = _text(self._credentials, "client_id")
        if not self._pending_client_id or self._pending_client_id == REGISTRATION_CLIENT_ID:
            self._fail("保存済みのクライアント登録が不正です。再ログインしてください。")
            return
        self._request(DISCOVERY_URL, self._discovered)

    def sign_out(self) -> None:
        self._cancel_pending()
        self._renewal.stop()
        client_id = _text(self._credentials, "client_id")
        refresh_token = _text(self._credentials, "refresh_token")
        self._credentials = {key: self._credentials[key] for key in ("client_id", "subject", "email")
                             if key in self._credentials}
        self._access_token = ""
        self._persist()
        self.auth_status_changed.emit("未ログイン")
        if client_id and refresh_token:
            self._revocation = (client_id, refresh_token)
            self._operation = "signout"
            self._request(DISCOVERY_URL, self._discovered)

    def _revoked(self, data: dict[str, Any]) -> None:
        self._revocation = None
        self._operation = None

    def _dispose_callback(self) -> None:
        self._pkce_verifier = ""
        self._state = ""
        self._redirect_uri = ""
        if self._reply_handler is not None:
            self._reply_handler.close()
            self._reply_handler.deleteLater()
            self._reply_handler = None

    def _cancel_pending(self) -> None:
        if self._reply is not None:
            reply = self._reply
            self._reply = None
            reply.abort()
            reply.deleteLater()
        self._dispose_callback()
        self._operation = None
        self._tokens = {}

    def cancel_sign_in(self) -> None:
        if self._operation == "signin":
            self._cancel_pending()
            self._schedule_renewal()

    def close(self) -> None:
        self._renewal.stop()
        self._cancel_pending()
        self.deleteLater()

    def _fail(self, message: str) -> None:
        operation = self._operation
        self._cancel_pending()
        if operation == "refresh":
            self._access_token = ""
        else:
            self._schedule_renewal()
        logger.warning("ChatGPT認証: %s", message)
        self.auth_status_changed.emit("認証エラー")
        self.auth_failed.emit(message)
