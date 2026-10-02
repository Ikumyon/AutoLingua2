from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import Mock, patch
from typing import TYPE_CHECKING

from autolingua2.adapters.base import FileAdapter
from autolingua2.adapters.executable import ExecutableAdapter
from autolingua2.plugins.paradox_yaml.parser import ParadoxYamlAdapter
from autolingua2.plugins.paradox_yaml.parser.writer import render_translation_file
from autolingua2.adapters.validation import validate_adapter
from autolingua2.infrastructure.platform.base import PlatformDriver
from autolingua2.ir import Issue, TranslationProject, TranslationSource, TranslationUnit, UnitState
from autolingua2.ir.filter_rules import AdapterFilterConfig, FilterRule, should_hide_unit
from autolingua2.ir.imported import ImportedTranslation, SourceRef
from autolingua2.ir.serialization import imported_from_dict
from autolingua2.ir.validation import array, record

if TYPE_CHECKING:
    from autolingua2.ui.creation_contract import CreationAdapter
    from autolingua2.ui.creation_panel import CommonCreationAdapter
    from autolingua2.plugins.paradox_yaml.ui.panel import ParadoxCreationAdapter

    def check_contracts(executable: ExecutableAdapter) -> None:
        parsers: list[FileAdapter] = [ParadoxYamlAdapter(lambda path: ""), executable]
        extensions: list[CreationAdapter] = [ParadoxCreationAdapter(), CommonCreationAdapter()]
        assert parsers and extensions


def sample() -> ImportedTranslation:
    return ImportedTranslation(
        TranslationProject(
            name="Example", source_language="en_US", target_language="ja_JP",
            target_file_language="l_japanese", adapter_id="paradox_yaml",
            sources=[TranslationSource("source", "example.yml", [Issue("source warning")])],
            units=[TranslationUnit(
                "unit", "key", "Hello", "こんにちは", "context", UnitState.DOUBTFUL,
                [Issue("review", "translation")], hidden=True, locked=True,
            )],
        ),
        {"unit": SourceRef("source", "key", "2", {"raw_line": ' key:0 "Hello"'})},
    )


class SerializationTests(unittest.TestCase):
    def test_json_round_trip_preserves_data_and_enum(self) -> None:
        original = sample()
        restored = imported_from_dict(json.loads(json.dumps(asdict(original))))
        self.assertEqual(restored, original)
        self.assertIs(restored.project.units[0].state, UnitState.DOUBTFUL)

    def test_empty_project(self) -> None:
        original = ImportedTranslation(TranslationProject())
        self.assertEqual(imported_from_dict(asdict(original)), original)

    def test_rejects_invalid_structure_and_references(self) -> None:
        valid = record(json.loads(json.dumps(asdict(sample()))))
        invalid: list[object] = [None, [], {}, {"project": []}]
        for field, bad in (("state", "unknown"), ("hidden", "false"), ("locked", 1),
                           ("source_text", None), ("issues", [{"message": 12}])):
            candidate = deepcopy(valid)
            unit = record(array(record(candidate["project"])["units"])[0])
            unit[field] = bad
            invalid.append(candidate)
        for field in ("source_text", "id", "label"):
            candidate = deepcopy(valid)
            del record(array(record(candidate["project"])["units"])[0])[field]
            invalid.append(candidate)
        for field in ("sources", "units"):
            candidate = deepcopy(valid)
            values = array(record(candidate["project"])[field])
            values.append(deepcopy(values[0]))
            invalid.append(candidate)
        for refs in ({}, {"orphan": asdict(sample().source_refs["unit"])},
                     {"unit": {"source_id": "missing", "external_id": "key"}},
                     {"unit": {"source_id": "source", "external_id": "key", "data": {"line": 1}}}):
            candidate = deepcopy(valid)
            candidate["source_refs"] = refs
            invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                imported_from_dict(candidate)


class FilterTests(unittest.TestCase):
    def test_defaults_are_independent_and_can_be_disabled(self) -> None:
        default = FilterRule("hide", pattern="Hello", is_builtin=True)
        config = AdapterFilterConfig.from_dict({}, [default])
        self.assertTrue(should_hide_unit(sample().project.units[0], config))
        config.disable_all_builtin = True
        self.assertFalse(should_hide_unit(sample().project.units[0], config))
        config.rules[0].enabled = False
        self.assertTrue(default.enabled)
        self.assertEqual(AdapterFilterConfig.from_dict(config.to_dict()), config)

    def test_rejects_malformed_settings(self) -> None:
        for value in ({"rules": [None]}, {"rules": None}, {"disable_all_builtin": "false"},
                      {"rules": [{"id": "rule", "enabled": 1}]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AdapterFilterConfig.from_dict(value)


class ParserTests(unittest.TestCase):
    def test_public_contracts_are_headless_and_preserve_type_identity(self) -> None:
        result = subprocess.run([
            sys.executable, "-c",
            "import sys; from autolingua2.plugins import contracts; "
            "from autolingua2.ir.imported import ImportedTranslation; "
            "assert contracts.ImportedTranslation is ImportedTranslation; "
            "assert not any(n.startswith(('PySide6', 'autolingua2_native')) for n in sys.modules); "
            "assert 'autolingua2.plugins.manager' not in sys.modules",
        ], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bundled_plugin_uses_only_public_host_imports(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/autolingua2/plugins/paradox_yaml"
        allowed = ("autolingua2.plugins.api", "autolingua2.plugins.contracts",
                   "autolingua2.plugins.paradox_yaml")
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                names: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                for name in names:
                    if name.startswith("autolingua2."):
                        self.assertTrue(any(name == prefix or name.startswith(prefix + ".") for prefix in allowed),
                                        f"{path}: private host import {name}")

    def test_parser_has_no_ui_contract_and_imports_without_qt(self) -> None:
        parser: FileAdapter = ParadoxYamlAdapter(lambda path: "")
        validate_adapter(parser)
        self.assertFalse(hasattr(parser, "create_creation_panel"))
        result = subprocess.run([
            sys.executable, "-c",
            "import sys; from autolingua2.plugins.paradox_yaml.parser import ParadoxYamlAdapter; "
            "assert not any(name.startswith('PySide6') for name in sys.modules)",
        ], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(("en_US", "English"), parser.supported_languages)

    def test_paradox_parse_restore_render(self) -> None:
        template = 'l_english:\n key:0 "Hello"\n'
        parser = ParadoxYamlAdapter(lambda path: template)
        path = Path("sample_l_english.yml")
        imported = parser.load(path)
        restored = imported_from_dict(json.loads(json.dumps(asdict(imported))))
        restored.project.target_file_language = "l_japanese"
        restored.project.units[0].target_text = "こんにちは"
        rendered = render_translation_file(restored, restored.project, read_text=lambda path: template)
        self.assertIn("l_japanese:", rendered)
        self.assertIn("こんにちは", rendered)
        self.assertEqual(parser.output_name(path, restored.project), "sample_l_japanese.yml")

    def test_domain_and_parsers_do_not_import_upper_layers(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "autolingua2"
        for directory in (root / "ir", root / "adapters", root / "plugins/paradox_yaml/parser"):
            for path in directory.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or ""]
                    for name in names:
                        self.assertFalse(name.startswith(("PySide6", "autolingua2.ui", "autolingua2.services")),
                                         f"{path}: {name}")


class ExecutableTests(unittest.TestCase):
    def description(self) -> dict[str, object]:
        return {
            "name": "Example", "suffixes": [".yml"],
            "supported_languages": [["en_US", "English"]],
            "supported_games": [{"id": "example", "name": "Example", "slots": [], "default_slot_id": ""}],
        }

    def create_adapter(self, description: object) -> ExecutableAdapter:
        platform = Mock(spec=PlatformDriver)
        platform.plugin_platform_key.return_value = "windows"
        manifest = {"protocol_version": 1, "id": "example",
                    "executables": {"windows": {"path": "example.exe", "args": []}}}
        with patch.object(Path, "read_text", return_value=json.dumps(manifest)), \
             patch.object(Path, "is_file", return_value=True), \
             patch("autolingua2.adapters.executable.PluginRPC") as rpc:
            rpc.return_value.call.return_value = {"id": "example", "parser": description}
            return ExecutableAdapter(Path("plugins/example/plugin.json"), platform)

    def test_supported_language_inspection_and_data_loading(self) -> None:
        adapter = self.create_adapter(self.description())
        validate_adapter(adapter)
        path = Path("source.yml").resolve()
        with patch.object(adapter.rpc, "call", return_value={"files": [str(path)], "source_language": "en_US"}), \
             patch.object(Path, "is_file", return_value=True):
            self.assertEqual(adapter.filter_source_files([path], "auto"), [path])
            self.assertEqual(adapter.detect_source_language(path), "en_US")
        with patch.object(adapter.rpc, "call", return_value={"files": [str(path)], "source_language": "invalid"}), \
             patch.object(Path, "is_file", return_value=True), self.assertRaises(ValueError):
            adapter.filter_source_files([path], "auto")
        self.assertIsNone(adapter.detect_source_language(path))
        imported = sample()
        imported.project.sources[0].id = str(path)
        imported.source_refs["unit"].source_id = str(path)
        with patch.object(adapter.rpc, "call", return_value=asdict(imported)):
            self.assertEqual(adapter.load(path), imported)

    def test_rejects_missing_duplicate_or_invalid_languages(self) -> None:
        for languages in (None, [], [["en_US"]], [["en_US", "English"], ["en_US", "Other"]]):
            description = self.description()
            if languages is None:
                del description["supported_languages"]
            else:
                description["supported_languages"] = languages
            with self.subTest(languages=languages), self.assertRaises(ValueError):
                self.create_adapter(description)


if __name__ == "__main__":
    unittest.main()
