from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from threading import Event

from PySide6.QtCore import QThread, Signal

from autolingua2.core.planner import translate_with_memory
from autolingua2.services.ai_providers import AiProviderPlugin, TextTranslator
from autolingua2.services.translation_memory_store import TranslationMemoryStore


class TranslationWorker(QThread):
    translated = Signal(str, str, str)
    failed = Signal(str, str)
    advanced = Signal(int, int)

    def __init__(
        self,
        items: list[tuple[str, str, str]],
        source_language: str,
        target_language: str,
        provider_id: str,
        provider: AiProviderPlugin | None,
        api_key: str,
        model: str,
        concurrency: int = 4,
    ) -> None:
        super().__init__()
        self.items = items
        self.source_language = source_language
        self.target_language = target_language
        self.provider_id = provider_id
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.concurrency = max(1, min(32, concurrency))
        self._stop = Event()

    def stop(self) -> None:
        self._stop.set()

    def _make_translator(self) -> TextTranslator:
        if self.provider is None:
            raise ValueError(f"選択したAI Providerを利用できません: {self.provider_id}")
        if not self.api_key.strip():
            raise ValueError(f"{self.provider.display_name} のAPIキーを設定してください")
        if not self.model.strip():
            raise ValueError(f"{self.provider.display_name} のモデル名を設定してください")
        translator = self.provider.create(self.api_key, self.model)
        if not callable(getattr(translator, "translate", None)):
            raise ValueError(f"{self.provider.display_name} の翻訳機能がありません")
        return translator

    def _translate_item(self, source_text: str, context: str) -> tuple[str, str]:
        with TranslationMemoryStore() as memory:
            outcome = translate_with_memory(
                source_text, self.source_language, self.target_language,
                memory, self._make_translator, context,
            )
        return outcome.text, outcome.method

    def run(self) -> None:
        remaining = iter(self.items)
        completed = 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            pending: dict[Future[tuple[str, str]], str] = {}

            def submit_next() -> bool:
                if self._stop.is_set():
                    return False
                item = next(remaining, None)
                if item is None:
                    return False
                unit_id, source_text, context = item
                pending[executor.submit(self._translate_item, source_text, context)] = unit_id
                return True

            for _ in range(min(self.concurrency, len(self.items))):
                submit_next()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    unit_id = pending.pop(future)
                    if not self._stop.is_set():
                        try:
                            text, method = future.result()
                        except Exception as exc:
                            self.failed.emit(unit_id, str(exc))
                        else:
                            self.translated.emit(unit_id, text, method)
                        completed += 1
                        self.advanced.emit(completed, len(self.items))
                    submit_next()
