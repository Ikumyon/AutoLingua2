from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .base import TranslationProviderError


class GeminiTranslationProvider:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key.strip() or not model.strip():
            raise ValueError("APIキーとモデルを設定してください")
        self.api_key = api_key.strip()
        self.model = model.strip()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        model = self.model.removeprefix("models/")
        if not model or "/" in model:
            raise ValueError("Gemini のモデル名が正しくありません")
        instructions = (
            f"Translate the user text from {source_language} to {target_language}. "
            "Return only the translation. Preserve every __AL_TOKEN_000__ style placeholder "
            "exactly, in its original order. Do not explain or add quotation marks."
        )
        payload = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": text}]}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='-._')}:generateContent",
            data=payload,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=180) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise TranslationProviderError(f"Gemini API エラー: HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise TranslationProviderError(f"Gemini API に接続できません: {exc}") from exc

        candidates = result.get("candidates", [])
        if not candidates:
            raise TranslationProviderError("Gemini API が訳を返しませんでした")
        candidate = candidates[0]
        if candidate.get("finishReason") not in (None, "STOP"):
            raise TranslationProviderError(f"Gemini API の応答が完了しませんでした: {candidate['finishReason']}")
        content = candidate.get("content") or {}
        translated = "".join(
            part.get("text", "") for part in content.get("parts", [])
            if isinstance(part, dict) and not part.get("thought", False)
        ).strip()
        if not translated:
            raise TranslationProviderError("Gemini API が空の訳を返しました")
        return translated


class GeminiPlugin:
    id = "gemini"
    display_name = "Gemini"
    api_key_env = "GEMINI_API_KEY"

    def create(self, api_key: str, model: str) -> GeminiTranslationProvider:
        return GeminiTranslationProvider(api_key, model)
