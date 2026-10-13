from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from autolingua2.plugins.contracts import (
    BaseAiProvider, BaseHttpTranslator, ChatMessage, ChatReply, ChatToolCall,
    object_value, string_value,
)
from .auth import ChatGptAuthManager

logger = logging.getLogger(__name__)


def _response_events(body: str) -> Iterator[dict[str, Any]]:
    """Decode SSE records, including multiline data and CRLF line endings."""
    data_lines: list[str] = []
    for line in [*body.splitlines(), ""]:
        if not line:
            if data_lines:
                payload = "\n".join(data_lines)
                data_lines.clear()
                if payload != "[DONE]":
                    yield object_value(json.loads(payload), "Responses event")
        elif line.startswith("data:"):
            value = line[5:]
            data_lines.append(value[1:] if value.startswith(" ") else value)


def _event_index(event: dict[str, Any], name: str) -> int:
    value = event.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"ChatGPT: ストリームの{name}が不正です。")
    return value


def _output_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    output = data.get("output")
    if not isinstance(output, list):
        raise ValueError("ChatGPT: 応答のoutput配列がありません。")
    return [object_value(item, "Response output item") for item in output]


def _message_text(output: dict[str, Any]) -> str:
    content = output.get("content")
    if not isinstance(content, list):
        raise ValueError("ChatGPT: メッセージのcontent配列がありません。")
    texts: list[str] = []
    for part in content:
        block = object_value(part, "Response content block")
        if block.get("type") == "output_text":
            texts.append(string_value(block.get("text"), "Output text"))
        elif block.get("type") == "refusal":
            raise ValueError("ChatGPT: 応答が拒否されました。")
    return "".join(texts)


class ChatGptTranslator(BaseHttpTranslator):
    """Sign in with ChatGPT 連携用トランスレーター（Responses API /v1/responses 準拠）。"""

    supports_chat = True
    chat_image_types = ("image/png", "image/jpeg", "image/webp", "image/gif")

    @property
    def endpoint(self) -> str:
        return "https://api.openai.com/v1/responses"

    def build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
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
            "instructions": system_prompt,
            "input": [{"role": "user", "content": text}],
            "stream": True,
            "store": False,
        }

    def extract_translation(self, response_data: dict[str, Any]) -> str:
        outputs = _output_items(response_data)
        translated = "".join(
            _message_text(item) for item in outputs if item.get("type") == "message"
        ).strip()
        if translated:
            return translated
        output_types = ", ".join(str(item.get("type")) for item in outputs) or "なし"
        raise ValueError(f"ChatGPT: 応答は完了しましたが本文が空です (output: {output_types})。")

    def build_chat_payload(
        self, messages: list[ChatMessage], system_prompt: str,
        tools: list[dict[str, Any]], continuation: list[dict[str, Any]],
    ) -> dict[str, Any]:
        formatted_messages: list[dict[str, Any]] = [
            {"role": m.role, "content": ([{"type": "input_text", "text": m.content}]
                + [{"type": "input_image", "image_url": image.data_url} for image in m.images]
                if m.images else m.content)} for m in messages
        ]
        for item in continuation:
            if item.get("type") == "function_call_output":
                formatted_messages.append(item)
            else:
                formatted_messages.extend(_output_items(item))
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": formatted_messages,
            "stream": True,
            "store": False,
        }
        if tools:
            payload["tools"] = [{
                "type": "function",
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            } for t in tools]
        return payload

    def decode_response(self, response_body: str) -> dict[str, Any]:
        completed: dict[str, Any] | None = None
        items: dict[int, dict[str, Any]] = {}
        texts: dict[tuple[int, int], str] = {}
        event_count = 0
        for event in _response_events(response_body):
            event_count += 1
            event_type = event.get("type")
            if event_type in {"response.output_text.delta", "response.output_text.done"}:
                key = (_event_index(event, "output_index"), _event_index(event, "content_index"))
                if event_type == "response.output_text.delta":
                    texts[key] = texts.get(key, "") + string_value(event.get("delta"), "Text delta")
                else:
                    texts[key] = string_value(event.get("text"), "Final text")
            elif event_type == "response.output_item.done":
                items[_event_index(event, "output_index")] = object_value(event.get("item"), "Final output item")
            elif event_type == "response.refusal.done":
                raise ValueError("ChatGPT: 応答が拒否されました。")
            elif event_type == "response.completed":
                completed = object_value(event.get("response"), "Responses completion")
                if completed.get("status") != "completed":
                    raise ValueError("ChatGPT: 完了イベントのstatusが不正です。")
            elif event_type in {"response.failed", "response.incomplete", "error"}:
                response = event if event_type == "error" else object_value(event.get("response"), "Failed response")
                details = response.get("incomplete_details" if event_type == "response.incomplete" else "error")
                error = response if event_type == "error" else (
                    {} if details is None else object_value(details, "Response error")
                )
                reason = error.get("reason") or error.get("code") or "unknown_error"
                message = error.get("message") or ""
                raise ValueError(f"ChatGPT: {event_type} ({reason}) {message}".strip())
        if completed is None:
            raise ValueError(f"ChatGPT: ストリームが完了せず終了しました ({event_count}イベント)。")

        # Assemble streamed items and text blocks before exposing a completed response.
        output = {index: item for index, item in enumerate(_output_items(completed))}
        output.update(items)
        blocks: dict[int, dict[int, dict[str, Any]]] = {}
        for (output_index, content_index), text in texts.items():
            blocks.setdefault(output_index, {})[content_index] = {"type": "output_text", "text": text}
        for output_index, text_blocks in blocks.items():
            item = output.setdefault(output_index, {"type": "message", "role": "assistant", "content": []})
            if item.get("type") != "message":
                raise ValueError("ChatGPT: 本文イベントと出力項目のtypeが一致しません。")
            content = item.get("content")
            if not isinstance(content, list):
                raise ValueError("ChatGPT: メッセージのcontent配列が不正です。")
            merged = {index: object_value(part, "Content block") for index, part in enumerate(content)}
            merged.update(text_blocks)
            item["content"] = [merged[index] for index in sorted(merged)]
        completed["output"] = [output[index] for index in sorted(output)]
        logger.info("ChatGPT response model=%s events=%d output_items=%d text_blocks=%d status=completed",
                    self.model, event_count, len(output), len(texts))
        return completed

    def extract_chat_reply(self, data: dict[str, Any]) -> ChatReply:
        texts: list[str] = []
        calls: list[ChatToolCall] = []
        for item in _output_items(data):
            if item.get("type") == "message":
                texts.append(_message_text(item))
            elif item.get("type") == "function_call":
                calls.append(ChatToolCall(
                    string_value(item.get("call_id"), "call_id"),
                    string_value(item.get("name"), "name"),
                    object_value(json.loads(string_value(item.get("arguments"), "arguments")), "arguments"),
                ))
        text = "".join(texts).strip()
        if text or calls:
            return ChatReply(text, calls, data)
        raise ValueError("ChatGPT: 有効な応答が得られませんでした。")

    def chat_tool_result(self, call: ChatToolCall, result: dict[str, Any]) -> dict[str, Any]:
        return {"type": "function_call_output", "call_id": call.id,
                "output": json.dumps(result, ensure_ascii=False)}

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
            model_items = data.get("models")
            if not isinstance(model_items, list):
                raise ValueError("モデル一覧の応答にmodels配列がありません。")
            models: list[tuple[str, str]] = []
            for item in model_items:
                if not isinstance(item, dict):
                    continue
                visibility = item.get("visibility")
                if visibility != "list":
                    continue
                slug = item.get("slug")
                name = item.get("display_name")
                if isinstance(slug, str) and slug.strip():
                    models.append((name.strip() if isinstance(name, str) and name.strip() else slug.strip(),
                                   slug.strip()))

            self.models_fetched.emit(models)
        except Exception as exc:
            self.fetch_failed.emit(f"モデルデータの解析に失敗しました: {exc}")


class ChatGptProvider(BaseAiProvider):
    """Sign in with ChatGPT AIプロバイダプラグイン。"""

    id = "chatgpt"
    display_name = "ChatGPT"
    api_key_env = "CHATGPT_AUTH_TOKEN"
    auth_type = "oauth"
    translator_class = ChatGptTranslator

    def __init__(self, auth: ChatGptAuthManager) -> None:
        self._auth = auth

    def create(self, api_key: str, model: str) -> ChatGptTranslator:
        token = self._auth.access_token
        if not token:
            raise ValueError("ChatGPTにログインしてください。")
        return ChatGptTranslator(api_key=token, model=model)

