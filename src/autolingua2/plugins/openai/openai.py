from __future__ import annotations

from typing import Any
import json

from autolingua2.plugins.contracts import (
    BaseAiProvider, BaseHttpTranslator, ChatMessage, ChatReply, ChatToolCall,
    object_value, string_value,
)


class OpenAiTranslator(BaseHttpTranslator):
    """OpenAI API用の翻訳トランスレーター（BaseHttpTranslatorの差分のみ実装）。"""

    supports_chat = True

    def build_chat_payload(self, messages: list[ChatMessage], system_prompt: str,
                           tools: list[dict[str, Any]], continuation: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}]
            + [{"role": m.role, "content": m.content} for m in messages] + continuation,
            "tools": [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["inputSchema"],
            }} for t in tools],
        }

    def extract_chat_reply(self, data: dict[str, Any]) -> ChatReply:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAI: choices がありません。")
        choice = object_value(choices[0], "choice")
        if choice.get("finish_reason") == "length":
            raise ValueError("応答が出力上限に達しました。")
        message = object_value(choice.get("message"), "message")
        calls: list[ChatToolCall] = []
        for item in message.get("tool_calls", []):
            entry = object_value(item, "tool_call")
            function = object_value(entry.get("function"), "function")
            calls.append(ChatToolCall(
                string_value(entry.get("id"), "id"), string_value(function.get("name"), "name"),
                object_value(json.loads(string_value(function.get("arguments"), "arguments")), "arguments"),
            ))
        content = message.get("content")
        text = "" if content is None else string_value(content, "content")
        if not text and not calls:
            raise ValueError(str(message.get("refusal") or "AIの応答が空です。"))
        return ChatReply(text, calls, message)

    def chat_tool_result(self, call: ChatToolCall, result: dict[str, Any]) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)}

    @property
    def endpoint(self) -> str:
        return "https://api.openai.com/v1/chat/completions"

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
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        }

    def extract_translation(self, response_data: dict[str, Any]) -> str:
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAIレスポンスに 'choices' が含まれていません。")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("OpenAIレスポンスの choice 形式が不正です。")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("OpenAIレスポンスに 'message' が含まれていません。")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("OpenAIレスポンスの 'content' が文字列ではありません。")
        return content.strip()

    def extract_custom_error(self, error_data: dict[str, Any] | None, status_code: int) -> str | None:
        if isinstance(error_data, dict):
            err = error_data.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message", "")).strip()
                code = str(err.get("code", "")).strip()
                if status_code == 401 or code == "invalid_api_key":
                    return f"APIキーが無効です ({msg})"
                if status_code == 404 or code == "model_not_found" or "does not exist" in msg:
                    return f"指定されたモデル '{self.model}' が見つかりません ({msg})"
                if status_code == 429 or code == "insufficient_quota":
                    return f"OpenAI レート制限または残高不足です ({msg})"
                if msg:
                    return f"OpenAI エラー ({status_code}): {msg}"
        return None


class OpenAiProvider(BaseAiProvider):
    """OpenAI AIプロバイダプラグイン。"""

    id = "openai"
    display_name = "OpenAI"
    api_key_env = "OPENAI_API_KEY"
    default_models = (
        ("GPT-6.1 Sol", "gpt-6.1-sol"),
        ("GPT-6 Astra", "gpt-6-astra"),
        ("GPT-6 Luna", "gpt-6-luna"),
        ("GPT-5.6 Sol", "gpt-5.6-sol"),
        ("GPT-5.6 Terra", "gpt-5.6-terra"),
        ("GPT-5.6 Luna", "gpt-5.6-luna"),
    )
    translator_class = OpenAiTranslator
