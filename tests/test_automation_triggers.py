import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox, QPushButton

from autolingua2.ir.automation_script import Script, ScriptError
from autolingua2.ir.automation_trigger import TriggerDefinition, TriggerScript
from autolingua2.ui.dialogs.automation import AutomationDialogController
from autolingua2.ui.dialogs import automation_triggers as ui


CONTEXT = {"project_is_open": True, "project_name": "test", "project_target_language": "ja",
           "project_source_language": "en"}
PATH = "C:/scripts/export.als"
SOURCE = f'on translation_completed {{ if project.target_language == "ja" {{ run("{PATH}") }} }}'


def test_conditions_events_functions_and_strings():
    script = TriggerScript('''function output(string path): void { run(path) }
on translation_completed {
    string[] files = ["C:/project.name.als", "C:/two.als"]
    if project.is_open && project.target_language == "ja" {
        for string path in files { output(path) }
    }
}
on schedule("09:00") { run("C:/morning.als") }
''')
    assert script.paths("translation_completed", CONTEXT) == ["C:/project.name.als", "C:/two.als"]
    assert script.paths("translation_completed", {**CONTEXT, "project_is_open": False}) == []
    assert script.paths("app_started", CONTEXT) == []
    assert script.paths("schedule", CONTEXT, "09:00") == ["C:/morning.als"]
    assert script.paths("schedule", CONTEXT, "10:00") == []


@pytest.mark.parametrize("source", [
    'on unknown { run("C:/a.als") }', 'on schedule("25:00") {}',
    'on app_started { click("button") }', 'on app_started { run(10) }',
    'on app_started { bool project_is_open = false }',
])
def test_invalid_definitions(source):
    with pytest.raises(ValueError):
        TriggerScript(source)


def test_bounded_condition_evaluation():
    script = TriggerScript('function again(): void { again() } on app_started { again() }')
    with pytest.raises(ScriptError):
        script.paths("app_started", CONTEXT)


class Service(QObject):
    batch_finished = Signal(int, int, int)
    busy = False


class Host(QObject):
    pass


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def triggers(app, monkeypatch):
    monkeypatch.setattr(ui, "load_triggers", lambda: [TriggerDefinition("one", "Export", SOURCE, True)])
    monkeypatch.setattr(ui, "save_triggers", lambda values: None)
    host = Host()
    host.window = QMainWindow()
    host.window.show()
    host.automation_dialog = AutomationDialogController(host.window, lambda _: QIcon())
    host.workspace_service = object()
    host.project_path = Path("C:/project.alproj")
    host.project = SimpleNamespace(name="test", target_language="ja", source_language="en", sources=[])
    host.translation_controller = SimpleNamespace(service=Service())
    host.operations = SimpleNamespace(has_workers=False)
    host.io_worker = host.import_worker = host._initial_setup_dialog = None
    controller = ui.AutomationTriggers(host)
    yield controller
    controller.shutdown()
    host.automation_dialog.dialog.hide()
    host.window.hide()
    host.automation_dialog.dialog.removeEventFilter(host.automation_dialog)
    host.automation_dialog.editor.removeEventFilter(host.automation_dialog)
    host.automation_dialog.dialog.deleteLater()
    host.window.deleteLater()
    app.sendPostedEvents()


def test_queue_deduplication_busy_and_project_switch(triggers, monkeypatch):
    triggers.emit_event("translation_completed")
    triggers.emit_event("translation_completed")
    assert len(triggers.queue) == 1
    triggers.host.translation_controller.service.busy = True
    monkeypatch.setattr(triggers, "_confirm", lambda _: pytest.fail("Must wait"))
    triggers._tick()
    assert len(triggers.queue) == 1
    triggers.host.translation_controller.service.busy = False
    triggers.host.workspace_service = object()
    triggers._tick()
    assert not triggers.queue


def test_cancel_does_not_read_script(triggers, monkeypatch):
    triggers.emit_event("translation_completed")
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("Read before approval"))
    triggers._tick()
    assert not triggers.executing
    assert not triggers.queue


def test_accept_reads_only_after_confirmation(triggers, monkeypatch):
    triggers.emit_event("translation_completed")
    approved = []
    def confirm(box):
        assert box.findChild(QPushButton, "buttonCancel").isDefault()
        approved.append(True)
        box.findChild(QPushButton, "buttonExecute").click()
        return box.result()
    monkeypatch.setattr(QDialog, "exec", confirm)
    def read(path, **kwargs):
        assert approved
        return 'string value = "ok"'
    monkeypatch.setattr(Path, "read_text", read)
    def start(script):
        triggers.automation.runner.running = True
    monkeypatch.setattr(triggers.automation, "start_script_object", start)
    triggers._tick()
    assert triggers.executing and triggers.automation.external_execution
    triggers.automation.runner.running = False


def test_missing_script_reports_failure_and_releases_queue(triggers, monkeypatch):
    triggers.emit_event("translation_completed")
    request = triggers.queue.popleft()
    triggers.current = request
    triggers.executing = True
    triggers.active_paths.extend(request.paths)
    def missing(*args, **kwargs):
        raise FileNotFoundError("missing script")
    monkeypatch.setattr(Path, "read_text", missing)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    triggers._next_script()
    assert not triggers.executing and not triggers.active_paths
    assert "Export" in warnings[0][-1] and "missing script" in warnings[0][-1]


def test_settings_roundtrip_keeps_independent_definitions(monkeypatch):
    from autolingua2.services.settings import automation_triggers as store
    saved = {"other_setting": True}
    monkeypatch.setattr(store, "_read_settings_file", lambda: saved.copy())
    monkeypatch.setattr(store, "_write_settings_file", lambda value: saved.update(value))
    values = [TriggerDefinition("first", "First", SOURCE, True),
              TriggerDefinition("second", "Second", 'on app_started {}', False)]
    store.save_triggers(values)
    assert store.load_triggers() == values
    assert saved["other_setting"] is True


def test_execution_preserves_editor_and_suppresses_recursion(triggers, monkeypatch):
    automation = triggers.automation
    original = automation.editor.toPlainText()
    original_path = automation.path
    triggers.emit_event("translation_completed")
    request = triggers.queue.popleft()
    triggers.current = request
    triggers.executing = True
    triggers.active_paths.extend(request.paths)
    reads = []
    def read(path, **kwargs):
        reads.append(str(path))
        return 'string name = "external"'
    monkeypatch.setattr(Path, "read_text", read)
    captured = []
    monkeypatch.setattr(automation, "start_script_object", captured.append)
    # Mark the runner busy as the real start method would.
    automation.runner.running = True
    triggers._next_script()
    assert len(captured) == 1 and isinstance(captured[0], Script)
    assert len(reads) == 1
    assert automation.editor.toPlainText() == original and automation.path is original_path
    triggers.emit_event("translation_completed")
    assert not triggers.queue
    automation.runner.running = False


def test_invalid_save_retains_active_definition(triggers):
    old = triggers.definitions[0]
    triggers.editor.setPlainText("on invalid {}")
    assert not triggers._save()
    assert triggers.definitions[0] == old
    assert triggers.scripts[old.id].paths("translation_completed", CONTEXT) == [PATH]


def test_daily_schedule_once_and_no_sleep_catchup(triggers, monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 10, 20, 8, 59, 59, 500000)
        @classmethod
        def now(cls):
            return cls.current
    monkeypatch.setattr(ui, "datetime", Clock)
    triggers.last_tick = Clock.current
    definition = replace(triggers.definitions[0], source=f'on schedule("09:00") {{ run("{PATH}") }}')
    triggers.definitions = [definition]
    triggers.scripts[definition.id] = TriggerScript(definition.source)
    monkeypatch.setattr(triggers, "_busy", lambda: True)
    Clock.current = datetime(2026, 10, 20, 9, 0, 0)
    triggers._tick()
    assert len(triggers.queue) == 1
    triggers.queue.clear()
    triggers._tick()
    assert not triggers.queue
    triggers.last_tick = datetime(2026, 10, 21, 8, 0)
    Clock.current = datetime(2026, 10, 21, 9, 0, 20)
    triggers._tick()
    assert not triggers.queue
