"""Managed trigger list/editor and cooperative event dispatch."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QTabWidget,
)

from autolingua2.ir.automation_script import Script, ScriptError
from autolingua2.ir.automation_trigger import EXAMPLE, TriggerDefinition, TriggerScript
from autolingua2.services.settings.automation_triggers import load_triggers, save_triggers
from autolingua2.ui.components.script_editor import ScriptEditor
from autolingua2.ui.dialogs.base import SimpleDialogController, require_child
from autolingua2.ui.resources.i18n import tr, translation_source


EVENT_LABELS = {
    "app_started": translation_source("AutomationTriggers", "アプリ起動時"),
    "project_opened": translation_source("AutomationTriggers", "プロジェクトを開いた時"),
    "translation_completed": translation_source("AutomationTriggers", "翻訳完了時"),
    "schedule": translation_source("AutomationTriggers", "指定時刻"),
}
HELP = '''on app_started { run("D:/scripts/start.als") }
on project_opened { run("D:/scripts/open.als") }
on translation_completed {
    if project.is_open && project.target_language == "ja" {
        run("D:/scripts/export.als")
    }
}
on schedule("09:00") { run("D:/scripts/daily.als") }

// project.is_open: bool
// project.name / project.source_language / project.target_language: string
// ALSの変数・配列・if・for・functionが使えます。
// runには処理用.alsの絶対パスを指定します。
// 時刻指定は毎日、アプリ起動中のみ有効です。
// 画面操作は処理用.alsに記述してください。
'''


@dataclass
class Request:
    definition: TriggerDefinition
    event: str
    project: object
    paths: list[str]


class AutomationTriggers(QObject):
    def __init__(self, host) -> None:
        super().__init__(host)
        self.host = host
        self.automation = host.automation_dialog
        self.automation.triggers = self
        self.definitions: list[TriggerDefinition] = []
        self.scripts: dict[str, TriggerScript] = {}
        self.queue: deque[Request] = deque()
        self.current: Request | None = None
        self.active_paths: deque[str] = deque()
        self.executing = False
        self.confirming = False
        self.closed = False
        self.started = False
        self.last_tick = datetime.now()
        self.fired: dict[tuple[str, str], object] = {}
        self.selected = -1
        self.load_failed = False
        self._bind_ui()
        try:
            self.definitions = load_triggers()
        except (ValueError, OSError) as exc:
            self.load_failed = True
            self.add_button.setEnabled(False)
            self._log(str(exc))
            self.status.setText(str(exc))
        for definition in self.definitions:
            try:
                self.scripts[definition.id] = TriggerScript(definition.source)
            except (ValueError, RecursionError) as exc:
                self._log(f"{definition.name}: {exc}")
        self._refresh_list()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.automation.execution_finished.connect(self._finished)
        host.translation_controller.service.batch_finished.connect(lambda *_: self.emit_event("translation_completed"))
        app = QApplication.instance()
        app.aboutToQuit.connect(self.shutdown)

    def _bind_ui(self) -> None:
        dialog = self.automation.dialog
        self.tabs = require_child(dialog, QTabWidget, "automationTabs")
        self.items = require_child(dialog, QListWidget, "listTriggers")
        self.name = require_child(dialog, QLineEdit, "editTriggerName")
        self.editor = require_child(dialog, ScriptEditor, "editTriggerScript")
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.status = require_child(dialog, QLabel, "labelTriggerStatus")
        self.log = require_child(dialog, QPlainTextEdit, "editTriggerLog")
        self.add_button = require_child(dialog, QPushButton, "buttonTriggerAdd")
        self.delete_button = require_child(dialog, QPushButton, "buttonTriggerDelete")
        self.path_button = require_child(dialog, QPushButton, "buttonTriggerPath")
        self.check_button = require_child(dialog, QPushButton, "buttonTriggerCheck")
        self.save_button = require_child(dialog, QPushButton, "buttonTriggerSave")
        self.add_button.clicked.connect(self._add)
        self.delete_button.clicked.connect(self._delete)
        self.path_button.clicked.connect(self._insert_path)
        self.check_button.clicked.connect(self._check)
        self.save_button.clicked.connect(self._save)
        require_child(dialog, QPushButton, "buttonTriggerHelp").clicked.connect(self._help)
        require_child(dialog, QPushButton, "buttonTriggerClose").clicked.connect(dialog.close)
        self.items.currentRowChanged.connect(self._select)
        self.items.itemChanged.connect(self._toggle)

    def _log(self, text: str) -> None:
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def _refresh_list(self, selected: int = 0) -> None:
        with QSignalBlocker(self.items):
            self.items.clear()
            for definition in self.definitions:
                item = QListWidgetItem(definition.name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if definition.enabled else Qt.CheckState.Unchecked)
                self.items.addItem(item)
            self.items.setCurrentRow(min(selected, len(self.definitions) - 1))
        self.selected = -1
        self._load_selection(self.items.currentRow())

    def _load_selection(self, row: int) -> None:
        self.selected = row
        definition = self.definitions[row] if row >= 0 else None
        self.name.setText(definition.name if definition else "")
        self.editor.setPlainText(definition.source if definition else "")
        self.editor.document().setModified(False)
        for widget in (self.name, self.editor, self.save_button, self.check_button, self.path_button, self.delete_button):
            widget.setEnabled(definition is not None)
        if definition:
            self.status.setText(tr("AutomationTriggers", "有効・待ち受け中") if definition.enabled and definition.id in self.scripts
                                else tr("AutomationTriggers", "無効または構文エラー"))

    def confirm_discard(self) -> bool:
        if self.selected < 0:
            return True
        saved = self.definitions[self.selected]
        if self.name.text() == saved.name and self.editor.toPlainText() == saved.source:
            return True
        result = QMessageBox.question(self.automation.dialog, tr("AutomationTriggers", "未保存の変更"),
                                      tr("AutomationTriggers", "トリガーの変更を保存しますか？"),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        return self._save() if result == QMessageBox.StandardButton.Save else result == QMessageBox.StandardButton.Discard

    def _select(self, row: int) -> None:
        if row == self.selected:
            return
        if not self.confirm_discard():
            with QSignalBlocker(self.items):
                self.items.setCurrentRow(self.selected)
            return
        self._load_selection(row)

    def _persist(self, values: list[TriggerDefinition]) -> bool:
        try:
            save_triggers(values)
        except OSError as exc:
            QMessageBox.warning(self.automation.dialog, tr("AutomationTriggers", "保存エラー"), str(exc))
            return False
        self.definitions = values
        return True

    def _add(self) -> None:
        if not self.confirm_discard():
            return
        definition = TriggerDefinition(uuid4().hex, tr("AutomationTriggers", "新しいトリガー"), EXAMPLE)
        if self._persist(self.definitions + [definition]):
            self.scripts[definition.id] = TriggerScript(definition.source)
            self._refresh_list(len(self.definitions) - 1)

    def _delete(self) -> None:
        if self.selected < 0:
            return
        definition = self.definitions[self.selected]
        if QMessageBox.question(self.automation.dialog, tr("AutomationTriggers", "削除"),
                                tr("AutomationTriggers", "選択したトリガーを削除しますか？"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if self._persist([d for d in self.definitions if d.id != definition.id]):
            self.scripts.pop(definition.id, None)
            self._invalidate(definition.id)
            self._refresh_list()

    def _invalidate(self, id: str) -> None:
        self.queue = deque(request for request in self.queue if request.definition.id != id)

    def _toggle(self, item: QListWidgetItem) -> None:
        row = self.items.row(item)
        old = self.definitions[row]
        enabled = item.checkState() == Qt.CheckState.Checked
        if enabled and old.id not in self.scripts:
            QMessageBox.warning(self.automation.dialog, tr("AutomationTriggers", "構文エラー"),
                                tr("AutomationTriggers", "構文を修正して保存してください。"))
        else:
            values = self.definitions.copy()
            values[row] = replace(old, enabled=enabled)
            if self._persist(values):
                self._invalidate(old.id)
                self.status.setText(tr("AutomationTriggers", "有効・待ち受け中") if enabled else tr("AutomationTriggers", "無効"))
                return
        with QSignalBlocker(self.items):
            item.setCheckState(Qt.CheckState.Checked if old.enabled else Qt.CheckState.Unchecked)

    def _compile(self) -> TriggerScript | None:
        try:
            return TriggerScript(self.editor.toPlainText())
        except (ValueError, RecursionError) as exc:
            self.status.setText(str(exc))
            if isinstance(exc, ScriptError):
                cursor = self.editor.textCursor()
                cursor.setPosition(self.editor.document().findBlockByNumber(exc.token.line - 1).position())
                self.editor.setTextCursor(cursor)
                self.editor.setFocus()
            return None

    def _check(self) -> None:
        if self._compile() is not None:
            self.status.setText(tr("AutomationTriggers", "構文に問題はありません。"))

    def _save(self) -> bool:
        if self.selected < 0:
            return False
        if not self.name.text().strip():
            self.status.setText(tr("AutomationTriggers", "名前を入力してください。"))
            return False
        script = self._compile()
        if script is None:
            return False
        old = self.definitions[self.selected]
        value = replace(old, name=self.name.text().strip(), source=self.editor.toPlainText())
        values = self.definitions.copy()
        values[self.selected] = value
        if not self._persist(values):
            return False
        self.scripts[value.id] = script
        self._invalidate(value.id)
        with QSignalBlocker(self.items):
            self.items.item(self.selected).setText(value.name)
        self.name.setText(value.name)
        self.editor.document().setModified(False)
        self.status.setText(tr("AutomationTriggers", "保存して反映しました。"))
        return True

    def _insert_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.automation.dialog, tr("AutomationTriggers", "処理スクリプトを選択"),
                                             "", "AUTOlingua Script (*.als)")
        if path:
            self.editor.insertPlainText(json.dumps(Path(path).as_posix(), ensure_ascii=False))

    def _help(self) -> None:
        QMessageBox.information(self.automation.dialog, tr("AutomationTriggers", "構文ヘルプ"), HELP)

    def startup(self) -> None:
        if not self.started:
            self.started = True
            self.last_tick = datetime.now()
            self.timer.start()
            self.emit_event("app_started")

    def shutdown(self) -> None:
        self.closed = True
        self.timer.stop()
        self.queue.clear()
        self.active_paths.clear()

    def emit_event(self, event: str, time: str | None = None, ids: set[str] | None = None) -> None:
        if self.closed or (event in {"project_opened", "translation_completed"}
                           and (self.automation.busy or self.executing)):
            return
        project = self.host.workspace_service
        context = {"project_is_open": bool(self.host.project_path or self.host.project.sources),
                   "project_name": self.host.project.name,
                   "project_target_language": self.host.project.target_language,
                   "project_source_language": self.host.project.source_language}
        for definition in self.definitions:
            if ids is not None and definition.id not in ids:
                continue
            if not definition.enabled or definition.id not in self.scripts:
                continue
            if (any(r.definition.id == definition.id for r in self.queue)
                    or (self.current is not None and self.current.definition.id == definition.id)):
                continue
            try:
                paths = self.scripts[definition.id].paths(event, context, time)
                if not paths:
                    continue
                for path in paths:
                    if not Path(path).is_absolute() or Path(path).suffix.lower() != ".als":
                        raise ValueError("runには処理用.alsの絶対パスを指定してください。")
                self.queue.append(Request(definition, event, project, paths))
                self._log(f"{definition.name}: " + tr("AutomationTriggers", "確認待ち"))
            except (ValueError, ArithmeticError, RecursionError) as exc:
                self._log(f"{definition.name}: {exc}")

    def _busy(self) -> bool:
        host = self.host
        return (self.automation.busy or host.translation_controller.service.busy
                or host.io_worker is not None or host.import_worker is not None
                or host.operations.has_workers or QApplication.activeModalWidget() is not None
                or host._initial_setup_dialog is not None or not host.window.isVisible())

    def _tick(self) -> None:
        if self.closed:
            return
        now = datetime.now()
        # A long gap (sleep) does not replay elapsed schedules.
        if (0 <= (now - self.last_tick).total_seconds() <= 2
                and now.strftime("%Y-%m-%d %H:%M") != self.last_tick.strftime("%Y-%m-%d %H:%M")):
            minute = now.strftime("%H:%M")
            due: set[str] = set()
            for definition in self.definitions:
                script = self.scripts.get(definition.id)
                if not definition.enabled or script is None:
                    continue
                if any(h.event == "schedule" and h.time == minute for h in script.handlers):
                    key = (definition.id, minute)
                    if self.fired.get(key) != now.date():
                        self.fired[key] = now.date()
                        due.add(definition.id)
            if due:
                self.emit_event("schedule", minute, due)
        self.last_tick = now
        if self.confirming or self.executing or self._busy():
            return
        while self.queue:
            request = self.queue.popleft()
            if request.project is not self.host.workspace_service:
                self._log(f"{request.definition.name}: " + tr("AutomationTriggers", "プロジェクト変更のため破棄"))
                continue
            self._confirm(request)
            break

    def _confirm(self, request: Request) -> None:
        self.confirming = True
        self.current = request
        box = SimpleDialogController("dialogs/AutomationTriggerConfirm.ui", self.host.window).dialog
        require_child(box, QLabel, "labelConfirm").setText(tr("AutomationTriggers", "「{name}」を実行しますか？").format(name=request.definition.name))
        require_child(box, QLabel, "labelDetails").setText(tr("AutomationTriggers", "きっかけ：{event}\nプロジェクト：{project}\nスクリプト：\n{paths}").format(
            event=tr("AutomationTriggers", EVENT_LABELS[request.event]), project=self.host.project.name,
            paths="\n".join(request.paths)))
        require_child(box, QPushButton, "buttonExecute").clicked.connect(box.accept)
        require_child(box, QPushButton, "buttonCancel").clicked.connect(box.reject)
        result = box.exec()
        box.deleteLater()
        self.confirming = False
        # Recheck after the nested event loop: settings/project may have changed.
        if (result != QDialog.DialogCode.Accepted or self.closed
                or request.project is not self.host.workspace_service
                or request.definition not in self.definitions or not request.definition.enabled):
            self._log(f"{request.definition.name}: " + tr("AutomationTriggers", "キャンセル"))
            self.current = None
            return
        self.current = request
        self.executing = True
        self.active_paths = deque(request.paths)
        self._next_script()

    def _next_script(self) -> None:
        if self.closed or not self.active_paths:
            self.executing = False
            self.current = None
            return
        path = self.active_paths.popleft()
        try:
            script = Script(Path(path).read_text(encoding="utf-8-sig"))
            self.tabs.setCurrentIndex(0)
            self.automation.external_execution = True
            self.automation.start_script_object(script)
            if not self.automation.busy:
                raise ValueError(self.automation.state.text())
            self.automation.execution_label.setText(tr("AutomationTriggers", "実行中：{path}").format(path=path))
            self._log(tr("AutomationTriggers", "実行中：{path}").format(path=path))
        except (OSError, ValueError, RuntimeError, RecursionError) as exc:
            self.automation.external_execution = False
            self.automation._file_changed()
            message = f"{self.current.definition.name}: {path}\n{exc}"
            self._log(message)
            self.active_paths.clear()
            self.executing = False
            self.current = None
            QMessageBox.warning(self.host.window, tr("AutomationTriggers", "実行エラー"), message)

    def _finished(self, message: str, error: bool) -> None:
        if not self.executing:
            return
        self._log(f"{self.current.definition.name}: {message}")
        self.automation._file_changed()
        if error or message != "完了しました。":
            self.active_paths.clear()
        QTimer.singleShot(0, self._next_script)
