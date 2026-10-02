"""Application composition boundary: one entrance, independent managers."""
from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import Literal

from .ir.validation import array, record, required, text
from .plugins.api import PluginContext
from .plugins.manager import PluginManager
from .ui.i18n import LocalizationManager, current_ui_language, language_events
from .ui.icons import IconManager
from .ui.theme import ThemeManager
from .ui.resource_api import IconAPI, LocalizationAPI, ThemeAPI

ResourceKind = Literal["ui_translation", "theme", "icon_theme"]
logger = logging.getLogger(__name__)


class ExtensionEntrance:
    """Routes admission only; consumers call each manager's public API directly."""

    def __init__(self) -> None:
        self._plugins = PluginManager(current_ui_language())
        self._localization = LocalizationManager()
        self._themes = ThemeManager()
        self._icons = IconManager()
        self._errors: list[str] = []
        self._closed = False
        language_events().changed.connect(self._plugins.change_language)

    @property
    def plugins(self) -> PluginManager:
        return self._plugins

    @property
    def localization(self) -> LocalizationAPI:
        return self._localization

    @property
    def themes(self) -> ThemeAPI:
        return self._themes

    @property
    def icons(self) -> IconAPI:
        return self._icons

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors) + self._plugins.errors

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Extension entrance is closed")

    def register_plugin(self, plugin_id: str, entry: Callable[[PluginContext], None]) -> bool:
        self._ensure_open()
        return self._plugins._load(plugin_id, entry)

    def register_resource(self, kind: ResourceKind, path: Path) -> None:
        self._ensure_open()
        if kind == "ui_translation":
            self._localization._register(path)
        elif kind == "theme":
            self._themes._register(path)
        elif kind == "icon_theme":
            self._icons._register(path)
        else:
            raise ValueError(f"Unknown resource kind: {kind}")

    def _report_error(self, label: str, error: Exception) -> None:
        message = f"{label}: {type(error).__name__}: {error}"
        self._errors.append(message)
        logger.error("Extension registration failure: %s", message)

    def load_configured(
        self, config_path: Path, check: Callable[[], None] | None = None,
        *, ui_language: str | None = None,
    ) -> None:
        self._ensure_open()
        try:
            config = record(json.loads(config_path.read_text(encoding="utf-8")))
            entries = array(required(config, "extensions"))
        except Exception as exc:
            self._report_error(str(config_path), exc)
            return
        plugins: list[dict[str, object]] = []
        for index, value in enumerate(entries):
            if check is not None:
                check()
            try:
                item = record(value)
                kind = text(required(item, "kind"), nonempty=True)
                if kind in ("python", "executable"):
                    plugins.append(item)
                elif kind in ("ui_translation", "theme", "icon_theme"):
                    path = config_path.parent / text(required(item, "path"), nonempty=True)
                    self.register_resource(kind, path.resolve())
                else:
                    raise ValueError(f"Unknown extension kind: {kind}")
            except Exception as exc:
                self._report_error(f"extensions[{index}]", exc)
        # Resolve system language against registered dictionaries before plugin callbacks.
        if ui_language is not None:
            self._plugins.change_language(self._localization.resolve_language(ui_language))
        for item in plugins:
            if check is not None:
                check()
            try:
                self._plugins._load_configured(item, config_path.parent)
            except Exception as exc:
                self._report_error(str(item.get("id", "plugin")), exc)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        language_events().changed.disconnect(self._plugins.change_language)
        self._plugins.close()
        self._localization.close()
