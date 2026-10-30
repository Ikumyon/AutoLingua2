"""Retranslation requests are tested without sending any network requests."""
from __future__ import annotations

from dataclasses import replace
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow, QPushButton, QWidget

from autolingua2.ir import UnitState
from autolingua2.ir.filter_rules import AdapterFilterConfig, FilterRule, TagKind, TagRules
from autolingua2.ir.unit import TranslationUnit
from autolingua2.ir.workspace import TranslationRecord, Workspace, WorkspaceUnit
from autolingua2.plugins.openai.openai import OpenAiProvider
from autolingua2.services.ai.ai_network import AiNetworkClient
from autolingua2.services.ai_providers.chat import ChatReply
from autolingua2.services.translation.translation import TranslationOptions, TranslationService, TranslationTextContext
from autolingua2.services.translation.translation_execution import TranslationModel
from autolingua2.ui.dialogs.retranslation import RetranslationDialog
from autolingua2.ui.main.main_window_translation import MainWindowTranslationController


class CapturingClient(AiNetworkClient):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict] = []
        self.chats: list[tuple] = []

    def translate_text(self, **kwargs) -> None:
        self.requests.append(kwargs)

    def request_chat(self, *args, **kwargs) -> None:
        self.chats.append(args)


class RetranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.client = CapturingClient()
        model = TranslationModel(OpenAiProvider(), "test-key", "test-model")
        rules = TagRules(AdapterFilterConfig([
            FilterRule("tag", TagKind.DISPLAY_CONTROL, pattern=r"<[^>]+>"),
        ]))
        self.options = TranslationOptions(model, model, "en", "ja", TranslationTextContext("test", "test", rules))
        self.workspace = Workspace("ja")
        self.service = TranslationService(self.client, lambda workspace: True, lambda: self.options,
                                          get_tone_context=lambda unit: None)
        self.service.memory = Mock()
        self.service.memory.lookup.return_value = None

    def tearDown(self) -> None:
        self.service.stop()
        self.app.processEvents()

    def unit(self, unit_id: str, target: str = "古い訳", source: str = "Hello.") -> WorkspaceUnit:
        record = TranslationRecord(target_text=target,
                                   state=UnitState.AI_TRANSLATED if target else UnitState.UNTRANSLATED)
        self.workspace.records[unit_id] = record
        return WorkspaceUnit(TranslationUnit(unit_id, unit_id, source), record)

    def drain(self) -> None:
        for _ in range(6):
            self.app.processEvents()

    def test_single_request_and_memory_isolation(self) -> None:
        unit = self.unit("a")
        self.service.translate_single(self.workspace, unit, self.options, additional_instructions="  短くして  ")
        request = self.client.requests[-1]
        self.assertEqual(request["additional_instructions"], "短くして")
        self.assertEqual(request["current_translation"], "古い訳")
        self.client.translation_completed.emit(request["request_id"], "新訳")
        self.assertEqual(unit.target_text, "新訳")
        self.service.memory.lookup.assert_not_called()
        self.service.memory.store.assert_not_called()
        self.assertEqual(self.options.additional_instructions, "")

    def test_batch_keeps_each_current_translation_and_untranslated_item(self) -> None:
        units = [self.unit("a", "訳その一"), self.unit("b", "訳その二"), self.unit("c", "")]
        self.service.start_batch(self.workspace, units, None, additional_instructions="自然に")
        self.drain()
        self.assertEqual(len(self.client.requests), 3)
        self.assertCountEqual([request["current_translation"] for request in self.client.requests],
                              ["訳その一", "訳その二", ""])
        for request in self.client.requests:
            self.assertEqual(request["additional_instructions"], "自然に")
            self.client.translation_completed.emit(request["request_id"], "新訳")
        self.assertEqual(self.service.completed, 3)
        self.assertFalse(self.service.running)
        self.service.memory.lookup.assert_not_called()
        self.service.memory.store.assert_not_called()

    def test_empty_instructions_preserve_normal_memory(self) -> None:
        unit = self.unit("a", "")
        self.service.translate_single(self.workspace, unit, self.options, additional_instructions=" \n ")
        request = self.client.requests[-1]
        self.assertEqual(request["additional_instructions"], "")
        self.assertEqual(request["current_translation"], "")
        self.client.translation_completed.emit(request["request_id"], "通常訳")
        self.service.memory.lookup.assert_called_once()
        self.service.memory.store.assert_called_once()

    def test_changed_instructions_or_current_translation_use_new_request(self) -> None:
        unit = self.unit("a")
        for instruction in ("短く", "自然に", "自然に"):
            self.service.translate_single(self.workspace, unit, self.options, additional_instructions=instruction)
            request = self.client.requests[-1]
            self.assertEqual(request["current_translation"], unit.target_text)
            self.client.translation_completed.emit(request["request_id"], unit.target_text + "改")
        self.assertEqual(len(self.client.requests), 3)
        self.assertEqual(self.service.usage_counts["temporary_cache"], 0)

    def test_failure_and_invalid_tokens_preserve_existing_translation(self) -> None:
        unit = self.unit("a", source="<b>Hello.</b>")
        self.service.translate_single(self.workspace, unit, self.options, additional_instructions="短く")
        self.client.translation_completed.emit(self.client.requests[-1]["request_id"], "タグ欠落")
        self.assertEqual(unit.target_text, "古い訳")
        self.assertEqual(unit.state, UnitState.AI_TRANSLATED)
        self.service.translate_single(self.workspace, unit, self.options)
        self.client.translation_failed.emit(self.client.requests[-1]["request_id"], "network failure")
        self.assertEqual(unit.target_text, "古い訳")
        self.assertFalse(unit.record.translating)

    def test_protected_tokens_survive_retranslation(self) -> None:
        unit = self.unit("a", source="<b>Hello.</b>")
        self.service.translate_single(self.workspace, unit, self.options, additional_instructions="短く")
        request = self.client.requests[-1]
        self.client.translation_completed.emit(request["request_id"], request["text"].replace("Hello.", "新訳"))
        self.assertEqual(unit.target_text, "<b>新訳</b>")

    def test_stop_preserves_translation_and_ignores_late_result(self) -> None:
        unit = self.unit("a")
        self.service.translate_single(self.workspace, unit, self.options, additional_instructions="短く")
        request = self.client.requests[-1]
        self.service.stop()
        self.client.translation_completed.emit(request["request_id"], "遅い結果")
        self.assertEqual(unit.target_text, "古い訳")
        self.assertFalse(unit.record.translating)

    def test_excluded_units_are_not_requested(self) -> None:
        units = [self.unit(str(index)) for index in range(4)]
        units[0].state = UnitState.LOCKED
        units[1].state = UnitState.HIDDEN
        units[2].record.pending_confirmation = Mock()
        units[3].record.translating = True
        self.service.translate_single(self.workspace, units[3], self.options, additional_instructions="短く")
        self.service.start_batch(self.workspace, units[:3], None, additional_instructions="短く")
        # A unit already enqueued by this service is also excluded from another request.
        self.service.translate_single(self.workspace, units[3], self.options, additional_instructions="再度")
        self.assertEqual(len(self.client.requests), 1)

    def test_review_receives_instructions_and_does_not_store_memory(self) -> None:
        unit = self.unit("a")
        self.service.translate_single(self.workspace, unit, replace(self.options, review_model=self.options.high),
                                      additional_instructions="敬語を外す")
        self.client.translation_completed.emit(self.client.requests[-1]["request_id"], "新訳")
        self.drain()
        request_id, _, messages, prompt, *_ = self.client.chats[-1]
        self.assertEqual(json.loads(messages[0].content)["additional_instructions"], "敬語を外す")
        self.assertIn("優先", prompt)
        reply = {"id": request_id, "reviews": {"a": {"approved": True, "review": ""}}}
        self.client.chat_completed.emit(request_id, ChatReply(json.dumps(reply)))
        self.assertEqual(unit.state, UnitState.AI_REVIEWED)
        self.service.memory.store.assert_not_called()

    def test_network_payload_and_queued_request_preserve_instructions(self) -> None:
        client = AiNetworkClient()
        client._post_ai = Mock()
        client.translation_slots.configure(1)
        client.translation_slots.acquire("block")
        client.translate_text("request", OpenAiProvider(), "test-key", "test-model", "Hello.", structured=True,
                              additional_instructions="短く", current_translation="現在訳")
        self.assertEqual(len(client._waiting_translations), 1)
        client.translation_slots.release("block")
        client._waiting_translations.popleft()()
        payload = client._post_ai.call_args.args[2]
        data = json.loads(payload["messages"][-1]["content"])
        self.assertEqual(data["additional_instructions"], "短く")
        self.assertEqual(data["current_translation"], "現在訳")
        self.assertIn("take priority", payload["messages"][0]["content"])
        client.translation_slots.release("request")

    def test_dialog_buttons_multiline_input_and_escape(self) -> None:
        parent = QWidget()
        single = RetranslationDialog(["<item>"], 0, parent)
        single.dialog.show()
        self.app.processEvents()
        self.assertTrue(single.dialog.findChild(QPushButton, "buttonUntranslated").isHidden())
        self.assertEqual(single.dialog.findChild(QLabel, "labelTargets").text(), "対象：<item>")
        single.instructions.setPlainText("自然に")
        QTest.keyClick(single.instructions, Qt.Key.Key_Return)
        self.assertIn("\n", single.instructions.toPlainText())
        QTimer.singleShot(0, lambda: QTest.keyClick(single.instructions, Qt.Key.Key_Escape))
        self.assertEqual(single.exec(), QDialog.DialogCode.Rejected)
        mixed = RetranslationDialog(["a", "b", "c"], 1, parent)
        button = mixed.dialog.findChild(QPushButton, "buttonUntranslated")
        self.assertFalse(button.isHidden())
        QTimer.singleShot(0, button.click)
        self.assertEqual(mixed.exec(), QDialog.DialogCode.Accepted)
        self.assertTrue(mixed.untranslated_only)
        translated = RetranslationDialog(["a", "b"], 0, parent)
        self.assertTrue(translated.dialog.findChild(QPushButton, "buttonUntranslated").isHidden())
        self.assertEqual(translated.additional_instructions(), "")
        parent.close()

    def test_single_button_opens_dialog_only_for_retranslation(self) -> None:
        window = QMainWindow()
        host = SimpleNamespace(window=window, active_workspace=self.workspace, _workspace_is_alive=lambda workspace: True)
        controller = SimpleNamespace(host=host, service=Mock(), _options=Mock(return_value=self.options))
        controller.service.is_translating.return_value = False
        unit = self.unit("a")
        with patch("autolingua2.ui.main.main_window_translation.RetranslationDialog") as dialog_type:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Rejected
            MainWindowTranslationController._translate_single_unit(controller, unit)
            controller.service.translate_single.assert_not_called()
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.additional_instructions.return_value = "短く"
            MainWindowTranslationController._translate_single_unit(controller, unit)
            controller.service.translate_single.assert_called_once_with(
                self.workspace, unit, self.options, additional_instructions="短く")
            dialog_type.reset_mock()
            MainWindowTranslationController._translate_single_unit(controller, self.unit("b", ""))
            dialog_type.assert_not_called()
        window.close()

    def test_selection_dialog_routes_all_or_only_untranslated_and_cancel(self) -> None:
        units = [self.unit("a"), self.unit("b", "")]
        window = QWidget()
        host = SimpleNamespace(window=window, active_workspace=self.workspace, filtered_units=units,
                               _workspace_is_alive=lambda workspace: True)
        controller = SimpleNamespace(host=host, _start_batch_translation=Mock())
        with patch("autolingua2.ui.main.main_window_translation.RetranslationDialog") as dialog_type:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.additional_instructions.return_value = "自然に"
            for untranslated_only, targets in ((False, units), (True, [units[1]])):
                dialog.untranslated_only = untranslated_only
                MainWindowTranslationController._handle_selected_translation(controller, [0, 1])
                controller._start_batch_translation.assert_called_with(targets, additional_instructions="自然に")
            controller._start_batch_translation.reset_mock()
            dialog.exec.return_value = QDialog.DialogCode.Rejected
            MainWindowTranslationController._handle_selected_translation(controller, [0, 1])
            controller._start_batch_translation.assert_not_called()
            dialog_type.reset_mock()
            MainWindowTranslationController._handle_selected_translation(controller, [1])
            dialog_type.assert_not_called()
            controller._start_batch_translation.assert_called_once_with([units[1]])
        window.close()


if __name__ == "__main__":
    unittest.main()
