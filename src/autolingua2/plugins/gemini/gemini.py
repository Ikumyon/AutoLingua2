from __future__ import annotations

from typing import Any

from autolingua2.plugins.contracts import (
    BaseAiProvider, BaseHttpTranslator, ChatMessage, ChatReply, ChatToolCall,
    object_value, string_value,
)

DEFAULT_GEMINI_MODELS: tuple[tuple[str, str], ...] = (
    ("Gemini 3.8 Flash", "gemini-3.8-flash"),
    ("Gemini 3.5 Flash", "gemini-3.5-flash"),
    ("Gemini 3 Pro", "gemini-3-pro"),
)


class GeminiTranslator(BaseHttpTranslator):
    """Google Gemini API用の翻訳トランスレーター（BaseHttpTranslatorの差分のみ実装）。"""

    supports_chat = True

    def build_chat_payload(self, messages: list[ChatMessage], system_prompt: str,
                           tools: list[dict[str, Any]], continuation: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "model" if m.role == "assistant" else "user",
                          "parts": [{"text": m.content}]} for m in messages] + continuation,
            "tools": [{"functionDeclarations": [{
                "name": t["name"], "description": t["description"], "parameters": t["inputSchema"],
            } for t in tools]}],
        }

    def extract_chat_reply(self, data: dict[str, Any]) -> ChatReply:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Gemini: 応答がありません（ブロックされた可能性があります）。")
        candidate = object_value(candidates[0], "candidate")
        if candidate.get("finishReason") not in (None, "STOP"):
            raise ValueError(f"Gemini: 応答が完了しませんでした: {candidate.get('finishReason')}")
        message = object_value(candidate.get("content"), "content")
        calls: list[ChatToolCall] = []
        texts: list[str] = []
        for item in message.get("parts", []):
            part = object_value(item, "part")
            if "functionCall" in part:
                function = object_value(part["functionCall"], "functionCall")
                name = string_value(function.get("name"), "name")
                calls.append(ChatToolCall(str(function.get("id", name)), name,
                                          object_value(function.get("args", {}), "args")))
            elif "text" in part and not part.get("thought"):
                texts.append(string_value(part["text"], "text"))
        if not texts and not calls:
            raise ValueError("AIの応答が空です。")
        return ChatReply("\n".join(texts), calls, message)

    def chat_tool_result(self, call: ChatToolCall, result: dict[str, Any]) -> dict[str, Any]:
        response: dict[str, Any] = {"name": call.name, "response": result}
        if call.id != call.name:
            response["id"] = call.id
        return {"role": "user", "parts": [{"functionResponse": response}]}

    @property
    def endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
            "User-Agent": "AUTOlingua2/0.1.0",
        }

    def build_payload(
        self,
        text: str,
        source_language: str,
        target_language: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        return {
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": text}],
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
            },
        }

    def extract_translation(self, response_data: dict[str, Any]) -> str:
        candidates = response_data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Geminiレスポンスに 'candidates' が含まれていません。")
        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise ValueError("Gemini candidate 形式が不正です。")
        content = first_candidate.get("content")
        if not isinstance(content, dict):
            raise ValueError("Geminiレスポンスに 'content' が含まれていません。")
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError("Geminiレスポンスに 'parts' が含まれていません。")
        first_part = parts[0]
        if not isinstance(first_part, dict):
            raise ValueError("Gemini part 形式が不正です。")
        text_val = first_part.get("text")
        if not isinstance(text_val, str):
            raise ValueError("Geminiレスポンスの 'text' が文字列ではありません。")
        return text_val.strip()

    def extract_custom_error(self, error_data: dict[str, Any] | None, status_code: int) -> str | None:
        if isinstance(error_data, dict):
            err = error_data.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message", "")).strip()
                status_str = str(err.get("status", "")).strip()
                if status_code == 404 or status_str == "NOT_FOUND" or "not found" in msg.lower():
                    return f"指定されたモデル '{self.model}' が見つかりません ({msg})"
                if (
                    "api key not valid" in msg.lower()
                    or "api_key_invalid" in msg.lower()
                    or "unregistered callers" in msg.lower()
                    or status_code in (401, 403)
                ):
                    return f"APIキーが無効です ({msg})"
                if status_code == 429 or status_str == "RESOURCE_EXHAUSTED" or "quota" in msg.lower():
                    return f"Gemini レート制限または利用枠を超過しました ({msg})"
                if msg:
                    return f"Gemini エラー ({status_code}): {msg}"
        return None


class GeminiProvider(BaseAiProvider):
    """Google Gemini AIプロバイダプラグイン。"""

    id = "gemini"
    display_name = "Google Gemini"
    api_key_env = "GEMINI_API_KEY"
    default_models = DEFAULT_GEMINI_MODELS
    translator_class = GeminiTranslator
