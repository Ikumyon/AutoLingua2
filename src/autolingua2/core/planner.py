from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .protection import protect_text, restore_text, sentence_parts
from .translation_memory import MemoryEntry, MemoryMatch, select_match


class TextTranslator(Protocol):
    def translate(self, text: str, source_language: str, target_language: str) -> str: ...


class MemoryRepository(Protocol):
    def candidates(self, source: str, source_language: str, target_language: str) -> list[MemoryEntry]: ...
    def record(self, source: str, target: str, source_language: str, target_language: str,
               provenance: str, context: str = "") -> int: ...
    def mark_used(self, entry_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class TranslationOutcome:
    text: str
    method: str


def translate_with_memory(
    source_text: str,
    source_language: str,
    target_language: str,
    memory: MemoryRepository,
    translator_factory: Callable[[], TextTranslator] | None,
    context: str = "",
) -> TranslationOutcome:
    if not source_text.strip():
        raise ValueError("原文が空です")
    whole_match = select_match(
        source_text, memory.candidates(source_text, source_language, target_language),
        source_language, target_language, context,
    )
    if whole_match is not None:
        memory.mark_used(whole_match.entry_id)
        if whole_match.method == "structural":
            memory.record(source_text, whole_match.target, source_language,
                          target_language, "reused", context)
        return TranslationOutcome(whole_match.target, whole_match.method)
    parts = sentence_parts(source_text)
    translated: list[str] = []
    methods: set[str] = set()
    translator: TextTranslator | None = None
    for index, part in enumerate(parts):
        if index % 2 or not part.strip():
            translated.append(part)
            continue
        prefix = part[: len(part) - len(part.lstrip())]
        suffix = part[len(part.rstrip()) :]
        source = part.strip()
        match: MemoryMatch | None = select_match(
            source, memory.candidates(source, source_language, target_language),
            source_language, target_language, context,
        )
        if match is not None:
            target = match.target
            memory.mark_used(match.entry_id)
            if match.method == "structural":
                memory.record(source, target, source_language, target_language,
                              "reused", context)
            methods.add(match.method)
        else:
            if translator is None:
                if translator_factory is None:
                    raise ValueError("利用可能な翻訳メモリがなく、AI設定もありません")
                translator = translator_factory()
            target = translate_value(source, source_language, target_language, translator)
            memory.record(source, target, source_language, target_language, "ai", context)
            methods.add("ai")
        translated.append(prefix + target + suffix)
    result = "".join(translated)
    if not result.strip() or result == source_text:
        raise ValueError("訳文が原文と同じか空です")
    return TranslationOutcome(result, next(iter(methods)) if len(methods) == 1 else "mixed")


def translate_value(
    source_text: str,
    source_language: str,
    target_language: str,
    translator: TextTranslator,
) -> str:
    if not source_text.strip():
        raise ValueError("原文が空です")
    protected, tokens = protect_text(source_text)
    parts = sentence_parts(protected)
    translated_parts: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 or not part.strip():
            translated_parts.append(part)
            continue
        prefix = part[: len(part) - len(part.lstrip())]
        suffix = part[len(part.rstrip()) :]
        translated_parts.append(
            prefix + translator.translate(part.strip(), source_language, target_language).strip() + suffix
        )
    result = restore_text("".join(translated_parts), tokens)
    if not result.strip() or result == source_text:
        raise ValueError("訳文が原文と同じか空です")
    return result
