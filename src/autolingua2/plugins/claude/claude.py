from __future__ import annotations

from typing import Any

from autolingua2.plugins.contracts import BaseAiProvider, BaseHttpTranslator

DEFAULT_CLAUDE_MODELS: tuple[tuple[str, str], ...] = (
    ("Claude 3.7 Sonnet", "claude-3-7-sonnet-20250219"),
    ("Claude 3.5 Sonnet", "claude-3-5-sonnet-20241022"),
    ("Claude 3.5 Haiku", "claude-3-5-haiku-20241022"),
    ("Claude 3 Opus", "claude-3-opus-20240229"),
)


class ClaudeTranslator(BaseHttpTranslator):
    """Anthropic Claude API用の翻訳トランスレーター（BaseHttpTranslatorの差分のみ実装）。"""

    @property
    def endpoint(self) -> str:
        return "https://api.anthropic.com/v1/messages"

    def build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
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
                if msg:
                    if status_code in (400, 401, 403):
                        return f"Claude APIキーが無効または権限がありません ({msg})"
                    if status_code == 429:
                        return f"Claude レート制限または残高不足です ({msg})"
                    if status_code == 404:
                        return f"指定されたモデル '{self.model}' が見つかりません ({msg})"
                    return f"Claude エラー ({status_code}): {msg}"
        return None


class ClaudeProvider(BaseAiProvider):
    """Anthropic Claude AIプロバイダプラグイン。"""

    id = "claude"
    display_name = "Anthropic Claude"
    api_key_env = "ANTHROPIC_API_KEY"
    default_models = DEFAULT_CLAUDE_MODELS
    translator_class = ClaudeTranslator
