from __future__ import annotations

import json
import logging
from typing import Any
from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from autolingua2.services.ai_providers.base import AiProviderPlugin, BaseHttpTranslator

logger = logging.getLogger(__name__)


class AiNetworkClient(QObject):
    """QtNetwork (QNetworkAccessManager) を用いた完全非同期AI通信クライアント。

    UIメインスレッドを1ミリ秒もブロックすることなく、複数モデルの並行検証や
    テキスト翻訳をノンブロッキングで実行します。
    """

    model_validated = Signal(str, bool, str)  # (model_name, is_valid, message)
    all_validated = Signal(int, int)          # (success_count, error_count)
    translation_completed = Signal(str, str)  # (request_id, translated_text)
    translation_failed = Signal(str, str)     # (request_id, error_message)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._active_replies: list[QNetworkReply] = []
        self._validation_remaining = 0
        self._validation_success = 0
        self._validation_error = 0

    def cancel_all(self) -> None:
        """実行中のすべての非同期リクエストを即座に切断・中断します。"""
        for reply in self._active_replies:
            if reply.isRunning():
                reply.abort()
                reply.deleteLater()
        self._active_replies.clear()
        self._validation_remaining = 0

    def validate_models(
        self,
        provider: AiProviderPlugin,
        api_key: str,
        models: list[str],
        timeout_sec: float = 8.0,
    ) -> None:
        """指定されたプロバイダとモデル群の有効性を並行・非同期で検証します。"""
        self.cancel_all()

        target_models = [m.strip() for m in models if m.strip()]
        if not target_models:
            self.all_validated.emit(0, 0)
            return

        self._validation_remaining = len(target_models)
        self._validation_success = 0
        self._validation_error = 0

        for model in target_models:
            try:
                raw_translator = provider.create(api_key, model)
                if not isinstance(raw_translator, BaseHttpTranslator):
                    self._on_single_validation_finished(
                        model, False, f"未対応のプロバイダ型です: {type(raw_translator)}"
                    )
                    continue

                translator: BaseHttpTranslator = raw_translator
                system_prompt = translator.build_system_prompt("en", "ja")
                payload = translator.build_payload("test", "en", "ja", system_prompt)
                headers = translator.build_headers()

                body_bytes = json.dumps(payload).encode("utf-8")
                request = QNetworkRequest(QUrl(translator.endpoint))

                for key, val in headers.items():
                    request.setRawHeader(key.encode("utf-8"), val.encode("utf-8"))

                request.setTransferTimeout(int(timeout_sec * 1000))
                reply = self._nam.post(request, QByteArray(body_bytes))
                self._active_replies.append(reply)

                reply.finished.connect(
                    lambda r=reply, m=model, t=translator: self._handle_validation_reply(r, m, t)
                )
            except Exception as exc:
                logger.warning("モデル検証リクエスト生成失敗 (%s): %s", model, exc)
                self._on_single_validation_finished(model, False, f"リクエスト生成失敗: {exc}")

    def _handle_validation_reply(
        self,
        reply: QNetworkReply,
        model: str,
        translator: BaseHttpTranslator,
    ) -> None:
        if reply in self._active_replies:
            self._active_replies.remove(reply)

        reply.deleteLater()
        status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        http_status = int(status_code) if status_code is not None else 0

        raw_bytes = bytes(reply.readAll().data())
        raw_text = raw_bytes.decode("utf-8", errors="replace")

        if reply.error() == QNetworkReply.NetworkError.NoError and 200 <= http_status < 300:
            try:
                data = json.loads(raw_text)
                _ = translator.extract_translation(data)
                self._on_single_validation_finished(model, True, "接続確認済み（利用可能）")
            except Exception as exc:
                self._on_single_validation_finished(model, False, f"レスポンス解析失敗: {exc}")
        else:
            error_message = translator._resolve_http_error(raw_text, http_status)
            if not error_message or error_message == raw_text:
                error_message = reply.errorString()
            self._on_single_validation_finished(model, False, f"接続エラー: {error_message}")

    def _on_single_validation_finished(self, model: str, is_valid: bool, message: str) -> None:
        if is_valid:
            self._validation_success += 1
        else:
            self._validation_error += 1

        self.model_validated.emit(model, is_valid, message)

        self._validation_remaining -= 1
        if self._validation_remaining <= 0:
            self._validation_remaining = 0
            self.all_validated.emit(self._validation_success, self._validation_error)
