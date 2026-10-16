"""Qt bindings, scope-aware validation and activation of shortcut presets."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import sys
from typing import Protocol, runtime_checkable
import weakref

from PySide6.QtCore import QKeyCombination, QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QAbstractButton, QMainWindow, QMenu, QWidget
from shiboken6 import isValid

from autolingua2.ir.shortcuts import ShortcutCommand, ShortcutPreset, scopes_overlap
from autolingua2.services.settings_store import load_shortcut_preferences, save_shortcut_preferences
from autolingua2.services.shortcut_presets import ShortcutPresetStore
from autolingua2.ui.i18n import tr


PORTABLE = QKeySequence.SequenceFormat.PortableText


@runtime_checkable
class _KeySequenceEntries(Protocol):
    """PySide exposes indexing at runtime but omits it from its QKeySequence stub."""
    def __getitem__(self, index: int, /) -> QKeyCombination: ...


def _combinations(sequence: QKeySequence) -> tuple[QKeyCombination, ...]:
    if not isinstance(sequence, _KeySequenceEntries):
        raise TypeError("QKeySequence does not expose key combinations")
    return tuple(sequence[index] for index in range(sequence.count()))


def normalize_key(key: str) -> str:
    sequence = QKeySequence.fromString(key, PORTABLE)
    if sequence.isEmpty() or any(entry.key() == Qt.Key.Key_unknown or entry.key().value == 0
                                 for entry in _combinations(sequence)):
        raise ValueError(tr("Shortcuts", "無効なキーです：{key}").format(key=key))
    return sequence.toString(PORTABLE)


def keys_overlap(first: str, second: str) -> bool:
    a, b = QKeySequence(first), QKeySequence(second)
    return a.matches(b) != QKeySequence.SequenceMatch.NoMatch or b.matches(a) != QKeySequence.SequenceMatch.NoMatch


@dataclass(frozen=True)
class ShortcutConflict:
    command_id: str
    key: str
    other_id: str
    other_key: str


class ShortcutManager(QObject):
    changed = Signal()
    edit_requested = Signal(str)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.commands: dict[str, ShortcutCommand] = {}
        self.targets: dict[str, list[weakref.ReferenceType[QAction]]] = {}
        self.menus: list[weakref.ReferenceType[QMenu]] = []
        self.store = ShortcutPresetStore()
        self.presets: dict[str, ShortcutPreset] = {}
        self.selected, self.index_mode = load_shortcut_preferences()
        self.debug = "--debug" in sys.argv
        self.active = ShortcutPreset("default", tr("Shortcuts", "AUTOlingua2 標準"))
        self.errors: list[str] = []
        self._reserved: set[str] = set()
        reserved = {QKeySequence.StandardKey.Copy, QKeySequence.StandardKey.Cut,
                    QKeySequence.StandardKey.Paste, QKeySequence.StandardKey.Undo, QKeySequence.StandardKey.Redo}
        reserved.update(standard for standard in QKeySequence.StandardKey
                        if standard.name.startswith(("MoveTo", "Select", "Delete")))
        for standard in reserved:
            self._reserved.update(key.toString(PORTABLE) for key in QKeySequence.keyBindings(standard))
        self.commands["export.address"] = ShortcutCommand(
            "export.address", tr("Shortcuts", "アドレス入力開始"), tr("Shortcuts", "訳文出力"),
            "export", ("Ctrl+L", "Alt+D"),
        )

    @staticmethod
    def current() -> ShortcutManager:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication is not running")
        manager = app.findChild(ShortcutManager)
        if manager is None:
            raise RuntimeError("ShortcutManager has not been initialized")
        return manager

    def register(self, command: ShortcutCommand, action: QAction, owner: QWidget) -> None:
        if command.id in self.commands and self.commands[command.id] != command:
            raise ValueError(f"Duplicate shortcut command: {command.id}")
        self.commands[command.id] = command
        action.setProperty("shortcutId", command.id)
        owner.addAction(action)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut if "/" in command.scope
                                  else Qt.ShortcutContext.WindowShortcut)
        self.targets.setdefault(command.id, []).append(weakref.ref(action))
        self._apply_action(command, action)

    def bind_widget(self, widget: QWidget, command_id: str) -> None:
        widget.setProperty("shortcutId", command_id)

    def register_main_window(self, window: QMainWindow, focus: QWidget, save_menu: QMenu) -> None:
        def visit(menu: QMenu, path: str) -> None:
            self.menus.append(weakref.ref(menu))
            for action in menu.actions():
                nested = action.menu()
                if isinstance(nested, QMenu):
                    visit(nested, f"{path} > {nested.title().replace('&', '')}")
                elif not action.isSeparator() and action.objectName():
                    command_id = action.objectName()
                    if command_id not in self.commands:
                        self.register(ShortcutCommand(
                            command_id, action.text().replace("&", ""), path, "main",
                            tuple(key.toString(PORTABLE) for key in action.shortcuts()),
                        ), action, window)
        for action in window.menuBar().actions():
            menu = action.menu()
            if isinstance(menu, QMenu):
                visit(menu, menu.title().replace("&", ""))
        self.menus.append(weakref.ref(save_menu))
        for action in save_menu.actions():
            if action.isSeparator():
                continue
            self.register(ShortcutCommand(
                action.objectName(), action.text(), tr("Shortcuts", "フォーカス編集 > 保存"), "main/focus",
                tuple(key.toString(PORTABLE) for key in action.shortcuts()),
            ), action, focus)
        # Designer buttons connected to the same operation use the same command ID.
        for button_name, command_id in {
            "buttonSaveSplit": "focus.save_next", "buttonListMode": "actionListMode",
            "buttonDashboardMode": "actionDashboardMode", "buttonFocusMode": "actionFocusMode",
            "buttonManageGlossary": "actionGlossary", "buttonProjectSourceUpdate": "actionCheckSourceUpdates",
        }.items():
            button = window.findChild(QWidget, button_name)
            if button is not None and command_id in self.commands:
                self.bind_widget(button, command_id)

    def effective(self, command_id: str, preset: ShortcutPreset | None = None) -> list[str]:
        command = self.commands[command_id]
        return list((preset or self.active).shortcuts.get(command_id, list(command.defaults)))

    def conflicts(self, preset: ShortcutPreset) -> list[ShortcutConflict]:
        result: list[ShortcutConflict] = []
        commands = list(self.commands.values())
        for index, command in enumerate(commands):
            for key in self.effective(command.id, preset):
                for reserved in self._reserved:
                    if keys_overlap(key, reserved):
                        result.append(ShortcutConflict(command.id, key, "", reserved))
                for other in commands[index + 1:]:
                    if not scopes_overlap(command.scope, other.scope):
                        continue
                    for other_key in self.effective(other.id, preset):
                        if keys_overlap(key, other_key):
                            result.append(ShortcutConflict(command.id, key, other.id, other_key))
                own = self.effective(command.id, preset)
                for other_key in own[own.index(key) + 1:]:
                    if keys_overlap(key, other_key):
                        result.append(ShortcutConflict(command.id, key, command.id, other_key))
        return result

    def validate(self, preset: ShortcutPreset) -> None:
        for command_id, values in preset.shortcuts.items():
            normalized = [normalize_key(key) for key in values]
            if len(set(normalized)) != len(normalized):
                raise ValueError(tr("Shortcuts", "同じキーが重複しています：{id}").format(id=command_id))
            if command_id not in self.commands:
                continue
            for key in normalized:
                sequence = QKeySequence(key)
                for combination in _combinations(sequence):
                    code = combination.key()
                    modifiers = combination.keyboardModifiers()
                    if code in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Return, Qt.Key.Key_Enter) and not modifiers:
                        raise ValueError(tr("Shortcuts", "確定・取消・移動の基本キーは変更できません。"))
                    if not modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
                        if not Qt.Key.Key_F1 <= code <= Qt.Key.Key_F35:
                            raise ValueError(tr("Shortcuts", "入力を妨げるキーにはCtrl・Alt・Metaのいずれかが必要です。"))
            preset.shortcuts[command_id] = normalized

    def load(self) -> None:
        first_run = not self.store.directory.exists()
        self.presets = self.store.load()
        self.errors = list(self.store.errors)
        if first_run:
            try:
                self.store.write(self.active)
                self.presets["default"] = deepcopy(self.active)
            except OSError as error:
                self.errors.append(str(error))
        for preset in self.presets.values():
            try:
                self.validate(preset)
            except ValueError as error:
                self.errors.append(f"{preset.name}: {error}")
        selected = self.presets.get(self.selected)
        try:
            if selected is None:
                raise ValueError(tr("Shortcuts", "選択中のセットが見つかりません。"))
            self.validate(selected)
            if self.conflicts(selected):
                raise ValueError(tr("Shortcuts", "選択中のセットに競合があります。"))
            self.active = deepcopy(selected)
        except ValueError as error:
            self.errors.append(str(error))
            self.selected = "default"
        self.apply()

    def apply(self) -> None:
        for reference in self.menus:
            menu = reference()
            if menu is not None and isValid(menu):
                menu.setToolTipsVisible(self.debug and self.index_mode)
        for command_id, refs in self.targets.items():
            alive: list[weakref.ReferenceType[QAction]] = []
            for reference in refs:
                action = reference()
                if action is not None and isValid(action):
                    self._apply_action(self.commands[command_id], action)
                    alive.append(reference)
            self.targets[command_id] = alive
        self.changed.emit()

    def _apply_action(self, command: ShortcutCommand, action: QAction) -> None:
        action.setShortcuts([QKeySequence(key) for key in self.effective(command.id)])

    def commit(self, presets: dict[str, ShortcutPreset], selected: str, index_mode: bool,
               baseline: dict[str, ShortcutPreset]) -> None:
        for preset in presets.values():
            if baseline.get(preset.id) != preset or preset.id == selected:
                self.validate(preset)
                if self.conflicts(preset):
                    raise ValueError(tr("Shortcuts", "キーの競合を解消してください：{name}").format(name=preset.name))
        modified = [preset for key, preset in presets.items() if baseline.get(key) != preset]
        deleted = [key for key in baseline if key not in presets]
        paths = {preset.id: self.store.paths.get(preset.id, self.store.path_for(preset.id)) for preset in modified}
        paths.update({key: self.store.paths[key] for key in deleted})
        backups = {path: path.read_bytes() if path.exists() else None for path in paths.values()}
        old_paths = dict(self.store.paths)
        old_preferences = load_shortcut_preferences()
        try:
            for preset in modified:
                path = paths[preset.id]
                if preset.id not in self.store.paths and path.exists():
                    raise OSError(f"Preset file already exists: {path}")
                self.store.write(preset)
            save_shortcut_preferences(selected, index_mode)
            for key in deleted:
                paths[key].unlink()
        except (OSError, ValueError):
            for path, payload in backups.items():
                if payload is None:
                    path.unlink(missing_ok=True)
                else:
                    self.store.write_bytes(path, payload)
            save_shortcut_preferences(*old_preferences)
            self.store.paths = old_paths
            raise
        for key in deleted:
            self.store.paths.pop(key, None)
        self.presets = deepcopy(presets)
        self.selected, self.index_mode = selected, index_mode
        self.active = deepcopy(presets[selected])
        self.apply()

    def command_for(self, widget: QWidget) -> ShortcutCommand | None:
        current: QWidget | None = widget
        while current is not None:
            command_id = current.property("shortcutId")
            if isinstance(command_id, str) and command_id in self.commands:
                return self.commands[command_id]
            if isinstance(current, QAbstractButton):
                for action in current.actions():
                    command_id = action.property("shortcutId")
                    if isinstance(command_id, str) and command_id in self.commands:
                        return self.commands[command_id]
            current = current.parentWidget()
        return None
