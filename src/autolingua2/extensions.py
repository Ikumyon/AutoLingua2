"""Application composition boundary: one entrance, independent managers."""
from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import Literal

from .ir.validation import record, required, text
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
        self._icons = IconManager()
        self._plugins = PluginManager(current_ui_language(), self._icons.get_icon)
        self._localization = LocalizationManager()
        self._themes = ThemeManager()
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

    def _load_plugin_folder(
        self, folder: Path, check: Callable[[], None] | None = None,
        *, builtin: bool = False,
    ) -> None:
        manifest_file = folder / "manifest.json"
        if not folder.is_dir() or not manifest_file.is_file():
            return
        if check is not None:
            check()
        try:
            manifest = record(json.loads(manifest_file.read_text(encoding="utf-8")))
            plugin_id = text(required(manifest, "id"), nonempty=True)
            kind = text(manifest.get("kind", "python"), nonempty=True)
            config_item: dict[str, object] = {
                "id": plugin_id,
                "kind": kind,
            }
            if kind == "executable":
                config_item["manifest"] = str(manifest_file.resolve())
            elif kind == "python":
                entry_file = Path(text(manifest.get("entry", "entry.py"), nonempty=True))
                entry_path = (folder / entry_file).resolve()
                if entry_file.is_absolute() or not entry_path.is_relative_to(folder.resolve()):
                    raise ValueError("Entry must be inside its plugin folder")
                if builtin:
                    parts = (folder.name, *entry_file.with_suffix("").parts)
                    if entry_file.suffix != ".py" or any(not part.isidentifier() for part in parts):
                        raise ValueError("Invalid builtin Python entry")
                    config_item["module"] = "autolingua2.plugins." + ".".join(parts)
                else:
                    config_item["path"] = str(entry_path)
            else:
                raise ValueError(f"Unknown plugin kind: {kind}")
            self._plugins._load_configured(config_item, folder.resolve())
        except Exception as exc:
            self._report_error(f"plugin:{folder.name}", exc)

    def load_all(
        self, root_dir: Path, check: Callable[[], None] | None = None,
        *, ui_language: str | None = None,
    ) -> None:
        """名刺（マニフェスト）を持つ内蔵/外部リソースおよびプラグインを自動探索してロードします。"""
        self._ensure_open()

        # 1. UI翻訳リソースの自動探索 (translations/*/metadata.json)
        translations_dir = root_dir / "translations"
        if translations_dir.is_dir():
            for folder in sorted(translations_dir.iterdir()):
                if folder.is_dir() and (folder / "metadata.json").is_file():
                    if check is not None:
                        check()
                    try:
                        self.register_resource("ui_translation", folder.resolve())
                    except Exception as exc:
                        self._report_error(f"translations/{folder.name}", exc)

        # 2. テーマリソースの自動探索 (theme/themes/*/theme.json)
        themes_dir = root_dir / "theme" / "themes"
        if themes_dir.is_dir():
            for folder in sorted(themes_dir.iterdir()):
                if folder.is_dir() and (folder / "theme.json").is_file():
                    if check is not None:
                        check()
                    try:
                        self.register_resource("theme", folder.resolve())
                    except Exception as exc:
                        self._report_error(f"theme/themes/{folder.name}", exc)

        # 3. アイコンリソースの自動探索 (theme/icons/*/iconset.json)
        icons_dir = root_dir / "theme" / "icons"
        if icons_dir.is_dir():
            for folder in sorted(icons_dir.iterdir()):
                if folder.is_dir() and (folder / "iconset.json").is_file():
                    if check is not None:
                        check()
                    try:
                        self.register_resource("icon_theme", folder.resolve())
                    except Exception as exc:
                        self._report_error(f"theme/icons/{folder.name}", exc)

        # 4. プラグインのコールバック前に言語を解決
        if ui_language is not None:
            self._plugins.change_language(self._localization.resolve_language(ui_language))

        # 5. 内蔵プラグインの自動探索 (src/autolingua2/plugins/*/manifest.json)
        builtin_plugins_dir = Path(__file__).parent / "plugins"
        if builtin_plugins_dir.is_dir():
            for folder in sorted(builtin_plugins_dir.iterdir()):
                self._load_plugin_folder(folder, check, builtin=True)

        # 6. 外部プラグインの自動探索 (plugins/*/manifest.json)
        external_plugins_dir = root_dir / "plugins"
        if external_plugins_dir.is_dir() and external_plugins_dir != builtin_plugins_dir:
            for folder in sorted(external_plugins_dir.iterdir()):
                # 既に内蔵で読み込み済みのID等があれば PluginManager 側で重複排除
                self._load_plugin_folder(folder, check)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        language_events().changed.disconnect(self._plugins.change_language)
        self._plugins.close()
        self._localization.close()
