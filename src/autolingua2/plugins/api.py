"""Public registration context and UI-capable plugin API."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .contracts import FileAdapter, AiProviderPlugin
from autolingua2.infrastructure.encoding import read_text_lossless
from autolingua2.ui.creation_contract import CreationActions, CreationAdapter, CreationContext

__all__ = ["PluginContext", "PluginContribution", "FileAccess", "CreationAdapter", "CreationContext"]


@dataclass(frozen=True)
class FileAccess:
    read_text_lossless: Callable[[Path], str]


@dataclass(frozen=True)
class PluginContribution:
    id: str
    parser: FileAdapter | None = None
    provider: AiProviderPlugin | None = None
    ui: CreationAdapter | None = None


class PluginContext:
    """The only host API supplied to a plugin, retained for its entire lifetime."""
    def __init__(self, plugin_id: str, language: str) -> None:
        self.id = plugin_id
        self._language = language
        self.files = FileAccess(read_text_lossless)
        self._contribution: PluginContribution | None = None
        self._accepting = True
        self._closed = False
        self._creation: CreationActions | None = None
        self._language_callbacks: list[Callable[[str], None]] = []
        self._close_callbacks: list[Callable[[], None]] = []

    def register(self, contribution: PluginContribution) -> None:
        if not self._accepting or self._contribution is not None:
            raise ValueError("A plugin must register exactly once during entry")
        if not isinstance(contribution, PluginContribution) or contribution.id != self.id:
            raise ValueError("Plugin ID does not match the configured ID")
        self._contribution = contribution

    @property
    def ui_language(self) -> str:
        return self._language

    @property
    def creation(self) -> CreationContext:
        if self._closed or self._creation is None:
            raise RuntimeError("Project creation API is not active for this plugin")
        return self._creation

    def on_language_changed(self, callback: Callable[[str], None]) -> None:
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        self._language_callbacks.append(callback)

    def on_close(self, callback: Callable[[], None]) -> None:
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        self._close_callbacks.append(callback)

    def _change_language(self, language: str) -> None:
        self._language = language
        for callback in tuple(self._language_callbacks):
            callback(language)

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._accepting = False
        self._creation = None
        self._language_callbacks.clear()
        errors: list[str] = []
        for callback in reversed(self._close_callbacks):
            try:
                callback()
            except Exception as exc:
                errors.append(str(exc))
        self._close_callbacks.clear()
        if errors:
            raise RuntimeError("; ".join(errors))
