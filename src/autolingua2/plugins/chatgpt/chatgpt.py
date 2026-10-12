from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from autolingua2.plugins.contracts import (
    BaseAiProvider, BaseHttpTranslator, ChatMessage, ChatReply, ChatToolCall,
    object_value, string_value,
)

logger = logging.getLogger(__name__)


class ChatGptTranslator(BaseHttpTranslator):
    """Sign in with ChatGPT 連携用トランスレーター（Responses API /v1/responses 準拠）。"""

    supports_chat = True

    @property
    def endpoint(self) -> str:
        return "https://api.openai.com/v1/responses"

    def build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Autolingua Desktop/0.1.0",
        }

    def build_payload(
        self,
        text: str,
        source_language: str,
        target_language: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "store": False,
        }

    def extract_translation(self, response_data: dict[str, Any]) -> str:
        # Responses API: output 配列のテキストを抽出
        outputs = response_data.get("output")
        if isinstance(outputs, list):
            texts = [
                str(item.get("text", "")).strip()
                for item in outputs
                if isinstance(item, dict) and item.get("text")
            ]
            if texts:
                return "\n".join(texts)

        # フォールバック (Chat Completions 形式も互換対応)
        choices = response_data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content.strip()

        raise ValueError("ChatGPT: 翻訳出力が見つかりませんでした。")

    def build_chat_payload(
        self, messages: list[ChatMessage], system_prompt: str,
        tools: list[dict[str, Any]], continuation: list[dict[str, Any]],
    ) -> dict[str, Any]:
        formatted_messages = (
            [{"role": "system", "content": system_prompt}]
            + [{"role": m.role, "content": m.content} for m in messages]
            + continuation
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "input": formatted_messages,
            "stream": False,
            "store": False,
        }
        if tools:
            payload["tools"] = [{
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            } for t in tools]
        return payload

    def extract_chat_reply(self, data: dict[str, Any]) -> ChatReply:
        outputs = data.get("output")
        if isinstance(outputs, list):
            texts: list[str] = []
            calls: list[ChatToolCall] = []
            for item in outputs:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type == "output_text" or "text" in item:
                    text_val = str(item.get("text", "")).strip()
                    if text_val:
                        texts.append(text_val)
                elif item_type == "function_call" or "function" in item:
                    fn = item.get("function", {})
                    fn_name = string_value(fn.get("name"), "name")
                    fn_args = object_value(json.loads(string_value(fn.get("arguments"), "arguments")), "arguments")
                    call_id = string_value(item.get("id", fn_name), "id")
                    calls.append(ChatToolCall(call_id, fn_name, fn_args))
            combined_text = "\n".join(texts)
            if combined_text or calls:
                return ChatReply(combined_text, calls, data)

        # フォールバック (Chat Completions 形式)
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice = object_value(choices[0], "choice")
            message = object_value(choice.get("message"), "message")
            calls = []
            for item in message.get("tool_calls", []):
                entry = object_value(item, "tool_call")
                function = object_value(entry.get("function"), "function")
                calls.append(ChatToolCall(
                    string_value(entry.get("id"), "id"), string_value(function.get("name"), "name"),
                    object_value(json.loads(string_value(function.get("arguments"), "arguments")), "arguments"),
                ))
            content = message.get("content")
            text = "" if content is None else string_value(content, "content")
            if text or calls:
                return ChatReply(text, calls, message)

        raise ValueError("ChatGPT: 有効な応答が得られませんでした。")

    def chat_tool_result(self, call: ChatToolCall, result: dict[str, Any]) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)}

    def extract_custom_error(self, error_data: dict[str, Any] | None, status_code: int) -> str | None:
        if isinstance(error_data, dict):
            err = error_data.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message", "")).strip()
                code = str(err.get("code", "")).strip()
                if status_code == 401:
                    return f"ChatGPT 認証トークンが無効または期限切れです ({msg})"
                if status_code == 404 or code == "model_not_found":
                    return f"指定されたモデル '{self.model}' が見つかりません ({msg})"
                if status_code == 429:
                    return f"ChatGPT 利用上限またはレート制限に達しました ({msg})"
                if msg:
                    return f"ChatGPT エラー ({status_code}): {msg}"
        return None


class ChatGptModelFetcher(QObject):
    """QtNetwork (QNetworkAccessManager) を用いた動的モデルカタログ取得クライアント。"""

    models_fetched = Signal(list)  # list[tuple[str, str]] (display_name, model_slug)
    fetch_failed = Signal(str)     # error_message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    def fetch_models(self, token: str, timeout_sec: float = 8.0) -> None:
        self.cancel()
        if not token.strip():
            self.fetch_failed.emit("認証トークンが空です。")
            return

        request = QNetworkRequest(QUrl("https://api.openai.com/v1/models"))
        request.setRawHeader(b"Authorization", f"Bearer {token.strip()}".encode("utf-8"))
        request.setRawHeader(b"User-Agent", b"Autolingua Desktop/0.1.0")
        request.setTransferTimeout(int(timeout_sec * 1000))

        reply = self._nam.get(request)
        self._reply = reply
        reply.finished.connect(lambda: self._on_finished(reply))

    def cancel(self) -> None:
        if self._reply is not None:
            if self._reply.isRunning():
                self._reply.abort()
            self._reply.deleteLater()
            self._reply = None

    def _on_finished(self, reply: QNetworkReply) -> None:
        if self._reply is not reply:
            return
        self._reply = None
        reply.deleteLater()

        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.fetch_failed.emit(f"モデル一覧の取得に失敗しました: {reply.errorString()}")
            return

        try:
            data = json.loads(bytes(reply.readAll().data()).decode("utf-8"))
            model_items = data.get("data", [])
            models: list[tuple[str, str]] = []
            for item in model_items:
                if not isinstance(item, dict):
                    continue
                visibility = item.get("visibility", "list")
                if visibility != "list":
                    continue
                slug = str(item.get("slug") or item.get("id") or "").strip()
                name = str(item.get("name") or slug).strip()
                if slug:
                    models.append((name, slug))

            if not models:
                models = list(ChatGptProvider.default_models)

            self.models_fetched.emit(models)
        except Exception as exc:
            self.fetch_failed.emit(f"モデルデータの解析に失敗しました: {exc}")


class ChatGptProvider(BaseAiProvider):
    """Sign in with ChatGPT AIプロバイダプラグイン。"""

    id = "chatgpt"
    display_name = "ChatGPT"
    api_key_env = "CHATGPT_AUTH_TOKEN"
    auth_type = "oauth"
    default_models = (
        ("GPT-4o", "gpt-4o"),
        ("GPT-4o mini", "gpt-4o-mini"),
        ("o1", "o1"),
        ("o3-mini", "o3-mini"),
    )
    translator_class = ChatGptTranslator
    auth_label = "アカウント"

