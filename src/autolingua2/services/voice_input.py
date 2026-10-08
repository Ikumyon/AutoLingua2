"""Voice input lifecycle, independent of chat widgets and plugin management."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Literal
import weakref

from PySide6.QtCore import QObject, Qt, Signal, Slot

from .voice_input_contract import VoiceInputCallbacks, VoiceInputOperation, VoiceInputProvider


logger = logging.getLogger(__name__)
VoiceInputState = Literal["idle", "recording", "processing"]


def voice_input_available(provider: VoiceInputProvider) -> bool:
    try:
        available = provider.is_available()
        if not isinstance(available, bool):
            raise TypeError("Voice input availability must be a bool")
        return available
    except Exception:
        logger.exception("Voice input availability check failed: %s", provider.id)
        return False


class VoiceInputService(QObject):
    changed = Signal()
    text_recognized = Signal(str)
    error = Signal(str)
    _notification = Signal(int, str, str)

    def __init__(self, providers: Mapping[str, VoiceInputProvider], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._providers = providers
        self._provider: VoiceInputProvider | None = None
        self._available = False
        self._operation: VoiceInputOperation | None = None
        self._state: VoiceInputState = "idle"
        self._generation = 0
        self._closed = False
        # Always queue, including synchronous callbacks during provider.start().
        self._notification.connect(self._receive, Qt.ConnectionType.QueuedConnection)

    @property
    def state(self) -> VoiceInputState:
        return self._state

    @property
    def active(self) -> bool:
        return self._state != "idle"

    @property
    def available(self) -> bool:
        return self._available and not self._closed

    def select_provider(self, provider_id: str) -> None:
        if self._closed:
            return
        self.cancel()
        self._provider = self._providers.get(provider_id)
        self._available = self._provider is not None and voice_input_available(self._provider)
        self.changed.emit()

    def start(self) -> None:
        if self._closed or self.active:
            return
        provider = self._provider
        if provider is None or not self.available:
            self.error.emit("Voice input provider is not available")
            return
        self._generation += 1
        generation = self._generation
        service_ref = weakref.ref(self)

        def notify(kind: str, value: str = "") -> None:
            service = service_ref()
            if service is None or service._closed or generation != service._generation:
                return
            if not isinstance(value, str):
                kind, value = "error", "Voice input notification must contain text"
            service._notification.emit(generation, kind, value)

        callbacks = VoiceInputCallbacks(
            text=lambda value: notify("text", value),
            finished=lambda: notify("finished"),
            error=lambda value: notify("error", value),
        )
        if provider.mode == "transcription":
            self._state = "recording"
            self.changed.emit()
        try:
            operation = provider.start(callbacks)
            if provider.mode == "external":
                if operation is not None:
                    if isinstance(operation, VoiceInputOperation):
                        operation.cancel()
                    raise TypeError("External voice input must return None")
                return
            if operation is None or not isinstance(operation, VoiceInputOperation):
                raise TypeError("Transcription must return a VoiceInputOperation")
            if self._closed or generation != self._generation:
                operation.cancel()
                return
            self._operation = operation
        except Exception as exc:
            self.cancel()
            self.error.emit(str(exc))

    def stop(self) -> None:
        if self._state != "recording":
            return
        operation = self._operation
        if operation is None:
            return
        self._state = "processing"
        self.changed.emit()
        try:
            operation.stop()
        except Exception as exc:
            self.cancel()
            self.error.emit(str(exc))

    def cancel(self) -> None:
        # Invalidate queued and future notifications before calling plugin code.
        self._generation += 1
        operation, self._operation = self._operation, None
        self._state = "idle"
        if operation is not None:
            try:
                operation.cancel()
            except Exception as exc:
                self.error.emit(str(exc))
        self.changed.emit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.cancel()
        self._provider = None

    @Slot(int, str, str)
    def _receive(self, generation: int, kind: str, value: str) -> None:
        if self._closed or generation != self._generation or not self.active:
            return
        if kind == "text":
            if value:
                self.text_recognized.emit(value)
        elif kind == "finished":
            self._generation += 1
            self._operation = None
            self._state = "idle"
            self.changed.emit()
        elif kind == "error":
            self.cancel()
            self.error.emit(value)
