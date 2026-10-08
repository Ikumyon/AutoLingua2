"""Public registration context and UI-capable plugin API."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from PySide6.QtGui import QIcon, QSyntaxHighlighter, QTextDocument
from PySide6.QtWidgets import QWidget

from .contracts import FileAdapter, AiProviderPlugin, TranslationExporter, ImportedTranslation, VoiceInputProvider
from autolingua2.infrastructure.encoding import read_text_auto
from autolingua2.infrastructure.platform import current_platform
from autolingua2.services.settings_store import load_plugin_settings, save_plugin_settings
from autolingua2.ui.creation_contract import CreationAdapter, CreationContext

__all__ = [
    "PluginContext",
    "PluginContribution",
    "FileAccess",
    "SystemVoiceInputAccess",
    "CreationAdapter",
    "CreationContext",
    "HighlighterFactory",
    "SettingsPageProvider",
    "GameTextPresentation",
    "NewlineCodec",
    "PluginSettings",
    "UIContribution",
    "ExportSettingsPanel",
]

HighlighterFactory = Callable[[str, QTextDocument, Callable[[], bool], Callable[[], bool]], QSyntaxHighlighter | None]


@dataclass(frozen=True)
class NewlineCodec:
    """Display conversion supplied by a game; absent means identity conversion."""

    expand: Callable[[str], str]
    collapse: Callable[[str], str]


@dataclass(frozen=True)
class GameTextPresentation:
    """Game capabilities and a stable link to the plugin's settings page."""

    newline_codec: NewlineCodec | None = None
    highlight_tags: bool = False
    apply_colors: bool = False
    settings_page_id: str | None = None
    settings_label: str = ""


@dataclass(frozen=True)
class PluginSettings:
    """Settings access bound to the registering plugin, never another plugin ID."""

    load: Callable[[], dict[str, object]]
    save: Callable[[dict[str, object]], None]


@runtime_checkable
class SettingsPageProvider(Protocol):
    """プラグインが本体設定ダイアログに提供する設定ページの公開契約。"""

    @property
    def id(self) -> str:
        """設定ページの固有ID。"""
        ...

    @property
    def title(self) -> str:
        """設定ダイアログのカテゴリ一覧に表示されるタイトル。"""
        ...

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """設定ページ用のウィジェットを生成して返す。"""
        ...

    def save_settings(self, widget: QWidget) -> None:
        """設定ダイアログで保存が実行された際に呼び出される保存処理。"""
        ...


@runtime_checkable
class ExportSettingsPanel(Protocol):
    def create_widget(self, workspaces: list[ImportedTranslation], parent: QWidget) -> QWidget:
        ...

    def read_settings(self, widget: QWidget) -> dict[str, object]:
        """Validate input and return worker-safe settings, raising ValueError on invalid input."""
        ...


@dataclass(frozen=True)
class UIContribution:
    """プラグインが4F（UI層）に提供する拡張機能コンテナ。"""

    creation_panel: CreationAdapter | None = None
    chat_icon: Callable[[], QIcon] | None = None
    settings_pages: list[SettingsPageProvider] = field(default_factory=list)
    text_presentation: Callable[[str], GameTextPresentation | None] | None = None
    highlighter_factory: HighlighterFactory | None = None
    export_settings: dict[str, ExportSettingsPanel] = field(default_factory=dict)


@dataclass(frozen=True)
class FileAccess:
    read_text_auto: Callable[[Path], tuple[str, str]]


@dataclass(frozen=True)
class SystemVoiceInputAccess:
    """OS-independent host entry to the platform's standard voice input."""

    is_available: Callable[[], bool]
    start: Callable[[], None]


@dataclass(frozen=True)
class PluginContribution:
    id: str
    parser: FileAdapter | None = None
    provider: AiProviderPlugin | None = None
    ui: UIContribution | None = None
    exporters: list[TranslationExporter] = field(default_factory=list)
    voice_input: VoiceInputProvider | None = None


class PluginContext:
    """The only host API supplied to a plugin, retained for its entire lifetime."""
    def __init__(self, plugin_id: str, language: str,
                 display_changed: Callable[[str], None] | None = None,
                 *, get_icon: Callable[[str], QIcon]) -> None:
        self.id = plugin_id
        self._get_icon = get_icon
        self._language = language
        self.files = FileAccess(read_text_auto)
        self.settings = PluginSettings(self._load_settings, self._save_settings)
        self.system_voice_input = SystemVoiceInputAccess(
            self._system_voice_input_available, self._start_system_voice_input,
        )
        self._display_changed = display_changed
        self._contribution: PluginContribution | None = None
        self._accepting = True
        self._closed = False
        self._creation: CreationContext | None = None
        self._language_callbacks: list[Callable[[str], None]] = []
        self._close_callbacks: list[Callable[[], None]] = []

    def get_icon(self, name: str, /) -> QIcon:
        """Obtain a host icon for any plugin UI using the current icon set."""
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        return self._get_icon(name)

    def _system_voice_input_available(self) -> bool:
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        return current_platform.system_voice_input_available()

    def _start_system_voice_input(self) -> None:
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        current_platform.start_system_voice_input()

    def _load_settings(self) -> dict[str, object]:
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        return load_plugin_settings(self.id)

    def _save_settings(self, data: dict[str, object]) -> None:
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        save_plugin_settings(self.id, data)

    def notify_display_changed(self) -> None:
        if self._closed:
            raise RuntimeError("Plugin context is closed")
        if self._display_changed is not None:
            self._display_changed(self.id)

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
        self._display_changed = None
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
