"""Shortcut settings: draft presets, multiple bindings and conflict resolution."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGroupBox, QHeaderView, QKeySequenceEdit,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from autolingua2.ir.shortcuts import ShortcutPreset
from autolingua2.ui.resources.i18n import tr
from autolingua2.ui.shortcuts import PORTABLE, ShortcutConflict, ShortcutManager, normalize_key
from .base import load_ui, require_child


class ShortcutSettingsPage:
    def __init__(self, parent: QWidget) -> None:
        self.manager = ShortcutManager.current()
        self.widget = load_ui("dialogs/settings/ShortcutPage.ui", parent)
        self.presets = self.manager.store.load()
        self.errors = list(self.manager.store.errors)
        # The in-memory standard set also permits using defaults when its file is missing.
        if "default" not in self.presets:
            self.presets["default"] = ShortcutPreset("default", tr("Shortcuts", "AUTOlingua2 標準"))
        self.baseline = deepcopy(self.presets)
        self.selected = self.manager.selected if self.manager.selected in self.presets else "default"
        self.command_id = ""
        self.index_mode = self.manager.index_mode
        self.items: dict[str, QTreeWidgetItem] = {}
        self.conflicts: list[ShortcutConflict] = []
        self.combo = require_child(self.widget, QComboBox, "comboSet")
        self.tree = require_child(self.widget, QTreeWidget, "treeShortcuts")
        self.keys = require_child(self.widget, QListWidget, "listKeys")
        self.search = require_child(self.widget, QLineEdit, "editSearch")
        self.group = require_child(self.widget, QGroupBox, "groupConflict")
        self.index_on = self.button("buttonIndexOn")
        self.index_off = self.button("buttonIndexOff")
        (self.index_on if self.manager.debug and self.index_mode else self.index_off).setChecked(True)
        for button in (self.index_on, self.index_off):
            button.setEnabled(self.manager.debug)
            if not self.manager.debug:
                button.setToolTip(tr("Shortcuts", "デバッグモードで起動した場合だけ変更できます。"))
        self.index_on.toggled.connect(self._index_changed)
        self.combo.currentIndexChanged.connect(self._set_changed)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda _item, column: self._edit_key(False) if column == 1 else None)
        self.keys.currentRowChanged.connect(lambda _row: self._update_key_buttons())
        self.search.textChanged.connect(self._filter)
        self.button("buttonNewSet").clicked.connect(self._new_set)
        self.button("buttonDeleteSet").clicked.connect(self._delete_set)
        self.button("buttonAddKey").clicked.connect(lambda: self._edit_key(True))
        self.button("buttonChangeKey").clicked.connect(lambda: self._edit_key(False))
        self.button("buttonRemoveKey").clicked.connect(self._remove_key)
        self.button("buttonUndo").clicked.connect(self._undo)
        self.button("buttonClear").clicked.connect(lambda: self._assign([]))
        self.button("buttonReset").clicked.connect(self._reset)
        self.button("buttonGoConflict").clicked.connect(self._go_conflict)
        self.button("buttonReplace").clicked.connect(self._replace)
        errors = require_child(self.widget, QLabel, "labelErrors")
        errors.setText("\n".join(self.errors))
        errors.setVisible(bool(self.errors))
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._refresh_sets()

    def button(self, name: str) -> QPushButton:
        return require_child(self.widget, QPushButton, name)

    @property
    def preset(self) -> ShortcutPreset:
        return self.presets[self.selected]

    def _index_changed(self, checked: bool) -> None:
        if self.manager.debug:
            self.index_mode = checked

    def _refresh_sets(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for preset in self.presets.values():
            self.combo.addItem(preset.name, preset.id)
        self.combo.setCurrentIndex(self.combo.findData(self.selected))
        self.combo.blockSignals(False)
        self.button("buttonDeleteSet").setEnabled(self.selected != "default")
        self._populate()

    def _set_changed(self, index: int) -> None:
        value = self.combo.itemData(index)
        if isinstance(value, str) and value in self.presets:
            self.selected = value
            self.button("buttonDeleteSet").setEnabled(value != "default")
            self._populate()

    def _scope_label(self, scope: str) -> str:
        return {"main": tr("Shortcuts", "メイン画面"),
                "main/focus": tr("Shortcuts", "フォーカス編集"),
                "export": tr("Shortcuts", "訳文出力")}.get(scope, scope)

    def _populate(self) -> None:
        previous = self.command_id
        self.tree.blockSignals(True)
        self.tree.clear()
        self.items.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for command in self.manager.commands.values():
            if command.location not in groups:
                groups[command.location] = QTreeWidgetItem(self.tree, [command.location])
                groups[command.location].setExpanded(True)
            keys = self.manager.effective(command.id, self.preset)
            item = QTreeWidgetItem(groups[command.location], [command.name, " / ".join(keys), self._scope_label(command.scope)])
            item.setData(0, Qt.ItemDataRole.UserRole, command.id)
            self.items[command.id] = item
        self.tree.blockSignals(False)
        if previous in self.items:
            self.tree.setCurrentItem(self.items[previous])
        else:
            self.command_id = ""
        self._selection_changed()
        self._filter(self.search.text())

    def select_command(self, command_id: str) -> None:
        if command_id in self.items:
            self.search.clear()
            item = self.items[command_id]
            parent = item.parent()
            if parent is not None:
                parent.setExpanded(True)
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def _selection_changed(self) -> None:
        item = self.tree.currentItem()
        value = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        self.command_id = value if isinstance(value, str) else ""
        self.keys.clear()
        command = self.manager.commands.get(self.command_id)
        require_child(self.widget, QLabel, "labelSelected").setText(
            tr("Shortcuts", "選択中のコマンド：{name}").format(name=command.name if command else ""))
        require_child(self.widget, QLabel, "labelLocation").setText(
            tr("Shortcuts", "場所：{location}").format(location=command.location if command else ""))
        if command is not None:
            self.keys.addItems(self.manager.effective(command.id, self.preset))
            if self.keys.count():
                self.keys.setCurrentRow(0)
        for name in ("buttonAddKey", "buttonUndo", "buttonClear", "buttonReset"):
            self.button(name).setEnabled(command is not None)
        self._update_key_buttons()
        self._refresh_conflicts()

    def _update_key_buttons(self) -> None:
        enabled = bool(self.command_id) and self.keys.currentRow() >= 0
        self.button("buttonChangeKey").setEnabled(enabled)
        self.button("buttonRemoveKey").setEnabled(enabled)

    def _filter(self, query: str) -> None:
        query = query.casefold()
        for item in self.items.values():
            parent = item.parent()
            location = parent.text(0) if parent is not None else ""
            item.setHidden(query not in " ".join([location, *(item.text(column) for column in range(3))]).casefold())
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            if parent is None:
                raise RuntimeError("ショートカットの分類がありません")
            children: list[QTreeWidgetItem] = []
            for row in range(parent.childCount()):
                child = parent.child(row)
                if child is None:
                    raise RuntimeError("ショートカットの項目がありません")
                children.append(child)
            parent.setHidden(all(child.isHidden() for child in children))

    def _assign(self, values: list[str]) -> None:
        if not self.command_id:
            return
        self.preset.shortcuts[self.command_id] = values
        self._populate()

    def _edit_key(self, adding: bool) -> None:
        if not self.command_id:
            return
        values = self.manager.effective(self.command_id, self.preset)
        row = self.keys.currentRow()
        if not adding and not 0 <= row < len(values):
            adding = True
        dialog = QDialog(self.widget)
        dialog.setWindowTitle(tr("Shortcuts", "ショートカットを入力"))
        layout = QVBoxLayout(dialog)
        editor = QKeySequenceEdit(dialog)
        if not adding:
            editor.setKeySequence(QKeySequence(values[row]))
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        QTimer.singleShot(0, editor.setFocus)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            key = normalize_key(editor.keySequence().toString(PORTABLE))
            if key in values and (adding or values[row] != key):
                return
            if adding:
                values.append(key)
            else:
                values[row] = key
            candidate = deepcopy(self.preset)
            candidate.shortcuts[self.command_id] = values
            self.manager.validate(candidate)
        except ValueError as error:
            QMessageBox.warning(self.widget, tr("Shortcuts", "キーの割り当て"), str(error))
            return
        self._assign(values)

    def _remove_key(self) -> None:
        values = self.manager.effective(self.command_id, self.preset)
        row = self.keys.currentRow()
        if 0 <= row < len(values):
            values.pop(row)
            self._assign(values)

    def _undo(self) -> None:
        if not self.command_id:
            return
        original = self.baseline.get(self.selected)
        if original is not None and self.command_id in original.shortcuts:
            self._assign(list(original.shortcuts[self.command_id]))
        else:
            self.preset.shortcuts.pop(self.command_id, None)
            self._populate()

    def _reset(self) -> None:
        if self.command_id:
            self._assign(list(self.manager.commands[self.command_id].defaults))

    def _refresh_conflicts(self) -> None:
        try:
            conflicts = self.manager.conflicts(self.preset)
        except ValueError:
            conflicts = []
        self.conflicts = [conflict for conflict in conflicts if self.command_id in (conflict.command_id, conflict.other_id)]
        self.group.setVisible(bool(self.conflicts))
        descriptions: list[str] = []
        for conflict in self.conflicts:
            other_id = conflict.other_id if conflict.command_id == self.command_id else conflict.command_id
            other = self.manager.commands.get(other_id)
            name = f"{other.location} > {other.name} ({self._scope_label(other.scope)})" if other else tr("Shortcuts", "文字編集の基本操作（変更不可）")
            descriptions.append(tr("Shortcuts", "{key}：{name}").format(key=conflict.key, name=name))
        require_child(self.widget, QLabel, "labelConflict").setText("\n".join(descriptions))
        editable = bool(self.conflicts) and all(conflict.other_id for conflict in self.conflicts)
        self.button("buttonReplace").setEnabled(editable)
        self.button("buttonGoConflict").setEnabled(editable)

    def _go_conflict(self) -> None:
        if self.conflicts:
            conflict = self.conflicts[0]
            self.select_command(conflict.other_id if conflict.command_id == self.command_id else conflict.command_id)

    def _replace(self) -> None:
        for conflict in self.conflicts:
            if not conflict.other_id:
                return
            other_id = conflict.other_id if conflict.command_id == self.command_id else conflict.command_id
            other_key = conflict.other_key if conflict.command_id == self.command_id else conflict.key
            values = self.manager.effective(other_id, self.preset)
            self.preset.shortcuts[other_id] = [key for key in values if key != other_key]
        self._populate()

    def _new_set(self) -> None:
        widget = load_ui("dialogs/ShortcutPresetDialog.ui", self.widget)
        if not isinstance(widget, QDialog):
            raise TypeError("ShortcutPresetDialog.ui must be a QDialog")
        name = require_child(widget, QLineEdit, "editName")
        box = require_child(widget, QDialogButtonBox, "buttonBox")
        save = box.button(QDialogButtonBox.StandardButton.Save)
        if save is None:
            raise RuntimeError("Missing preset save button")
        save.setEnabled(False)
        name.textChanged.connect(lambda value: save.setEnabled(bool(value.strip())))
        if widget.exec() != QDialog.DialogCode.Accepted:
            return
        preset = deepcopy(self.preset)
        preset.id = uuid4().hex
        preset.name = name.text().strip()
        preset.description = require_child(widget, QLineEdit, "editDescription").text()
        preset.author = require_child(widget, QLineEdit, "editAuthor").text()
        preset.tags = [tag.strip() for tag in require_child(widget, QLineEdit, "editTags").text().split(",") if tag.strip()]
        self.presets[preset.id] = preset
        self.selected = preset.id
        self._refresh_sets()

    def _delete_set(self) -> None:
        if self.selected == "default":
            return
        if QMessageBox.question(self.widget, tr("Shortcuts", "セット削除"),
                                tr("Shortcuts", "このセットを削除しますか？ 確定・適用時にファイルを削除します。")) != QMessageBox.StandardButton.Yes:
            return
        del self.presets[self.selected]
        self.selected = "default"
        self._refresh_sets()

    def validate(self) -> bool:
        try:
            for preset in self.presets.values():
                if self.baseline.get(preset.id) != preset or preset.id == self.selected:
                    self.manager.validate(preset)
                    conflicts = self.manager.conflicts(preset)
                    if conflicts:
                        self.selected = preset.id
                        self._refresh_sets()
                        self.select_command(conflicts[0].command_id)
                        raise ValueError(tr("Shortcuts", "キーの競合を解消してください。"))
        except ValueError as error:
            QMessageBox.warning(self.widget, tr("Shortcuts", "ショートカット設定"), str(error))
            return False
        return True

    def save(self) -> None:
        self.manager.commit(self.presets, self.selected, self.index_mode, self.baseline)
        self.baseline = deepcopy(self.presets)
