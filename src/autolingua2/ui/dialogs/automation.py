from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
import math
import re

from PySide6.QtCore import QElapsedTimer, QEvent, QItemSelectionModel, QObject, QSaveFile, QIODeviceBase, QTimer, Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QFontDatabase, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QDialog, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QSpinBox,
    QTableView, QTextEdit, QWidget,
)

from autolingua2.infrastructure.automation_activity import AutomationAction, AutomationSession
from autolingua2.ir.automation_script import READ_FUNCTIONS, ReadValue, Script, ScriptError, Step
from autolingua2.services.operations.automation import AutomationRunner
from autolingua2.ui.components.script_editor import ScriptEditor
from autolingua2.ui.components.search_bar import SearchBar
from autolingua2.ui.dialogs.base import SimpleDialogController, require_child
from autolingua2.ui.resources.i18n import tr


EXAMPLE = '''string[] languages = ["ja", "th", "ko", "de"]

for string code in languages {
    click("buttonAddLanguage")
    table_row("tableLanguages", code)
    click("buttonAdd")
    click("buttonClose")
}

// click("buttonAdd", "en") selects the row and clicks in one step.
// spin_set("spinFocusPageSize", 100) sets an absolute value.
// spin_add("spinFocusPageSize", 10) adds 10; spin_sub subtracts it.
// int pageSize = spin_get("spinFocusPageSize") reads an integer spin box.
// float rate = spin_get("doubleSpinRate") reads a double spin box.
// combo_select("comboTargetLanguage", "日本語") selects an exact label.
// string language = combo_get("comboTargetLanguage") reads the selected label.
// string name = text_get("editName") reads plain text.
// bool enabled = check_get("checkEnabled") reads the check state.
// int volume = slider_get("sliderVolume") reads the slider value.
// string code = table_row_get("tableLanguages", 1) reads column 1 of the selected row (0-based).
click("buttonTranslateAll")
'''


class AutomationDialogController(QObject):
    """Resolve script operations against widgets in the active application window."""

    def __init__(self, window: QMainWindow, get_icon: Callable[[str], QIcon]) -> None:
        super().__init__(window)
        self.window = window
        self.get_icon = get_icon
        self.dialog = SimpleDialogController("dialogs/AutomationDialog.ui").dialog
        self.dialog.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.dialog.setWindowIcon(window.windowIcon())
        self.editor = require_child(self.dialog, ScriptEditor, "editScript")
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.search_bar = require_child(self.dialog, SearchBar, "searchBar")
        self.search_bar.bind_replace_panel(require_child(self.dialog, QWidget, "replacePanel"))
        self.search = self.search_bar.editor
        self.replace_text = require_child(self.dialog, QLineEdit, "editReplace")
        self.search_result = require_child(self.dialog, QLabel, "labelSearchResult")
        self.cursor_position = require_child(self.dialog, QLabel, "labelCursorPosition")
        self.search_buttons: dict[str, QAbstractButton] = {
            "buttonSearchCase": self.search_bar.case_button,
            "buttonSearchWord": self.search_bar.word_button,
            "buttonSearchRegex": self.search_bar.regex_button,
        }
        self.search_buttons.update({name: require_child(self.dialog, QPushButton, name) for name in (
            "buttonSearchPrevious", "buttonSearchNext", "buttonReplace", "buttonReplaceAll",
        )})
        self.refresh_icons()
        self._search_matches: list[tuple[QTextCursor, re.Match[str]]] = []
        for button in self.search_buttons.values():
            if isinstance(button, QPushButton):
                button.setAutoDefault(False)
        for name in ("buttonSearchCase", "buttonSearchWord", "buttonSearchRegex"):
            self.search_buttons[name].toggled.connect(self._refresh_search)
        self.search.textChanged.connect(self._refresh_search)
        self.search.returnPressed.connect(self._find_match)
        self.search_buttons["buttonSearchPrevious"].clicked.connect(lambda: self._find_match(True))
        self.search_buttons["buttonSearchNext"].clicked.connect(self._find_match)
        self.search_buttons["buttonReplace"].clicked.connect(self._replace_match)
        self.search_buttons["buttonReplaceAll"].clicked.connect(lambda: self._replace_match(True))
        self.editor.textChanged.connect(self._refresh_search)
        self.editor.cursorPositionChanged.connect(self._update_cursor_position)
        self.editor.blockCountChanged.connect(self._update_cursor_position)
        self.log = require_child(self.dialog, QPlainTextEdit, "editLog")
        self.log.setMaximumBlockCount(1000)
        self.file_label = require_child(self.dialog, QLabel, "labelFile")
        self.state = require_child(self.dialog, QLabel, "labelState")
        self.path: Path | None = None
        self.runner = AutomationRunner(self)
        self.runner.action_requested.connect(self._dispatch)
        self.runner.line_changed.connect(self._line)
        self.runner.finished.connect(self._finished)
        self.runner.completion_requested.connect(self._complete)
        self.session: AutomationSession | None = None
        self.action: AutomationAction | None = None
        self.requested_step: Step | None = None
        self.completing = False
        self.ready_elapsed = QElapsedTimer()
        self.ready_elapsed.start()
        self.stable_window: QWidget | None = None
        self.wait_timer = QTimer(self)
        self.wait_timer.setSingleShot(True)
        self.wait_timer.timeout.connect(self._settle)
        self.elapsed = QElapsedTimer()
        self.wait_step: Step | None = None
        self.start_script: Script | None = None
        self.prepared_step: Step | None = None
        self._run_app: QApplication | None = None
        self.buttons = {name: require_child(self.dialog, QPushButton, name) for name in (
            "buttonNew", "buttonOpen", "buttonSave", "buttonSaveAs", "buttonStart", "buttonStop", "buttonClose",
        )}
        self.buttons["buttonNew"].clicked.connect(self._new)
        self.buttons["buttonOpen"].clicked.connect(self._open)
        self.buttons["buttonSave"].clicked.connect(self._save)
        self.buttons["buttonSaveAs"].clicked.connect(lambda: self._save(True))
        self.buttons["buttonStart"].clicked.connect(self._start)
        self.buttons["buttonStop"].clicked.connect(self._stop)
        self.buttons["buttonClose"].clicked.connect(self.dialog.close)
        for button in self.buttons.values():
            button.setAutoDefault(False)
        self.editor.modificationChanged.connect(self._file_changed)
        self.editor.setPlainText(EXAMPLE)
        self.editor.document().setModified(False)
        self.dialog.finished.connect(lambda: self._stop("実行ウィンドウを閉じたため停止しました。"))
        self.dialog.installEventFilter(self)
        self.editor.installEventFilter(self)
        self._file_changed()
        self._update_cursor_position()

    def _update_cursor_position(self) -> None:
        cursor = self.editor.textCursor()
        # Count displayed Unicode characters rather than QTextCursor's UTF-16 units.
        prefix = QTextCursor(cursor)
        prefix.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        self.cursor_position.setText(
            tr("AutomationDialog", "行 {line} / 全{total}行・列 {column}").format(
                line=cursor.blockNumber() + 1, total=self.editor.blockCount(),
                column=len(prefix.selectedText()) + 1,
            )
        )

    def _refresh_search(self) -> None:
        self._search_matches = []
        query = self.search.text()
        regex = self.search_buttons["buttonSearchRegex"].isChecked()
        expression = query if regex else re.escape(query)
        if self.search_buttons["buttonSearchWord"].isChecked():
            expression = r"(?<!\w)(?:" + expression + r")(?!\w)"
        message = tr("AutomationDialog", "検索文字列を入力してください")
        if query:
            flags = re.MULTILINE
            if not self.search_buttons["buttonSearchCase"].isChecked():
                flags |= re.IGNORECASE
            try:
                pattern = re.compile(expression, flags)
                text = self.editor.toPlainText()
                position = offset = 0
                for match in pattern.finditer(text):
                    offset += len(text[position:match.start()].encode("utf-16-le")) // 2
                    length = len(match.group().encode("utf-16-le")) // 2
                    cursor = QTextCursor(self.editor.document())
                    cursor.setPosition(offset)
                    cursor.setPosition(offset + length, QTextCursor.MoveMode.KeepAnchor)
                    self._search_matches.append((cursor, match))
                    position = match.end()
                    offset += length
                message = tr("AutomationDialog", "{count}件一致").format(count=len(self._search_matches))
            except re.error as error:
                message = tr("AutomationDialog", "検索エラー：{error}").format(error=error)
        self.search_result.setText(message)
        found = bool(self._search_matches)
        for name in ("buttonSearchPrevious", "buttonSearchNext"):
            self.search_buttons[name].setEnabled(found)
        for name in ("buttonReplace", "buttonReplaceAll"):
            self.search_buttons[name].setEnabled(found and not self.editor.isReadOnly())

    def _find_match(self, backward: bool = False) -> None:
        if not self._search_matches:
            return
        current = self.editor.textCursor()
        candidates = list(reversed(self._search_matches)) if backward else self._search_matches
        for cursor, _ in candidates:
            if backward:
                eligible = cursor.selectionEnd() <= current.selectionStart()
            else:
                eligible = cursor.selectionStart() >= current.selectionEnd()
            if eligible and not (
                not cursor.hasSelection() and cursor.position() == current.position()
            ):
                break
        else:
            cursor = candidates[0][0]
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def _replace_match(self, all_matches: bool = False) -> None:
        if self.editor.isReadOnly() or not self._search_matches:
            return
        matches = self._search_matches
        if not all_matches:
            current = self.editor.textCursor()
            selected = [item for item in matches if (
                item[0].selectionStart() == current.selectionStart()
                and item[0].selectionEnd() == current.selectionEnd()
            )]
            if not selected:
                self._find_match()
                return
            matches = selected[:1]
        try:
            replacements = [
                (QTextCursor(cursor), match.expand(self.replace_text.text())
                 if self.search_buttons["buttonSearchRegex"].isChecked() else self.replace_text.text())
                for cursor, match in matches
            ]
        except (re.error, IndexError) as error:
            self.search_result.setText(tr("AutomationDialog", "置換式が無効です：{error}").format(error=error))
            return
        edit = self.editor.textCursor()
        edit.beginEditBlock()
        for cursor, replacement in reversed(replacements):
            cursor.insertText(replacement)
        edit.endEditBlock()
        if not all_matches:
            self.editor.setTextCursor(replacements[0][0])
            self._find_match()
        self.search_result.setText(
            self.search_result.text() + " | "
            + tr("AutomationDialog", "{count}箇所を置換").format(count=len(replacements))
        )

    def refresh_icons(self) -> None:
        self.search_bar.set_icons(self.get_icon)
        for name, icon in (
            ("buttonSearchPrevious", "arrow-up"), ("buttonSearchNext", "arrow-down"),
            ("buttonReplace", "replace"), ("buttonReplaceAll", "replace-all"),
        ):
            self.search_buttons[name].setIcon(self.get_icon(icon))

    def show(self) -> None:
        self.dialog.showNormal()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def shutdown(self) -> None:
        self._stop("メインウィンドウを閉じたため停止しました。")
        self.dialog.hide()

    def _file_changed(self) -> None:
        name = str(self.path) if self.path is not None else tr("AutomationDialog", "未保存")
        marker = " *" if self.editor.document().isModified() else ""
        self.file_label.setText(name + marker)

    def _confirm_discard(self) -> bool:
        if not self.editor.document().isModified():
            return True
        result = QMessageBox.question(
            self.dialog, tr("AutomationDialog", "未保存の変更"),
            tr("AutomationDialog", "変更を保存しますか？"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Save:
            return self._save()
        return result == QMessageBox.StandardButton.Discard

    def _new(self) -> None:
        if not self._confirm_discard():
            return
        self.path = None
        self.editor.clear()
        self.editor.document().setModified(False)
        self._file_changed()

    def _open(self) -> None:
        if not self._confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self.dialog, tr("AutomationDialog", "スクリプトを開く"),
                                            "", "AUTOlingua Script (*.als);;All files (*)")
        if not name:
            return
        try:
            text = Path(name).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self.dialog, tr("AutomationDialog", "読み込みエラー"), str(exc))
            return
        self.path = Path(name)
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        self._file_changed()

    def _save(self, save_as: bool = False) -> bool:
        path = self.path
        if save_as or path is None:
            name, _ = QFileDialog.getSaveFileName(self.dialog, tr("AutomationDialog", "スクリプトを保存"),
                                                str(path) if path is not None else "automation.als",
                                                "AUTOlingua Script (*.als);;All files (*)")
            if not name:
                return False
            path = Path(name)
        file = QSaveFile(str(path))
        data = self.editor.toPlainText().encode("utf-8")
        if not file.open(QIODeviceBase.OpenModeFlag.WriteOnly):
            QMessageBox.warning(self.dialog, tr("AutomationDialog", "保存エラー"), file.errorString())
            return False
        if file.write(data) != len(data):
            message = file.errorString()
            file.cancelWriting()
            QMessageBox.warning(self.dialog, tr("AutomationDialog", "保存エラー"), message)
            return False
        if not file.commit():
            QMessageBox.warning(self.dialog, tr("AutomationDialog", "保存エラー"), file.errorString())
            return False
        self.path = path
        self.editor.document().setModified(False)
        self._file_changed()
        return True

    def _start(self) -> None:
        self.log.clear()
        try:
            script = Script(self.editor.toPlainText())
        except ScriptError as exc:
            self._line(exc.token.line)
            self._finished(str(exc), True)
            return
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("QApplicationがありません。")
        if QApplication.activeModalWidget() is not None:
            self._finished(tr("AutomationDialog", "ほかのダイアログを閉じてから開始してください。"), True)
            return
        self._run_app = app
        app.installEventFilter(self)
        self.editor.setReadOnly(True)
        self._set_running(True)
        self.start_script = script
        self.dialog.showMinimized()
        self.elapsed.start()
        self.wait_timer.start(0)

    def _stop(self, message: str = "停止しました。") -> None:
        if self.start_script is not None:
            self._finished(message, False)
        else:
            self.runner.stop(message)

    def _set_running(self, running: bool) -> None:
        for name, button in self.buttons.items():
            if name not in {"buttonStop", "buttonClose"}:
                button.setEnabled(not running)
        self.buttons["buttonStop"].setEnabled(running)
        self.editor.setReadOnly(running)
        self._refresh_search()

    def _line(self, line: int) -> None:
        self.state.setText(tr("AutomationDialog", "実行位置: {line}行").format(line=line))
        cursor = QTextCursor(self.editor.document().findBlockByNumber(line - 1))
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        style = QTextCharFormat()
        style.setBackground(QColor(100, 150, 220, 65))
        selection.format = style
        self.editor.setExtraSelections([selection])
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def _finished(self, message: str, error: bool) -> None:
        if self.session is not None:
            self.session.close()
            self.session.deleteLater()
            self.session = None
        self.action = None
        self.requested_step = None
        self.completing = False
        self.stable_window = None
        self.wait_timer.stop()
        self.wait_step = None
        self.prepared_step = None
        self.start_script = None
        if self._run_app is not None:
            self._run_app.removeEventFilter(self)
            self._run_app = None
        self._set_running(False)
        self.state.setText(tr("AutomationDialog", "エラー") if error else message)
        self.log.appendPlainText(message)

    def _active(self) -> QWidget | None:
        modal = QApplication.activeModalWidget()
        return modal if modal is not None else QApplication.activeWindow()

    def _owns(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            if current is self.window:
                return True
            current = current.parentWidget()
        return False

    def _select_row(self, table: QTableView, key: str) -> None:
        model = table.model()
        selection = table.selectionModel()
        if model is None or selection is None:
            raise ValueError("テーブルのモデルまたは選択モデルがありません。")
        if not table.isVisible() or not table.isEnabled():
            raise ValueError("対象テーブルが非表示または無効です。")
        if table.selectionMode() == QAbstractItemView.SelectionMode.NoSelection:
            raise ValueError("対象テーブルは行を選択できません。")
        matches = [model.index(row, column, table.rootIndex())
                   for row in range(model.rowCount(table.rootIndex()))
                   for column in range(model.columnCount(table.rootIndex()))
                   if model.index(row, column, table.rootIndex()).data() == key]
        if len({index.row() for index in matches}) != 1:
            raise ValueError(f"行を一意に特定できません: {key}")
        index = matches[0]
        flags = model.flags(index)
        if table.isRowHidden(index.row()) or not flags & Qt.ItemFlag.ItemIsEnabled or not flags & Qt.ItemFlag.ItemIsSelectable:
            raise ValueError(f"対象行が非表示または選択できません: {key}")
        table.setCurrentIndex(index)
        selection.select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _button_row(self, button: QAbstractButton) -> tuple[QTableView, int] | None:
        parent = button.parentWidget()
        while parent is not None and not isinstance(parent, QTableView):
            parent = parent.parentWidget()
        if parent is None:
            return None
        model = parent.model()
        if model is None:
            raise ValueError("テーブルのモデルがありません。")
        for row in range(model.rowCount(parent.rootIndex())):
            for column in range(model.columnCount(parent.rootIndex())):
                cell = parent.indexWidget(model.index(row, column, parent.rootIndex()))
                if cell is not None and (cell is button or cell.isAncestorOf(button)):
                    return parent, row
        raise ValueError("ボタンが属する行を特定できません。")

    def _read_value(self, active: QWidget, target: str, step: Step) -> ReadValue:
        widgets = [widget for widget in active.findChildren(QWidget, target)
                   if widget.window() is active and widget.isVisible()]
        if len(widgets) != 1:
            raise ValueError(f"読み取り対象を一意に指定してください: {target}")
        widget = widgets[0]
        operation = step.token.text
        if operation == "spin_get" and isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        if operation == "combo_get" and isinstance(widget, QComboBox):
            if widget.currentIndex() < 0:
                raise ValueError(f"コンボボックスの項目が未選択です: {target}")
            return widget.currentText()
        if operation == "text_get":
            if isinstance(widget, QLineEdit):
                return widget.text()
            if isinstance(widget, (QPlainTextEdit, QTextEdit)):
                return widget.toPlainText()
        if operation == "check_get" and isinstance(widget, QCheckBox):
            if widget.checkState() == Qt.CheckState.PartiallyChecked:
                raise ValueError(f"部分チェック状態はbool型で取得できません: {target}")
            return widget.isChecked()
        if operation == "slider_get" and isinstance(widget, QSlider):
            return widget.value()
        if operation == "table_row_get" and isinstance(widget, QTableView):
            model = widget.model()
            selection = widget.selectionModel()
            if model is None or selection is None:
                raise ValueError("テーブルのモデルまたは選択モデルがありません。")
            rows = {index.row() for index in selection.selectedIndexes() if index.parent() == widget.rootIndex()}
            if len(rows) != 1:
                raise ValueError("読み取る行を1行だけ選択してください。")
            row = next(iter(rows))
            if widget.isRowHidden(row):
                raise ValueError("選択行が非表示です。")
            column = step.column
            if column is None or not 0 <= column < model.columnCount(widget.rootIndex()):
                raise ValueError("列番号がテーブルの範囲外です。")
            value = model.index(row, column, widget.rootIndex()).data()
            if not isinstance(value, str):
                raise ValueError("行キーとして読み取る列には文字列が必要です。")
            return value
        raise ValueError(f"{operation}に対応する種類の部品ではありません: {target}")

    def _dispatch(self, step: Step) -> None:
        if not self.runner.running or self.runner.pending is not step:
            return
        if self.session is None:
            self.session = AutomationSession(self)
        if self.requested_step is not step:
            self.ready_elapsed.restart()
            self.action = None
            self.requested_step = step
            self.stable_window = None
        active = self._active()
        if self._tasks_pending(active):
            self.wait_step = step
            return
        if not self.runner.running:
            return
        if active is None or not self._owns(active) or active is self.dialog:
            self._await_ready(step, "操作対象のアプリ画面")
            return
        widgets = [widget for widget in active.findChildren(QWidget, step.target or "")
                   if widget.window() is active and widget.isVisible()]
        if not widgets or (step.token.text not in READ_FUNCTIONS and not any(w.isEnabled() for w in widgets)):
            self._await_ready(step, step.target or "操作対象")
            return
        if self.action is None:
            self.action = self.session.action(step, active)
        with self.action.scope():
            self._perform(step)

    def _await_ready(self, step: Step | None, label: str) -> None:
        if self.ready_elapsed.elapsed() >= 5000:
            self.runner.fail(f"{label}を操作できるまでの待機がタイムアウトしました。")
            return
        self.state.setText(tr("AutomationDialog", "待機中: {label}").format(label=label))
        self.wait_step = step
        self.wait_timer.start(25)

    def _tasks_pending(self, active: QWidget | None, *, final: bool = False) -> bool:
        session = self.session
        if session is None:
            return False
        failure = session.failure()
        if failure is not None:
            self.runner.fail(f"{failure.label}: {failure.error or '処理に失敗しました。'}",
                             step=failure.action.step if failure.action is not None else None)
            return False
        blocking = session.blocking(active, final=final)
        if not blocking:
            return False
        if final and not session.blocking(active):
            self._await_ready(None, "確認画面への回答")
            return True
        self.state.setText(tr("AutomationDialog", "待機中: {label}").format(label=blocking[0].label))
        self.ready_elapsed.restart()
        self.wait_timer.start(25)
        return True

    def _complete(self) -> None:
        self.completing = True
        self.ready_elapsed.restart()
        self.wait_timer.start(0)

    def _perform(self, step: Step) -> None:
        if not self.runner.running or self.runner.pending is not step:
            return
        try:
            active = self._active()
            if active is None or not self._owns(active) or active is self.dialog:
                raise ValueError("操作対象のアプリ画面がアクティブではありません。")
            target = step.target
            if target is None:
                raise ValueError("操作対象のIDがありません。")
            if step.token.text in READ_FUNCTIONS:
                result = self._read_value(active, target, step)
                arguments = f"{target}, {step.column}" if step.column is not None else target
                self.log.appendPlainText(f"{step.token.line}: {step.token.text}({arguments}) = {result!r}")
                self.runner.acknowledge(step, result)
                return
            if step.token.text == "table_row":
                tables = [table for table in active.findChildren(QTableView, target)
                          if table.window() is active and table.isVisible()]
                if len(tables) != 1 or step.code is None:
                    raise ValueError(f"テーブルと行を一意に指定してください: {target}")
                self._select_row(tables[0], step.code)
                self.log.appendPlainText(f"{step.token.line}: table_row({target}, {step.code})")
                self.wait_step = step
                self.wait_timer.start(0)
                return
            if step.token.text == "combo_select":
                combos = [combo for combo in active.findChildren(QComboBox, target)
                          if combo.window() is active and combo.isVisible()]
                if len(combos) != 1 or step.code is None:
                    raise ValueError(f"コンボボックスと項目を一意に指定してください: {target}")
                combo = combos[0]
                if not combo.isEnabled():
                    raise ValueError(f"対象コンボボックスが無効です: {target}")
                matches = [index for index in range(combo.count()) if combo.itemText(index) == step.code]
                if len(matches) != 1:
                    raise ValueError(f"項目を一意に特定できません: {step.code}")
                index = matches[0]
                flags = combo.model().index(index, combo.modelColumn(), combo.rootModelIndex()).flags()
                if not flags & Qt.ItemFlag.ItemIsEnabled or not flags & Qt.ItemFlag.ItemIsSelectable:
                    raise ValueError(f"対象項目を選択できません: {step.code}")
                combo.setCurrentIndex(index)
                combo.activated.emit(index)
                self.log.appendPlainText(f"{step.token.line}: combo_select({target}, {step.code})")
                self.wait_step = step
                self.wait_timer.start(0)
                return
            if step.token.text in {"spin_set", "spin_add", "spin_sub"}:
                spins = [widget for widget in active.findChildren(QWidget, target)
                         if isinstance(widget, (QSpinBox, QDoubleSpinBox))
                         and widget.window() is active and widget.isVisible()]
                if len(spins) != 1:
                    raise ValueError(f"スピンボックスを一意に指定してください: {target}")
                spin = spins[0]
                if not spin.isEnabled() or spin.isReadOnly():
                    raise ValueError(f"対象スピンボックスを変更できません: {target}")
                amount = step.value
                if amount is None:
                    raise ValueError("スピンボックスの数値が指定されていません。")
                if not math.isfinite(amount):
                    raise ValueError("有限の数値を指定してください。")
                if step.token.text != "spin_set" and amount < 0:
                    raise ValueError("増減量には0以上の数値を指定してください。")
                value = (spin.value() + amount if step.token.text == "spin_add" else
                         spin.value() - amount if step.token.text == "spin_sub" else amount)
                if not spin.minimum() <= value <= spin.maximum():
                    raise ValueError(f"スピンボックスの範囲外です: {value}")
                if isinstance(spin, QSpinBox):
                    if isinstance(value, float) and not value.is_integer():
                        raise ValueError("整数のスピンボックスには整数値が必要です。")
                    spin.setValue(int(value))
                else:
                    spin.setValue(value)
                self.log.appendPlainText(f"{step.token.line}: {step.token.text}({target}, {amount})")
                self.wait_step = step
                self.wait_timer.start(0)
                return
            candidates: list[QAbstractButton] = []
            row_buttons: list[tuple[QAbstractButton, QTableView, int]] = []
            for button in active.findChildren(QAbstractButton, target):
                if button.window() is not active or not button.isVisible():
                    continue
                location = self._button_row(button)
                if location is None:
                    if step.code is None:
                        candidates.append(button)
                else:
                    table, row = location
                    if table.isVisible() and not table.isRowHidden(row):
                        row_buttons.append((button, table, row))
            if step.code is not None and self.prepared_step is not step:
                tables = {table for _, table, _ in row_buttons}
                if len(tables) != 1:
                    raise ValueError(f"対象テーブルを一意に特定できません: {target}")
                self._select_row(next(iter(tables)), step.code)
            for button, table, row in row_buttons:
                selection = table.selectionModel()
                if selection is None:
                    raise ValueError("テーブルの選択モデルがありません。")
                if {index.row() for index in selection.selectedIndexes()} == {row}:
                    candidates.append(button)
            if len(candidates) != 1:
                raise ValueError(f"ボタンを一意に特定できません。行内のボタンは1行を選択してください: {target}")
            button = candidates[0]
            location = self._button_row(button)
            if location is not None and self.prepared_step is not step:
                table, row = location
                model = table.model()
                if model is None:
                    raise ValueError("テーブルのモデルがありません。")
                table.scrollTo(model.index(row, 0, table.rootIndex()), QAbstractItemView.ScrollHint.PositionAtCenter)
                self.prepared_step = step
                self.wait_step = step
                self.wait_timer.start(0)
                return
            if not button.isVisible() or not button.isEnabled():
                raise ValueError("対象ボタンが非表示または無効です。")
            self.log.appendPlainText(f"{step.token.line}: {step.target}" + (f" ({step.code})" if step.code else ""))
            self.wait_step = step
            self.prepared_step = None
            # Schedule completion observation BEFORE click: opening a modal dialog
            # enters its nested event loop and click() only returns after it closes.
            self.wait_timer.start(0)
            button.click()
        except (ValueError, RuntimeError) as exc:
            self.runner.fail(str(exc))

    def _settle(self) -> None:
        script = self.start_script
        if script is not None:
            if self._active() is self.window:
                self.start_script = None
                self.runner.start(script)
            elif self.elapsed.elapsed() >= 5000:
                self._finished("メインウィンドウがアクティブになるまでの待機がタイムアウトしました。", True)
            else:
                self.wait_timer.start(25)
            return
        if self.completing:
            active = self._active()
            if self._tasks_pending(active, final=True) or not self.runner.running:
                return
            self.runner.stop("完了しました。")
            return
        step = self.wait_step
        if not self.runner.running or step is None or self.runner.pending is not step:
            return
        active = self._active()
        if self._tasks_pending(active) or not self.runner.running:
            return
        if self.action is None or self.prepared_step is step:
            self._dispatch(step)
            return
        if active is None or not self._owns(active) or active is self.dialog:
            self._await_ready(step, "操作後のアプリ画面")
            return
        if self.stable_window is not active:
            self.stable_window = active
            self.wait_timer.start(0)
            return
        self.wait_step = None
        self.runner.acknowledge(step)

    def _script_key_press(self, event: QKeyEvent) -> bool:
        if self.editor.isReadOnly() or event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            return False
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            return False
        before = QTextCursor(cursor)
        before.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        prefix = before.selectedText()
        after = QTextCursor(cursor)
        after.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        suffix = after.selectedText()
        in_string = escaped = in_comment = False
        for index, character in enumerate(prefix):
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
            elif character == '"':
                in_string = True
            elif prefix[index:index + 2] == "//":
                in_comment = True
                break

        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            indent = prefix[:len(prefix) - len(prefix.lstrip(" \t"))]
            opens_block = not in_string and not in_comment and prefix.rstrip().endswith("{")
            inner_indent = indent + "    " if opens_block else indent
            cursor.beginEditBlock()
            cursor.insertText("\n" + inner_indent)
            if opens_block and suffix.lstrip(" \t").startswith("}"):
                inner_position = cursor.position()
                whitespace = suffix[:len(suffix) - len(suffix.lstrip(" \t"))]
                for _ in whitespace:
                    cursor.deleteChar()
                cursor.insertText("\n" + indent)
                cursor.setPosition(inner_position)
            cursor.endEditBlock()
        elif in_string or in_comment:
            return False
        elif event.text() == "{":
            cursor.beginEditBlock()
            cursor.insertText("{}")
            cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
            cursor.endEditBlock()
        elif event.text() == "}" and suffix.startswith("}"):
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
        elif event.key() == Qt.Key.Key_Backspace and prefix.endswith("{") and suffix.startswith("}"):
            cursor.beginEditBlock()
            cursor.deletePreviousChar()
            cursor.deleteChar()
            cursor.endEditBlock()
        else:
            return False
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.editor and isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if self._script_key_press(event):
                return True
        if watched is self.dialog and isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.dialog.close()
            return True
        if watched is self.dialog and event.type() == QEvent.Type.Close:
            self._stop("実行ウィンドウを閉じたため停止しました。")
            if not self._confirm_discard():
                event.ignore()
                return True
        if self.runner.running or self.start_script is not None:
            if (self.runner.running and isinstance(watched, QMessageBox) and event.type() == QEvent.Type.Show
                    and self._owns(watched) and watched.icon() in {QMessageBox.Icon.Warning, QMessageBox.Icon.Critical}
                    and not watched.standardButtons() & (QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                                        | QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Ignore)):
                self.runner.fail(watched.text())
            if watched is self.window and event.type() == QEvent.Type.Close:
                self._stop("メインウィンドウを閉じたため停止しました。")
            elif event.spontaneous() and event.type() in {
                QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel,
            } and isinstance(watched, QWidget):
                root = watched.window()
                if root is self.window or (root.objectName() == "WorkspaceLanguageDialog" and root.parentWidget() is self.window):
                    self._stop("手動操作を検知したため停止しました。")
        return super().eventFilter(watched, event)
