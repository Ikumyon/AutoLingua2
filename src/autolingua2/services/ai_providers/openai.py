from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import TranslationProviderError


class OpenAITranslationProvider:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key.strip() or not model.strip():
            raise ValueError("APIキーとモデルを設定してください")
        self.api_key = api_key.strip()
        self.model = model.strip()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "store": False,
                "instructions": (
                    f"Translate the user text from {source_language} to {target_language}. "
                    "Return only the translation. Preserve every __AL_TOKEN_000__ style placeholder "
                    "exactly, in its original order. Do not explain or add quotation marks."
                ),
                "input": text,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            "https://api.openai.com/v1/responses",
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=180) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise TranslationProviderError(f"OpenAI API エラー: HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise TranslationProviderError(f"OpenAI API に接続できません: {exc}") from exc

        if result.get("status") != "completed":
            raise TranslationProviderError("OpenAI API の応答が完了しませんでした")
        parts = [
            part.get("text", "")
            for item in result.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        ]
        translated = "".join(parts).strip()
        if not translated:
            raise TranslationProviderError("OpenAI API が空の訳を返しました")
        return translated


class OpenAIPlugin:
    id = "openai"
    display_name = "OpenAI"
    api_key_env = "OPENAI_API_KEY"

    def create(self, api_key: str, model: str) -> OpenAITranslationProvider:
        return OpenAITranslationProvider(api_key, model)
