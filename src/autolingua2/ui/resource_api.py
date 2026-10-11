"""Public runtime interfaces; registration belongs to ExtensionEntrance."""
from collections.abc import Mapping
from typing import Protocol

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from .i18n import LanguageInfo
from .theme import ThemeInfo


class LocalizationAPI(Protocol):
    @property
    def available_languages(self) -> Mapping[str, LanguageInfo]: ...
    def apply_language(self, app: QCoreApplication, language: str) -> None: ...


class ThemeAPI(Protocol):
    def available_themes(self, ui_language: str = "system") -> dict[str, ThemeInfo]: ...
    def apply_theme(self, theme_id: str, app: QApplication | None = None) -> bool: ...
    @property
    def current_theme_id(self) -> str: ...
