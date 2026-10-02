from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from autolingua2.infrastructure.operations import OperationCancelled
from autolingua2.ir import TranslationProject, TranslationUnit
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.plugins.api import PluginContext, PluginContribution
from autolingua2.extensions import ExtensionEntrance
from autolingua2.plugins.paradox_yaml.entry import register
from autolingua2.plugins.paradox_yaml.parser import ParadoxYamlAdapter
from autolingua2.plugins.paradox_yaml.ui.panel import ParadoxCreationPanel
from autolingua2.plugins.paradox_yaml.ui.translations import PluginTranslations
from autolingua2.ui.creation_panel import CommonCreationPanel
from autolingua2.ui.i18n import language_events
from autolingua2.ui.main_window import MainWindowController

ROOT = Path(__file__).resolve().parents[1]


class EntranceTests(unittest.TestCase):
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
        self.runtime = self.entrance.plugins
        self.addCleanup(self.entrance.close)

    def configured(self, entries: list[object]) -> None:
        config_path = ROOT / "tests" / "fixtures" / "extensions.json"
        original_read = Path.read_text

        def read(path: Path, *args, **kwargs) -> str:
            if path == config_path:
                return json.dumps({"extensions": entries})
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", read), \
             patch.object(Path, "iterdir", side_effect=AssertionError("Plugin scanning is forbidden")):
            self.entrance.load_configured(config_path)

    def test_default_config_loads_paradox_through_entrance(self) -> None:
        with patch.object(Path, "iterdir", side_effect=AssertionError("No scanning")):
            self.entrance.load_configured(ROOT / "extensions.json")
        self.assertEqual(list(self.runtime.parsers), ["paradox_yaml"])
        self.assertEqual(list(self.runtime.ui_extensions), ["paradox_yaml"])
        self.assertFalse(self.runtime.errors)

    def test_only_explicit_python_entries_load_and_relative_imports_work(self) -> None:
        self.configured([{"id": "example", "kind": "python", "path": "external_entry.py"}])
        self.assertFalse(self.runtime.errors)
        self.assertEqual(list(self.runtime.providers.providers), ["example"])
        self.assertFalse(self.runtime.parsers)
        self.assertFalse(hasattr(self.runtime.providers, "register"))

    def test_duplicate_fails_before_entry_and_preserves_first(self) -> None:
        self.assertTrue(self.entrance.register_plugin("paradox_yaml", register))
        parser = self.runtime.parsers["paradox_yaml"]
        with patch("autolingua2.plugins.paradox_yaml.entry.ParadoxYamlAdapter") as constructor:
            self.assertFalse(self.entrance.register_plugin("paradox_yaml", register))
            constructor.assert_not_called()
        self.assertIs(self.runtime.parsers["paradox_yaml"], parser)

    def test_initial_language_failure_prevents_publication(self) -> None:
        closed: list[bool] = []

        def fail(language: str) -> None:
            raise ValueError("Bad translation resource")

        def entry(context: PluginContext) -> None:
            context.on_close(lambda: closed.append(True))
            context.on_language_changed(fail)
            context.register(PluginContribution(context.id, parser=ParadoxYamlAdapter(context.files.read_text_lossless)))

        self.assertFalse(self.entrance.register_plugin("paradox_yaml", entry))
        self.assertFalse(self.runtime.parsers)
        self.assertEqual(closed, [True])

    def test_no_configuration_does_not_silently_load_bundled_plugin(self) -> None:
        self.entrance.load_configured(ROOT / "tests/fixtures/missing-config.json")
        self.assertFalse(self.runtime.parsers)
        self.assertEqual(len(self.entrance.errors), 1)

    def test_entry_cannot_register_twice(self) -> None:
        def entry(context: PluginContext) -> None:
            contribution = PluginContribution(context.id, parser=ParadoxYamlAdapter(context.files.read_text_lossless))
            context.register(contribution)
            context.register(contribution)

        self.assertFalse(self.entrance.register_plugin("paradox_yaml", entry))
        self.assertFalse(self.runtime.parsers)

    def test_failed_registration_rolls_back_callbacks_and_capabilities(self) -> None:
        closed: list[str] = []
        changes: list[str] = []

        def failing(context: PluginContext) -> None:
            context.on_close(lambda: closed.append("closed"))
            context.on_language_changed(changes.append)
            context.register(PluginContribution(context.id, parser=ParadoxYamlAdapter(context.files.read_text_lossless)))
            raise RuntimeError("Entry failure")

        self.assertFalse(self.entrance.register_plugin("paradox_yaml", failing))
        self.assertFalse(self.runtime.parsers)
        self.runtime.change_language("en_US")
        self.assertEqual(closed, ["closed"])
        self.assertEqual(changes, [])

    def test_invalid_and_missing_registration_are_rejected(self) -> None:
        self.assertFalse(self.entrance.register_plugin("none", lambda context: None))
        self.assertFalse(self.entrance.register_plugin("empty", lambda context: context.register(PluginContribution("empty"))))
        self.assertFalse(self.entrance.register_plugin("mismatch", lambda context: context.register(PluginContribution("other"))))
        self.assertFalse(self.runtime.parsers)
        self.assertEqual(len(self.runtime.errors), 3)

    def test_bad_entry_does_not_prevent_next_plugin(self) -> None:
        self.configured([
            {"id": "broken", "kind": "python", "path": "missing.py"},
            {"id": "example", "kind": "python", "path": "external_entry.py"},
        ])
        self.assertEqual(len(self.runtime.errors), 1)
        self.assertIn("example", self.runtime.providers.providers)

    def test_language_and_cleanup_use_context_without_a_panel(self) -> None:
        changes: list[str] = []
        closed: list[str] = []

        def entry(context: PluginContext) -> None:
            context.on_language_changed(changes.append)
            context.on_close(lambda: closed.append("closed"))
            context.register(PluginContribution(context.id, parser=ParadoxYamlAdapter(context.files.read_text_lossless)))

        self.assertTrue(self.entrance.register_plugin("paradox_yaml", entry))
        context = self.runtime.context("paradox_yaml")
        self.assertEqual(changes, ["ja_JP"])
        self.runtime.change_language("en_US")
        self.assertEqual(context.ui_language, "en_US")
        self.assertEqual(changes, ["ja_JP", "en_US"])
        self.runtime.close()
        self.runtime.change_language("ja_JP")
        self.assertEqual(closed, ["closed"])
        self.assertEqual(changes, ["ja_JP", "en_US"])
        with self.assertRaises(RuntimeError):
            _ = context.creation

    def test_paradox_owns_dictionary_loading_and_disposal(self) -> None:
        module = "autolingua2.plugins.paradox_yaml.ui.translations"
        translations = PluginTranslations()
        with patch.object(Path, "is_file", return_value=True), \
             patch(module + ".QTranslator") as factory, \
             patch(module + ".QCoreApplication.installTranslator", return_value=True) as install, \
             patch(module + ".QCoreApplication.removeTranslator") as remove:
            translator = factory.return_value
            translator.load.return_value = True
            translations.change_language("en_US")
            filename = translator.load.call_args.args[0]
            self.assertEqual(Path(filename).name, "en_US.qm")
            self.assertEqual(Path(filename).parent.parent.name, "paradox_yaml")
            install.assert_called_once_with(translator)
            translations.close()
            remove.assert_called_once_with(translator)
            translator.deleteLater.assert_called_once()

    def test_language_failure_is_reported_and_other_plugins_receive_event(self) -> None:
        changes: list[str] = []

        def fail_later(language: str) -> None:
            if language == "en_US":
                raise ValueError("translation failed")

        def entry(context: PluginContext) -> None:
            context.on_language_changed(fail_later)
            context.register(PluginContribution(context.id, parser=ParadoxYamlAdapter(context.files.read_text_lossless)))

        self.entrance.register_plugin("paradox_yaml", entry)
        self.configured([{"id": "example", "kind": "python", "path": "external_entry.py"}])
        self.runtime.context("example").on_language_changed(changes.append)
        self.runtime.change_language("en_US")
        self.assertEqual(changes, ["en_US"])
        self.assertEqual(len(self.runtime.errors), 1)

    def test_executable_registration_uses_same_entrance(self) -> None:
        manifest = {"protocol_version": 1, "id": "paradox_yaml",
                    "executables": {"test": {"path": "plugin.exe", "args": []}}}
        registration = {"id": "paradox_yaml", "parser": {
            "name": "Test", "suffixes": [".json"], "supported_languages": [["en", "English"]],
            "supported_games": [{"id": "json", "name": "JSON", "slots": [], "default_slot_id": ""}],
        }}
        with patch("autolingua2.adapters.executable.current_platform.plugin_platform_key", return_value="test"), \
             patch("autolingua2.plugins.manager._resolve", return_value=ROOT / "fake-plugin.json"), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_text", return_value=json.dumps(manifest)), \
             patch("autolingua2.adapters.executable.PluginRPC") as rpc:
            rpc.return_value.call.return_value = registration
            # The config reader is patched separately; the manifest reader remains in effect.
            self.configured([{"id": "paradox_yaml", "kind": "executable", "manifest": "fake-plugin.json"}])
            rpc.return_value.call.assert_called_once_with("register", {})
        self.assertIn("paradox_yaml", self.runtime.parsers)
        self.assertFalse(self.runtime.errors)

    def test_paradox_and_parser_only_use_plugin_and_common_panels(self) -> None:
        for with_ui in (True, False):
            with self.subTest(with_ui=with_ui):
                entrance = ExtensionEntrance()
                runtime = entrance.plugins
                entry = register if with_ui else lambda context: context.register(
                    PluginContribution(context.id, parser=ParadoxYamlAdapter(context.files.read_text_lossless)))
                self.assertTrue(entrance.register_plugin("paradox_yaml", entry))
                with patch.dict(os.environ, {"AUTOLINGUA_SETTINGS_PATH": str(ROOT / "tests/fixtures/absent-settings.json")}), \
                     patch("autolingua2.ui.main_window.save_ai_settings"), \
                     patch("autolingua2.ui.main_window.save_window_layout"), \
                     patch("autolingua2.ui.main_window.save_translation_table_columns"), \
                     patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok) as warning:
                    controller = MainWindowController(entrance)
                    try:
                        self.assertIsInstance(controller.active_creation_panel,
                                              ParadoxCreationPanel if with_ui else CommonCreationPanel)
                        self.assertTrue(controller._panel_valid)
                        controller.select_game_by_id("hoi4", "paradox_yaml")
                        controller._on_ui_language_changed("en_US")
                        self.assertFalse(hasattr(runtime.context("paradox_yaml").creation, "parent_widget"))
                        warning.assert_not_called()
                    finally:
                        language_events().changed.disconnect(controller._on_ui_language_changed)
                        controller.window.close()
                        controller.window.deleteLater()
                        entrance.close()

    def test_restart_save_success_cancel_and_failure(self) -> None:
        self.assertTrue(self.entrance.register_plugin("paradox_yaml", register))
        with patch.dict(os.environ, {"AUTOLINGUA_SETTINGS_PATH": str(ROOT / "tests/fixtures/absent-settings.json")}), \
             patch("autolingua2.ui.main_window.save_ai_settings"), \
             patch("autolingua2.ui.main_window.save_window_layout"), \
             patch("autolingua2.ui.main_window.save_translation_table_columns"):
            controller = MainWindowController(self.entrance)
            try:
                project = TranslationProject(adapter_id="paradox_yaml",
                    units=[TranslationUnit("unit", "key", "source", "translated")])
                controller.imported = ImportedTranslation(project)
                controller.project = project
                controller.units = project.units
                controller._restart_target = True
                with patch.object(QFileDialog, "getExistingDirectory", return_value=""), \
                     patch.object(controller, "_run_operation") as run:
                    controller.save_translation()
                    run.assert_not_called()
                    self.assertIsNone(controller._restart_target)

                controller._restart_target = True
                with patch.object(QFileDialog, "getExistingDirectory", return_value=str(ROOT)), \
                     patch.object(controller, "_run_operation") as run, \
                     patch("autolingua2.ui.main_window.export_translation", return_value=[]) as export, \
                     patch.object(controller.window, "close") as close:
                    controller.save_translation()
                    operation, completed = run.call_args.args
                    self.assertEqual(controller._saved_targets, [])
                    close.assert_not_called()
                    completed(operation())
                    export.assert_called_once()
                    self.assertIsNot(export.call_args.args[0], controller.imported)
                    self.assertEqual(controller._saved_targets, [("unit", "translated")])
                    close.assert_called_once()

                for error in (OSError("save failed"), OperationCancelled("cancelled")):
                    controller._restart_target = True
                    controller._close_after_io = True
                    controller.io_worker = Mock(error=error)
                    controller._operation_dialog = Mock()
                    with patch.object(controller.window, "close") as close, \
                         patch.object(QMessageBox, "warning"):
                        controller._operation_finished()
                        self.assertIsNone(controller._restart_target)
                        close.assert_not_called()
            finally:
                controller._restart_target = None
                controller.io_worker = None
                language_events().changed.disconnect(controller._on_ui_language_changed)
                controller.window.close()
                controller.window.deleteLater()


if __name__ == "__main__":
    unittest.main()
