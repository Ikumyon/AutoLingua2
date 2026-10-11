from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from itertools import count
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from autolingua2.ir import UnitState
from autolingua2.ir.classification import ClassificationResult, SourceCategory
from autolingua2.ir.workspace import UnitView, Workspace
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.tone import ConditionalTone, Tone, ToneContext, ToneItem, resolve_tone
from autolingua2.services.ai_network import AiNetworkClient
from autolingua2.services.ai_providers.base import AiProviderPlugin


@dataclass(frozen=True)
class TranslationOptions:
    provider: AiProviderPlugin
    api_key: str
    model: str
    source_language: str
    target_language: str
    source_language_name: str = ""
    target_language_name: str = ""
    tone: Tone | None = None
    tone_items: tuple[ToneItem, ...] = ()


def tone_context(imported: ImportedTranslation, unit: UnitView) -> ToneContext:
    ref = imported.source_refs.get(unit.id)
    if ref is None:
        raise ValueError("条件付き口調の判定に必要な原文情報がありません。")
    source = next((source for source in imported.project.sources if source.id == ref.source_id), None)
    if source is None:
        raise ValueError("条件付き口調の判定に必要なファイル情報がありません。")
    return ToneContext(Path(source.name).name, ref.external_id, unit.source_text)


@dataclass(frozen=True)
class _TranslationTask:
    workspace: Workspace
    unit: UnitView
    batch: bool
    generation: int
    options: TranslationOptions
    applied_tone: ToneItem | None = None


class TranslationService(QObject):
    """単件・一括翻訳の要求、進行、キャンセルとモデル反映を管理する。"""

    unit_translated = Signal(object, object, bool)
    translation_failed = Signal(object, str, bool)
    batch_unit_started = Signal(object, int, int)
    progress_changed = Signal(int, int)
    batch_finished = Signal(int, int)
    batch_stopped = Signal()

    def __init__(
        self, client: AiNetworkClient,
        workspace_is_alive: Callable[[Workspace], bool],
        get_options: Callable[[], TranslationOptions | None],
        parent: QObject | None = None,
        *,
        get_tone_context: Callable[[UnitView], ToneContext],
    ) -> None:
        super().__init__(parent)
        self.client = client
        self._workspace_is_alive = workspace_is_alive
        self._get_options = get_options
        self._get_tone_context = get_tone_context
        self._batch_options: TranslationOptions | None = None
        self.completed_options: TranslationOptions | None = None
        self._ids = count()
        self._pending: dict[str, _TranslationTask] = {}
        self._queue: deque[UnitView] = deque()
        self._batch_workspace: Workspace | None = None
        self._batch_generation = 0
        self.running = False
        self.completed = 0
        self.total = 0
        client.translation_completed.connect(self._completed)
        client.translation_failed.connect(self._failed)

    def start_batch(
        self, workspace: Workspace, targets: list[UnitView],
        classification: ClassificationResult | None,
    ) -> None:
        if self.running:
            self.stop()
        self._batch_generation += 1
        self._batch_workspace = workspace
        selected = {unit.id: unit for unit in targets if unit.source_text.strip()}
        options = self._get_options()
        if options is None:
            return
        resolved_tones: dict[str, str | None] = {}
        for unit in selected.values():
            try:
                resolved_tones[unit.id] = self._tone_for(unit, options)
            except ValueError as exc:
                self.translation_failed.emit(unit, str(exc), True)
                return
        self._batch_options = options
        selected_order = {unit_id: position for position, unit_id in enumerate(selected)}
        representatives: dict[str, UnitView] = {}
        if classification is not None:
            for group in classification.groups:
                if group.category != SourceCategory.EXACT:
                    continue
                candidates_by_tone: dict[str | None, list[UnitView]] = {}
                for element in group.elements:
                    candidate = selected.get(element.unit_id)
                    if candidate is not None:
                        candidates_by_tone.setdefault(resolved_tones[candidate.id], []).append(candidate)
                for candidates in candidates_by_tone.values():
                    representative = next((unit for unit in candidates if unit.id == group.representative_id), None)
                    if representative is None:
                        representative = min(candidates, key=lambda unit: selected_order[unit.id])
                    representatives.update((unit.id, representative) for unit in candidates)
        queued: dict[str, UnitView] = {}
        for unit in selected.values():
            representative = representatives.get(unit.id, unit)
            queued.setdefault(representative.id, representative)
        self._queue = deque(queued.values())
        self.running = True
        self.completed = 0
        self.total = len(self._queue)
        self.progress_changed.emit(0, self.total)
        self._next_batch_unit(self._batch_generation)

    def translate_single(
        self, workspace: Workspace, unit: UnitView, options: TranslationOptions,
    ) -> None:
        if unit.source_text.strip():
            self._request(_TranslationTask(workspace, unit, False, self._batch_generation, options))

    def stop(self) -> None:
        was_running = self.running
        self.running = False
        self._batch_generation += 1
        self._batch_workspace = None
        self._batch_options = None
        self._queue.clear()
        self._pending.clear()
        self.client.cancel_all()
        if was_running:
            self.batch_stopped.emit()

    def _next_batch_unit(self, generation: int) -> None:
        if not self.running or generation != self._batch_generation:
            return
        if not self._queue:
            self.running = False
            self._batch_workspace = None
            self._batch_options = None
            self.batch_finished.emit(self.completed, self.total)
            return
        workspace = self._batch_workspace
        if workspace is None:
            raise RuntimeError("一括翻訳のワークスペースがありません")
        options = self._batch_options
        if not self._workspace_is_alive(workspace) or options is None:
            self.stop()
            return
        unit = self._queue.popleft()
        self.batch_unit_started.emit(unit, self.completed + 1, self.total)
        self._request(_TranslationTask(workspace, unit, True, generation, options))

    def _tone_for(self, unit: UnitView, options: TranslationOptions) -> str | None:
        tone = self.resolved_tone(unit, options.tone, options.tone_items)
        return tone.prompt if tone is not None else None

    def resolved_tone(self, unit: UnitView, selected: Tone | None,
                      items: Sequence[ToneItem]) -> ToneItem | None:
        tone = selected if isinstance(selected, ToneItem) else None
        if isinstance(selected, ConditionalTone):
            tone = resolve_tone(selected.block, items, self._get_tone_context(unit))
        return replace(tone) if tone is not None else None

    def matching_tone_peers[T: UnitView](self, peers: Sequence[T], applied: ToneItem | None,
                                        selected: Tone | None, items: Sequence[ToneItem]) -> list[T]:
        prompt = applied.prompt if applied is not None else None
        matched: list[T] = []
        for peer in peers:
            tone = self.resolved_tone(peer, selected, items)
            if (tone.prompt if tone is not None else None) == prompt:
                matched.append(peer)
        return matched

    def _request(self, task: _TranslationTask) -> None:
        options = task.options
        try:
            tone = self.resolved_tone(task.unit, options.tone, options.tone_items)
        except ValueError as exc:
            self.translation_failed.emit(task.unit, str(exc), task.batch)
            self._advance(task)
            return
        request_id = f"translation_{next(self._ids)}"
        self._pending[request_id] = replace(task, applied_tone=tone)
        self.client.translate_text(
            request_id=request_id, provider=options.provider, api_key=options.api_key,
            model=options.model, text=task.unit.source_text,
            source_language=options.source_language, target_language=options.target_language,
            source_language_name=options.source_language_name,
            target_language_name=options.target_language_name,
            tone=tone.prompt if tone is not None else None,
        )

    def _completed(self, request_id: str, translated_text: str) -> None:
        task = self._pending.pop(request_id, None)
        if task is None:
            return
        if not self._workspace_is_alive(task.workspace):
            if task.batch:
                self.stop()
            return
        task.unit.target_text = translated_text
        task.unit.state = UnitState.AI_TRANSLATED
        task.workspace.records[task.unit.id].tone = task.applied_tone
        self.completed_options = task.options
        self.unit_translated.emit(task.workspace, task.unit, task.batch)
        self._advance(task)

    def _failed(self, request_id: str, error_message: str) -> None:
        task = self._pending.pop(request_id, None)
        if task is None:
            return
        self.translation_failed.emit(task.unit, error_message, task.batch)
        self._advance(task)

    def _advance(self, task: _TranslationTask) -> None:
        if not task.batch or not self.running or task.generation != self._batch_generation:
            return
        self.completed += 1
        self.progress_changed.emit(self.completed, self.total)
        generation = self._batch_generation
        QTimer.singleShot(0, lambda: self._next_batch_unit(generation))
