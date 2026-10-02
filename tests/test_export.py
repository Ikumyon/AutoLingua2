from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock

from autolingua2.adapters.base import FileAdapter
from autolingua2.infrastructure.operations import OperationCancelled, operation_scope
from autolingua2.ir import TranslationProject, TranslationSource, TranslationUnit
from autolingua2.ir.imported import ImportedTranslation, SourceRef
from autolingua2.services.export import export_translation


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.adapter = Mock(spec=FileAdapter)
        self.adapter.id = "test"
        self.adapter.output_name.side_effect = lambda path, project: path.name + ".translated"
        self.imported = ImportedTranslation(
            TranslationProject(adapter_id="test",
                sources=[TranslationSource("a.yml", "A"), TranslationSource("b.yml", "B")],
                units=[TranslationUnit("a", "a", "source", "訳A"), TranslationUnit("b", "b", "source", "訳B")]),
            {"a": SourceRef("a.yml", "a"), "b": SourceRef("b.yml", "b")},
        )

    def test_each_source_receives_only_its_own_units_and_references(self) -> None:
        paths = export_translation(self.imported, self.adapter, self.path)
        self.assertEqual([path.name for path in paths], ["a.yml.translated", "b.yml.translated"])
        for call, unit_id in zip(self.adapter.save.call_args_list, ("a", "b")):
            _, imported, project = call.args
            self.assertEqual([unit.id for unit in project.units], [unit_id])
            self.assertEqual(list(imported.source_refs), [unit_id])
            self.assertEqual(len(project.sources), 1)
        self.assertEqual(len(self.imported.project.sources), 2)

    def test_duplicate_or_escaping_names_fail_before_any_write(self) -> None:
        for name in ("same.yml", "../escape.yml", "..\\escape.yml"):
            with self.subTest(name=name):
                self.adapter.output_name.side_effect = None
                self.adapter.output_name.return_value = name
                with self.assertRaises(ValueError):
                    export_translation(self.imported, self.adapter, self.path)
                self.adapter.save.assert_not_called()

    def test_cancellation_and_save_failure_are_not_reported_as_success(self) -> None:
        cancel = Event()
        cancel.set()
        with self.assertRaises(OperationCancelled), operation_scope(cancel, lambda message: None):
            export_translation(self.imported, self.adapter, self.path)
        self.adapter.save.assert_not_called()
        self.adapter.save.side_effect = OSError("write failed")
        with self.assertRaises(OSError):
            export_translation(self.imported, self.adapter, self.path)


if __name__ == "__main__":
    unittest.main()
