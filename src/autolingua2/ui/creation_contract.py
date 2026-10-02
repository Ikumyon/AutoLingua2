from __future__ import annotations

from pathlib import Path
from typing import Protocol, TYPE_CHECKING, runtime_checkable
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from autolingua2.plugins.api import PluginContext


class CreationContext(Protocol):
    def cancel_operation(self) -> None:
        ...

    def add_target_path(self, path: Path, /) -> None:
        ...

    def remove_target_path(self, path: Path, /) -> None:
        ...

    def set_project_name(self, name: str, /) -> None:
        ...

    def select_game(self, game_id: str, /) -> None:
        ...

    def set_source_language(self, lang_code: str, /) -> None:
        ...

    def set_target_slot(self, slot_code: str, /) -> None:
        ...

    def get_icon(self, name: str, /) -> QIcon:
        ...


@dataclass(frozen=True)
class CreationActions:
    """Only supported actions, never the host window or its controller."""
    cancel_operation: Callable[[], None]
    add_target_path: Callable[[Path], None]
    remove_target_path: Callable[[Path], None]
    set_project_name: Callable[[str], None]
    select_game: Callable[[str], None]
    set_source_language: Callable[[str], None]
    set_target_slot: Callable[[str], None]
    get_icon: Callable[[str], QIcon]


@runtime_checkable
class CreationAdapter(Protocol):
    """UI-only extension; independent of the file parser contract."""

    def create_creation_panel(self, context: PluginContext) -> QWidget:
        ...

    def on_paths_dropped(self, paths: list[Path], context: PluginContext) -> list[Path]:
        ...

    def on_game_selected(self, game_id: str, context: PluginContext) -> None:
        ...

    def format_target_path_label(self, path: Path, current_source_lang: str) -> tuple[str, str, str]:
        ...

    def dispose_creation_panel(self, panel: QWidget) -> None:
        ...

