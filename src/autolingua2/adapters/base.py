from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QWidget

from autolingua2.ir import TranslationProject


@dataclass(slots=True)
class SourceRef:
    source_id: str
    external_id: str
    location: str = ""
    data: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ImportedTranslation:
    project: TranslationProject
    source_refs: dict[str, SourceRef] = field(default_factory=dict)


@dataclass(slots=True)
class GameProfile:
    id: str
    name: str
    available_slots: list[tuple[str, str]]
    default_slot: str = ""


class CreationContext(Protocol):
    def cancel_operation(self) -> None:
        ...

    def add_target_path(self, path: Path) -> None:
        ...

    def remove_target_path(self, path: Path) -> None:
        ...

    def set_project_name(self, name: str) -> None:
        ...

    def select_game(self, game_id: str) -> None:
        ...

    def set_source_language(self, lang_code: str) -> None:
        ...

    def set_target_slot(self, slot_code: str) -> None:
        ...

    def get_icon(self, name: str) -> QIcon:
        ...

    @property
    def parent_widget(self) -> QWidget:
        ...

    @property
    def current_ui_language(self) -> str:
        ...


class FileAdapter(Protocol):
    id: str
    name: str
    suffixes: set[str]
    supported_languages: list[tuple[str, str]]
    default_filter_rules: list[Any]

    def can_load(self, path: Path) -> bool:
        ...

    def load(self, path: Path) -> ImportedTranslation:
        ...

    def save(self, path: Path, imported: ImportedTranslation, project: TranslationProject,
             existing: ImportedTranslation | None = None) -> None:
        ...

    def output_name(self, path: Path, project: TranslationProject) -> str:
        ...

    def detect_source_language(self, path: Path) -> str | None:
        ...

    def filter_source_files(self, paths: list[Path], current_source_lang: str) -> list[Path]:
        ...


class CreationAdapter(Protocol):
    """GUI hooks must not perform recursive IO. Drop hooks return unhandled paths."""
    supported_games: list[GameProfile]

    def create_creation_panel(self, context: CreationContext) -> QWidget:
        ...

    def on_paths_dropped(self, paths: list[Path], context: CreationContext) -> list[Path]:
        ...

    def on_game_selected(self, game_id: str, context: CreationContext) -> None:
        ...

    def format_target_path_label(self, path: Path, current_source_lang: str) -> tuple[str, str, str]:
        ...

    def dispose_creation_panel(self, panel: QWidget) -> None:
        ...

    def on_ui_language_changed(self, language_code: str, context: CreationContext) -> None:
        ...


class PluginAdapter(FileAdapter, CreationAdapter, Protocol):
    """Registered plugins implement both contracts; file IO remains Qt independent."""


class QtTranslationProvider(Protocol):
    """Optional opt-in. Paths and locale fallback belong to the plugin."""
    def qt_translation_files(self, language_code: str) -> list[Path]:
        ...

