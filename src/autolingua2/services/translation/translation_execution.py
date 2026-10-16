"""Independent decisions for translation order, model routing, and request slots."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
import heapq
from PySide6.QtCore import QObject, Signal

from autolingua2.services.ai_providers.base import AiProviderPlugin


class TranslationDifficulty(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class TranslationModel:
    provider: AiProviderPlugin
    api_key: str
    model: str


@dataclass(frozen=True, slots=True)
class TranslationOrder:
    unit_id: str
    position: int
    dependency: str | None = None


class TranslationOrderPlanner:
    def __init__(self, orders: Iterable[TranslationOrder]) -> None:
        self.orders = {order.unit_id: order for order in orders}
        self.completed: set[str] = set()
        self.failed: set[str] = set()
        self.started: set[str] = set()
        self._resumable: set[str] = set()
        for order in self.orders.values():
            visited = {order.unit_id}
            dependency = order.dependency
            while dependency is not None:
                if dependency in visited or dependency not in self.orders:
                    raise ValueError("翻訳の依存関係が循環しているか、参考元がありません。")
                visited.add(dependency)
                dependency = self.orders[dependency].dependency
        self._representatives = {order.dependency for order in self.orders.values() if order.dependency is not None}
        self._dependents: dict[str, list[str]] = {}
        self._ready: list[tuple[bool, int, str]] = []
        for order in self.orders.values():
            if order.dependency is None:
                heapq.heappush(self._ready, (order.unit_id not in self._representatives, order.position, order.unit_id))
            else:
                self._dependents.setdefault(order.dependency, []).append(order.unit_id)

    def next_ready(self) -> str | None:
        if not self.has_ready:
            return None
        _, _, unit_id = heapq.heappop(self._ready)
        self._resumable.discard(unit_id)
        self.started.add(unit_id)
        return unit_id

    @property
    def has_ready(self) -> bool:
        while self._ready:
            unit_id = self._ready[0][2]
            if (unit_id in self.completed or unit_id in self.failed
                    or (unit_id in self.started and unit_id not in self._resumable)):
                heapq.heappop(self._ready)
                continue
            return True
        return False

    def resume(self, unit_id: str) -> None:
        if unit_id not in self.started or unit_id in self.completed or unit_id in self.failed:
            raise ValueError("再開する翻訳仕事が実行中ではありません。")
        if unit_id not in self._resumable:
            self._resumable.add(unit_id)
            order = self.orders[unit_id]
            heapq.heappush(self._ready, (unit_id not in self._representatives, order.position, unit_id))

    def finish(self, unit_id: str, *, success: bool) -> set[str]:
        if success:
            if unit_id in self.completed:
                return set()
            self.completed.add(unit_id)
            for dependent in self._dependents.get(unit_id, ()):
                order = self.orders[dependent]
                heapq.heappush(self._ready, (dependent not in self._representatives, order.position, dependent))
            return set()
        affected = {unit_id}
        waiting = [unit_id]
        while waiting:
            for dependent in self._dependents.get(waiting.pop(), ()):
                if dependent not in affected:
                    affected.add(dependent)
                    waiting.append(dependent)
        self.failed.update(affected)
        return affected - {unit_id}


class TranslationModelRouter:
    def __init__(self, high: TranslationModel, low: TranslationModel) -> None:
        self.high = high
        self.low = low

    def select(self, difficulty: TranslationDifficulty) -> TranslationModel:
        return self.low if difficulty == TranslationDifficulty.LOW else self.high


class TranslationSlotManager(QObject):
    freed = Signal()
    ready_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.limit = 4
        self._requests: set[str] = set()
        self._sources: dict[str, Callable[[], bool]] = {}
        self._last_source: str | None = None

    def register_source(self, source: str, has_ready: Callable[[], bool]) -> None:
        self._sources[source] = has_ready

    def can_dispatch(self, source: str) -> bool:
        return self.available and (self._last_source != source or not any(
            has_ready() for other, has_ready in self._sources.items() if other != source
        ))

    def notify_ready(self) -> None:
        self.ready_changed.emit()

    def configure(self, limit: int) -> None:
        if not 1 <= limit <= 32:
            raise ValueError("同時リクエスト数は1〜32で指定してください。")
        self.limit = limit

    def acquire(self, request_id: str, *, source: str = "direct") -> bool:
        if request_id in self._requests:
            return True
        if not self.can_dispatch(source):
            return False
        self._requests.add(request_id)
        self._last_source = source
        return True

    def release(self, request_id: str) -> None:
        if request_id in self._requests:
            self._requests.remove(request_id)
            self.freed.emit()

    def clear(self) -> None:
        self._requests.clear()
        self._last_source = None
        self.freed.emit()

    @property
    def available(self) -> bool:
        return self.remaining > 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - len(self._requests))

    @property
    def idle(self) -> bool:
        return not self._requests
