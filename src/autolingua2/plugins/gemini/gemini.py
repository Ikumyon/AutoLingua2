from __future__ import annotations

from typing import Any
from urllib.parse import quote

from autolingua2.plugins.contracts import (
    HOST_APP_VERSION,
    BaseAiProvider, BaseHttpTranslator, ChatMessage, ChatReply, ChatToolCall,
    object_value, string_value, TranslationUsage, usage_number, ChatCapacity,
)

DEFAULT_GEMINI_MODELS: tuple[tuple[str, str], ...] = (
    ("Gemini 3.8 Flash", "gemini-3.8-flash"),
    ("Gemini 3.5 Flash", "gemini-3.5-flash"),
    ("Gemini 3 Pro", "gemini-3-pro"),
)


class GeminiTranslator(BaseHttpTranslator):
    """Google Gemini API用の翻訳トランスレーター（BaseHttpTranslatorの差分のみ実装）。"""

    supports_chat = True
    chat_image_types = ("image/png", "image/jpeg", "image/webp")

    @property
    def chat_model_endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model, safe='')}"

    def extract_chat_capacity(self, data: dict[str, Any]) -> ChatCapacity | None:
        limit = usage_number(data, "inputTokenLimit")
        output = usage_number(data, "outputTokenLimit")
        if limit is None or limit <= 0:
            return None
        return ChatCapacity(limit, min(4096, output) if output else 4096)

    def is_chat_context_error(self, data: dict[str, Any], status_code: int) -> bool:
        error = data.get("error")
        if status_code != 400 or not isinstance(error, dict) or error.get("status") != "INVALID_ARGUMENT":
            return False
        message = str(error.get("message", "")).lower()
        return ("input token" in message and ("exceed" in message or "maximum" in message)
                or "exceeds the context window" in message)

    def build_summary_payload(self, messages: list[ChatMessage], instructions: str,
                              output_tokens: int) -> dict[str, Any]:
        payload = self.build_chat_payload(messages, instructions, [], [])
        payload["generationConfig"] = {"maxOutputTokens": output_tokens}
        return payload

    def extract_usage(self, data: dict[str, Any]) -> TranslationUsage:
        usage = data.get("usageMetadata")
        return TranslationUsage(
            input_tokens=usage_number(usage, "promptTokenCount"), output_tokens=usage_number(usage, "candidatesTokenCount"),
            reasoning_tokens=usage_number(usage, "thoughtsTokenCount"),
            cache_read_tokens=usage_number(usage, "cachedContentTokenCount"), reasoning_in_output=False,
        )

    def build_chat_payload(self, messages: list[ChatMessage], system_prompt: str,
                           tools: list[dict[str, Any]], continuation: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "model" if m.role == "assistant" else "user",
                          "parts": [{"text": m.content}] + [
                              {"inlineData": {"mimeType": image.mime_type, "data": image.data}}
                              for image in m.images]} for m in messages] + continuation,
            "tools": [{"functionDeclarations": [{
                "name": t["name"], "description": t["description"], "parametersJsonSchema": t["inputSchema"],
            } for t in tools]}],
        }
        if not tools:
            payload.pop("tools")
        return payload

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
            "User-Agent": f"Autolingua Desktop/{HOST_APP_VERSION}",
        }

    def build_payload(
        self,
        text: str,
        source_language: str,
        target_language: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        generation: dict[str, Any] = {"temperature": 0.3}
        if self.model.startswith("gemini-3"):
            generation = {"thinkingConfig": {"thinkingLevel": "LOW"}}
        elif self.model.startswith("gemini-2.5-flash"):
            generation["thinkingConfig"] = {"thinkingBudget": 0}
        elif self.model.startswith("gemini-2.5-pro"):
            generation["thinkingConfig"] = {"thinkingBudget": 128}
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
            "generationConfig": generation,
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
