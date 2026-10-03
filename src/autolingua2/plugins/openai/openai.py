from __future__ import annotations

from typing import Any

from autolingua2.plugins.contracts import BaseAiProvider, BaseHttpTranslator


class OpenAiTranslator(BaseHttpTranslator):
    """OpenAI API用の翻訳トランスレーター（BaseHttpTranslatorの差分のみ実装）。"""

    @property
    def endpoint(self) -> str:
        return "https://api.openai.com/v1/chat/completions"

    def build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
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
                if msg:
                    if status_code == 401:
                        return f"OpenAI APIキーが無効です ({msg})"
                    if status_code == 429:
                        return f"OpenAI レート制限または残高不足です ({msg})"
                    if status_code == 404:
                        return f"指定されたモデル '{self.model}' が見つかりません ({msg})"
                    return f"OpenAI エラー ({status_code}): {msg}"
        return None


class OpenAiProvider(BaseAiProvider):
    """OpenAI AIプロバイダプラグイン。"""

    id = "openai"
    display_name = "OpenAI"
    api_key_env = "OPENAI_API_KEY"
    default_models = (
        ("GPT-4o mini", "gpt-4o-mini"),
        ("GPT-4o", "gpt-4o"),
        ("GPT-4.1", "gpt-4.1"),
        ("o3-mini", "o3-mini"),
    )
    translator_class = OpenAiTranslator
