"""Public runtime interfaces; registration belongs to ExtensionEntrance."""
from collections.abc import Mapping
from typing import Protocol

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .i18n import LanguageInfo
from .icons import IconSetInfo
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


class IconAPI(Protocol):
    def available_iconsets(self, ui_language: str = "system") -> dict[str, IconSetInfo]: ...
    def set_current_iconset(self, iconset_id: str) -> None: ...
    def get_icon(self, icon_name: str) -> QIcon: ...
    @property
    def current_iconset_id(self) -> str: ...
