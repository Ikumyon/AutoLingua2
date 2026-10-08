from __future__ import annotations

from pathlib import Path
from typing import Protocol, TYPE_CHECKING, runtime_checkable
from collections.abc import Callable
from dataclasses import dataclass

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

class CreationActions:
    """Only supported actions, never the host window or its controller."""

    def __init__(
        self,
        cancel_operation: Callable[[], None],
        add_target_path: Callable[[Path], None],
        remove_target_path: Callable[[Path], None],
        set_project_name: Callable[[str], None],
        select_game: Callable[[str], None],
        set_source_language: Callable[[str], None],
        set_target_slot: Callable[[str], None],
    ) -> None:
        self._cancel_operation = cancel_operation
        self._add_target_path = add_target_path
        self._remove_target_path = remove_target_path
        self._set_project_name = set_project_name
        self._select_game = select_game
        self._set_source_language = set_source_language
        self._set_target_slot = set_target_slot

    def cancel_operation(self) -> None:
        self._cancel_operation()

    def add_target_path(self, path: Path, /) -> None:
        self._add_target_path(path)

    def remove_target_path(self, path: Path, /) -> None:
        self._remove_target_path(path)

    def set_project_name(self, name: str, /) -> None:
        self._set_project_name(name)

    def select_game(self, game_id: str, /) -> None:
        self._select_game(game_id)

    def set_source_language(self, lang_code: str, /) -> None:
        self._set_source_language(lang_code)

    def set_target_slot(self, slot_code: str, /) -> None:
        self._set_target_slot(slot_code)

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

