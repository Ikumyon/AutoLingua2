from __future__ import annotations

from typing import Any
import json

from autolingua2.plugins.contracts import (
    BaseAiProvider, BaseHttpTranslator, ChatMessage, ChatReply, ChatToolCall,
    object_value, string_value,
)

DEFAULT_CLAUDE_MODELS: tuple[tuple[str, str], ...] = (
    ("Claude Sonnet 5.5", "claude-sonnet-5-5"),
    ("Claude Opus 5.5", "claude-opus-5-5"),
    ("Claude Fable 5.1", "claude-fable-5-1"),
    ("Claude Sonnet 5", "claude-sonnet-5"),
)


class ClaudeTranslator(BaseHttpTranslator):
    """Anthropic Claude API用の翻訳トランスレーター（BaseHttpTranslatorの差分のみ実装）。"""

    supports_chat = True

    def build_chat_payload(self, messages: list[ChatMessage], system_prompt: str,
                           tools: list[dict[str, Any]], continuation: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": self.model, "max_tokens": 4096, "system": system_prompt,
            "messages": [{"role": m.role, "content": m.content} for m in messages] + continuation,
            "tools": [{"name": t["name"], "description": t["description"],
                       "input_schema": t["inputSchema"]} for t in tools],
        }

    def extract_chat_reply(self, data: dict[str, Any]) -> ChatReply:
        if data.get("stop_reason") == "max_tokens":
            raise ValueError("応答が出力上限に達しました。")
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise ValueError("Claude: content がありません。")
        texts: list[str] = []
        calls: list[ChatToolCall] = []
        for item in blocks:
            block = object_value(item, "content block")
            if block.get("type") == "text":
                texts.append(string_value(block.get("text"), "text"))
            elif block.get("type") == "tool_use":
                calls.append(ChatToolCall(string_value(block.get("id"), "id"),
                                          string_value(block.get("name"), "name"),
                                          object_value(block.get("input"), "input")))
        if not texts and not calls:
            raise ValueError("AIの応答が空です。")
        return ChatReply("\n".join(texts), calls, {"role": "assistant", "content": blocks})

    def chat_tool_result(self, call: ChatToolCall, result: dict[str, Any]) -> dict[str, Any]:
        return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id,
                "content": json.dumps(result, ensure_ascii=False), "is_error": "error" in result}]}

    @property
    def endpoint(self) -> str:
        return "https://api.anthropic.com/v1/messages"

    def build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
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
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        }

    def extract_translation(self, response_data: dict[str, Any]) -> str:
        content_list = response_data.get("content")
        if not isinstance(content_list, list) or not content_list:
            raise ValueError("Claudeレスポンスに 'content' が含まれていません。")
        first_block = content_list[0]
        if not isinstance(first_block, dict):
            raise ValueError("Claude content ブロックの形式が不正です。")
        text_val = first_block.get("text")
        if not isinstance(text_val, str):
            raise ValueError("Claudeレスポンスの 'text' が文字列ではありません。")
        return text_val.strip()

    def extract_custom_error(self, error_data: dict[str, Any] | None, status_code: int) -> str | None:
        if isinstance(error_data, dict):
            err = error_data.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message", "")).strip()
                err_type = str(err.get("type", "")).strip()
                if status_code == 404 or err_type == "not_found_error" or "not_found" in err_type or "model:" in msg.lower():
                    return f"指定されたモデル '{self.model}' が見つかりません ({msg})"
                if status_code == 401 or err_type == "authentication_error" or "api-key" in msg.lower() or "permission" in msg.lower() or status_code == 403:
                    return f"APIキーが無効です ({msg})"
                if status_code == 429 or err_type == "rate_limit_error":
                    return f"Claude レート制限または残高不足です ({msg})"
                if msg:
                    return f"Claude エラー ({status_code}): {msg}"
        return None


class ClaudeProvider(BaseAiProvider):
    """Anthropic Claude AIプロバイダプラグイン。"""

    id = "claude"
    display_name = "Anthropic Claude"
    api_key_env = "ANTHROPIC_API_KEY"
    default_models = DEFAULT_CLAUDE_MODELS
    translator_class = ClaudeTranslator
