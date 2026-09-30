from __future__ import annotations

from typing import Protocol, runtime_checkable


class TranslationProviderError(RuntimeError):
    pass


class TextTranslator(Protocol):
    def translate(self, text: str, source_language: str, target_language: str) -> str: ...


@runtime_checkable
class AiProviderPlugin(Protocol):
    id: str
    display_name: str
    api_key_env: str

    def create(self, api_key: str, model: str) -> TextTranslator: ...
