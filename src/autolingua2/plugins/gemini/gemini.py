from __future__ import annotations

from typing import Any

from autolingua2.plugins.contracts import BaseAiProvider, BaseHttpTranslator

DEFAULT_GEMINI_MODELS: tuple[tuple[str, str], ...] = (
    ("Gemini 3.8 Flash", "gemini-3.8-flash"),
    ("Gemini 3.5 Flash", "gemini-3.5-flash"),
    ("Gemini 3 Pro", "gemini-3-pro"),
)


class GeminiTranslator(BaseHttpTranslator):
    """Google Gemini API用の翻訳トランスレーター（BaseHttpTranslatorの差分のみ実装）。"""

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
                if msg:
                    if status_code in (400, 401, 403):
                        return f"Gemini APIキーが無効または権限がありません ({msg})"
                    if status_code == 429:
                        return f"Gemini レート制限または利用枠を超過しました ({msg})"
                    if status_code == 404:
                        return f"指定されたモデル '{self.model}' が見つかりません ({msg})"
                    return f"Gemini エラー ({status_code}): {msg}"
        return None


class GeminiProvider(BaseAiProvider):
    """Google Gemini AIプロバイダプラグイン。"""

    id = "gemini"
    display_name = "Google Gemini"
    api_key_env = "GEMINI_API_KEY"
    default_models = DEFAULT_GEMINI_MODELS
    translator_class = GeminiTranslator
