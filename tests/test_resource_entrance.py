from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from autolingua2.extensions import ExtensionEntrance, ResourceKind
from autolingua2.plugins.api import PluginContext
from autolingua2.plugins.paradox_yaml.entry import register
from autolingua2.ui.dialogs.settings import SettingsDialogController
from autolingua2.ui.i18n import language_events

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme/themes/system"
ICONS = ROOT / "theme/icons/default"
LANGUAGE = ROOT / "translations/ja_JP"


class ResourceEntranceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        if not isinstance(app, QApplication):
            raise RuntimeError("Tests require QApplication")
        cls.app = app

    def setUp(self) -> None:
        self.entrance = ExtensionEntrance()
        self.addCleanup(self.entrance.close)
        self.addCleanup(lambda: self.app.setStyleSheet(""))

    def test_empty_entrance_does_not_find_installed_resources(self) -> None:
        self.assertFalse(self.entrance.localization.available_languages)
        self.assertFalse(self.entrance.themes.available_themes())
        self.assertFalse(self.entrance.icons.available_iconsets())
        self.assertTrue(self.entrance.icons.get_icon("file").isNull())
        self.assertFalse(self.entrance.plugins.parsers)

    def test_explicit_config_routes_all_four_kinds_without_discovery(self) -> None:
        with patch.object(Path, "iterdir", side_effect=AssertionError("No directory discovery")):
            self.entrance.load_configured(ROOT / "extensions.json")
            self.assertEqual(list(self.entrance.localization.available_languages), ["ja_JP"])
            self.assertEqual(list(self.entrance.themes.available_themes()), ["system"])
            self.assertEqual(list(self.entrance.icons.available_iconsets()), ["default"])
            self.assertEqual(list(self.entrance.plugins.parsers), ["paradox_yaml"])
            self.assertFalse(self.entrance.icons.get_icon("file").isNull())
            self.assertTrue(self.entrance.themes.apply_theme("system", self.app))
        self.assertTrue(self.app.styleSheet())
        self.assertFalse(self.entrance.errors)

    def test_duplicates_preserve_registered_resources(self) -> None:
        resources: tuple[tuple[ResourceKind, Path], ...] = (
            ("ui_translation", LANGUAGE), ("theme", THEME), ("icon_theme", ICONS),
        )
        for kind, path in resources:
            with self.subTest(kind=kind):
                self.entrance.register_resource(kind, path)
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    self.entrance.register_resource(kind, path)
        self.assertEqual(len(self.entrance.localization.available_languages), 1)
        self.assertEqual(len(self.entrance.themes.available_themes()), 1)
        self.assertEqual(len(self.entrance.icons.available_iconsets()), 1)

    def test_bad_entry_does_not_block_other_resource_kinds(self) -> None:
        original = Path.read_text
        config_path = ROOT / "test-extensions.json"
        config = {"extensions": [
            {"kind": "unknown", "path": "."},
            {"kind": "theme", "path": "missing-theme"},
            {"kind": "icon_theme", "path": "theme/icons/default"},
            {"kind": "ui_translation", "path": "translations/ja_JP"},
        ]}

        def read(path: Path, *args, **kwargs) -> str:
            return json.dumps(config) if path == config_path else original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            self.entrance.load_configured(config_path)
        self.assertEqual(len(self.entrance.errors), 2)
        self.assertFalse(self.entrance.themes.available_themes())
        self.assertFalse(self.entrance.icons.get_icon("file").isNull())
        self.assertIn("ja_JP", self.entrance.localization.available_languages)

    def test_resource_id_is_independent_of_directory_and_other_kind(self) -> None:
        original = Path.read_text

        def read(path: Path, *args, **kwargs) -> str:
            content = original(path, *args, **kwargs)
            if path in (ICONS / "iconset.json", THEME / "theme.json"):
                data = json.loads(content)
                data["id"] = "shared"
                return json.dumps(data)
            return content

        with patch.object(Path, "read_text", read):
            self.entrance.register_resource("icon_theme", ICONS)
            self.entrance.register_resource("theme", THEME)
        self.entrance.icons.set_current_iconset("shared")
        self.assertFalse(self.entrance.icons.get_icon("file").isNull())
        self.assertTrue(self.entrance.themes.apply_theme("shared", self.app))
        self.assertEqual(self.entrance.themes.current_theme_id, "shared")
        self.assertEqual(self.entrance.icons.current_iconset_id, "shared")
        self.assertFalse(self.entrance.localization.available_languages)

    def test_registering_icons_invalidates_previous_missing_icon_cache(self) -> None:
        self.assertTrue(self.entrance.icons.get_icon("file").isNull())
        self.entrance.register_resource("icon_theme", ICONS)
        self.assertFalse(self.entrance.icons.get_icon("file").isNull())

    def test_plugin_initial_language_matches_configured_language(self) -> None:
        changes: list[str] = []

        def entry(context: PluginContext) -> None:
            context.on_language_changed(changes.append)
            register(context)

        with patch("autolingua2.plugins.paradox_yaml.entry.register", entry):
            self.entrance.load_configured(ROOT / "extensions.json", ui_language="en_US")
        self.assertFalse(self.entrance.errors)
        self.assertEqual(changes, ["en_US"])

    def test_localization_notifies_plugins_without_main_window_and_closes_once(self) -> None:
        self.entrance.register_resource("ui_translation", LANGUAGE)
        self.assertTrue(self.entrance.register_plugin("paradox_yaml", register))
        changes: list[str] = []
        self.entrance.plugins.context("paradox_yaml").on_language_changed(changes.append)
        self.entrance.localization.apply_language(self.app, "en_US")
        self.assertEqual(changes, ["en_US"])
        self.entrance.localization.apply_language(self.app, "ja_JP")
        self.assertEqual(changes, ["en_US", "ja_JP"])
        self.assertEqual(list(self.entrance.localization.available_languages), ["ja_JP"])
        self.entrance.close()
        self.entrance.close()
        language_events().changed.emit("en_US")
        self.assertEqual(changes, ["en_US", "ja_JP"])
        with self.assertRaises(RuntimeError):
            self.entrance.register_resource("theme", THEME)

    def test_settings_uses_same_managers_and_does_not_discover_resources(self) -> None:
        self.entrance.load_configured(ROOT / "extensions.json")
        with patch.dict(os.environ, {"AUTOLINGUA_SETTINGS_PATH": str(ROOT / "tests/fixtures/absent-settings.json")}), \
             patch.object(Path, "iterdir", side_effect=AssertionError("Settings cannot discover resources")):
            dialog = SettingsDialogController(self.entrance)
        try:
            self.assertIs(dialog.icon_manager, self.entrance.icons)
            self.assertIs(dialog.theme_manager, self.entrance.themes)
            self.assertIs(dialog.localization, self.entrance.localization)
            self.assertEqual(dialog.list_themes.count(), 1)
            self.assertEqual(dialog.list_icon_themes.count(), 1)
        finally:
            dialog.dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
