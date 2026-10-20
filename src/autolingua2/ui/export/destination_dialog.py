"""Reusable folder and file output destination dialog."""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QDir, QEvent, QModelIndex, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QFileSystemModel, QFormLayout, QHeaderView, QInputDialog,
    QHBoxLayout, QLineEdit, QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget,
    QToolButton, QTreeView, QWidget,
)

from autolingua2.ui.dialogs.base import SimpleDialogController, require_child
from autolingua2.ui.resources.i18n import tr


class _AddressBar(QObject):
    """Manage the two Designer pages and their path-dependent buttons."""
    def __init__(self, dialog: QWidget, model: QFileSystemModel,
                 navigate: Callable[[Path], bool]) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._model = model
        self._navigate = navigate
        self._stack = require_child(dialog, QStackedWidget, "stackLocation")
        self._page = require_child(dialog, QWidget, "pageBreadcrumbs")
        self._input_page = require_child(dialog, QWidget, "pageLocationInput")
        self._edit = require_child(dialog, QLineEdit, "editLocation")
        self._layout = require_child(dialog, QHBoxLayout, "layoutBreadcrumbs")
        self._ancestors = require_child(dialog, QToolButton, "buttonAncestors")
        self._blank = require_child(dialog, QPushButton, "buttonEditLocation")
        self._path: Path | None = None
        self._buttons: list[tuple[Path, QToolButton, QToolButton]] = []
        self._hidden: list[Path] = []
        self._loaded: set[Path] = set()
        self._pending_menu: tuple[Path, QMenu] | None = None
        self._submitting = False
        self._resize_pending = False
        self._ancestors.hide()
        self._stack.setCurrentWidget(self._page)
        self._edit.installEventFilter(self)
        self._stack.installEventFilter(self)
        self._blank.clicked.connect(self._begin_edit)
        self._ancestors.clicked.connect(self._show_ancestors)
        self._model.directoryLoaded.connect(self._directory_loaded)
        self._model.rowsInserted.connect(self._children_inserted)
        from autolingua2.ui.shortcuts import ShortcutManager
        manager = ShortcutManager.current()
        action = require_child(dialog, QAction, "actionEditExportAddress")
        action.triggered.connect(self._begin_edit)
        manager.register(manager.commands["export.address"], action, dialog)
        manager.bind_widget(self._blank, "export.address")
        manager.bind_widget(self._stack, "export.address")

    def set_path(self, path: Path) -> None:
        self._path = path
        self._edit.setText(str(path))
        self._stack.setCurrentWidget(self._page)
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                raise RuntimeError("パンくずのレイアウト項目を取得できません。")
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._buttons.clear()
        for ancestor in [*reversed(path.parents), path]:
            name = QToolButton(self._page)
            name.setAutoRaise(True)
            name.setText(ancestor.name or str(ancestor))
            name.setToolTip(str(ancestor))
            name.clicked.connect(lambda checked=False, target=ancestor: self._navigate(target))
            arrow = QToolButton(self._page)
            arrow.setAutoRaise(True)
            arrow.setText("›")
            arrow.setToolTip(tr("ExportDialog", "子フォルダを表示"))
            arrow.clicked.connect(lambda checked=False, target=ancestor, button=arrow:
                                  self._show_children(target, button))
            self._layout.addWidget(name)
            self._layout.addWidget(arrow)
            self._buttons.append((ancestor, name, arrow))
        self._fit_buttons()

    def _begin_edit(self) -> None:
        if self._path is None:
            return
        self._edit.setText(str(self._path))
        self._stack.setCurrentWidget(self._input_page)
        self._edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._edit.selectAll()

    def _cancel_edit(self) -> None:
        if self._path is not None:
            self._edit.setText(str(self._path))
        self._stack.setCurrentWidget(self._page)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._edit:
            if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
                if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape}:
                    event.accept()
                    return True
            if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key.Key_Escape:
                    self._cancel_edit()
                    return True
                if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self._submitting = True
                    try:
                        value = self._edit.text().strip()
                        if not value:
                            QMessageBox.warning(self._dialog, tr("ExportDialog", "フォルダ選択エラー"),
                                                tr("ExportDialog", "パスを入力してください。"))
                        elif self._navigate(Path(value)):
                            self._stack.setCurrentWidget(self._page)
                    finally:
                        self._submitting = False
                    if self._stack.currentWidget() is self._input_page:
                        self._edit.setFocus()
                    return True
            if event.type() == QEvent.Type.FocusOut and not self._submitting:
                self._cancel_edit()
        if watched is self._stack and event.type() == QEvent.Type.Resize and not self._resize_pending:
            self._resize_pending = True
            QTimer.singleShot(0, self._fit_buttons)
        return super().eventFilter(watched, event)

    def _fit_buttons(self) -> None:
        self._resize_pending = False
        if not self._buttons:
            return
        widths: list[int] = []
        for path, name, arrow in self._buttons:
            name.setText(path.name or str(path))
            name.setFixedWidth(name.sizeHint().width())
            widths.append(name.width() + arrow.sizeHint().width())
        available = max(0, self._stack.contentsRect().width() - self._blank.minimumWidth())
        first = 0
        total = sum(widths)
        if total > available and len(widths) > 1:
            available = max(0, available - self._ancestors.sizeHint().width())
            while total > available and first < len(widths) - 1:
                total -= widths[first]
                first += 1
        self._hidden = [path for path, _, _ in self._buttons[:first]]
        self._ancestors.setVisible(bool(self._hidden))
        for index, (_, name, arrow) in enumerate(self._buttons):
            name.setVisible(index >= first)
            arrow.setVisible(index >= first)
        _, current, arrow = self._buttons[-1]
        if total > available:
            width = max(1, available - arrow.sizeHint().width())
            padding = max(0, current.sizeHint().width() - current.fontMetrics().horizontalAdvance(current.text()))
            current.setText(current.fontMetrics().elidedText(current.text(), Qt.TextElideMode.ElideMiddle,
                                                            max(1, width - padding)))
            current.setFixedWidth(width)

    def _show_ancestors(self) -> None:
        menu = QMenu(self._ancestors)
        for path in self._hidden:
            action = menu.addAction(path.name or str(path))
            action.setToolTip(str(path))
            action.triggered.connect(lambda checked=False, target=path: self._navigate(target))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self._ancestors.mapToGlobal(self._ancestors.rect().bottomLeft()))

    def _show_children(self, path: Path, button: QToolButton) -> None:
        menu = QMenu(button)
        index = self._model.index(str(path))
        if not index.isValid() or not self._model.isDir(index):
            self._menu_message(menu, tr("ExportDialog", "子フォルダを取得できません。"))
        elif path in self._loaded:
            self._populate_children(path, menu)
        else:
            if self._model.rowCount(index) > 0:
                self._populate_children(path, menu)
            else:
                self._menu_message(menu, tr("ExportDialog", "読み込み中…"))
            self._pending_menu = (path, menu)
            timer = QTimer(menu)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._children_timeout(menu))
            timer.start(5000)
            if self._model.canFetchMore(index):
                self._model.fetchMore(index)
        menu.aboutToHide.connect(lambda: self._close_children_menu(menu))
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))

    def _menu_message(self, menu: QMenu, message: str) -> None:
        menu.clear()
        menu.addAction(message).setEnabled(False)

    def _populate_children(self, path: Path, menu: QMenu) -> None:
        index = self._model.index(str(path))
        if not index.isValid() or not self._model.isDir(index):
            self._menu_message(menu, tr("ExportDialog", "子フォルダを取得できません。"))
            return
        children: list[tuple[str, Path]] = []
        for row in range(self._model.rowCount(index)):
            child = self._model.index(row, 0, index)
            if self._model.isDir(child):
                children.append((self._model.fileName(child), Path(self._model.filePath(child))))
        menu.clear()
        for name, target in sorted(children, key=lambda item: item[0].casefold()):
            action = menu.addAction(name)
            action.triggered.connect(lambda checked=False, path=target: self._navigate(path))
        if not children:
            self._menu_message(menu, tr("ExportDialog", "子フォルダがありません。"))

    def _directory_loaded(self, directory: str) -> None:
        path = Path(directory)
        self._loaded.add(path)
        if self._pending_menu is not None and self._pending_menu[0] == path:
            _, menu = self._pending_menu
            self._pending_menu = None
            self._populate_children(path, menu)

    def _children_inserted(self, parent: QModelIndex, _first: int, _last: int) -> None:
        if self._pending_menu is None:
            return
        path, menu = self._pending_menu
        if parent.isValid() and Path(self._model.filePath(parent)) == path:
            self._populate_children(path, menu)

    def _children_timeout(self, menu: QMenu) -> None:
        if self._pending_menu is not None and self._pending_menu[1] is menu:
            path, _ = self._pending_menu
            self._pending_menu = None
            index = self._model.index(str(path))
            if index.isValid() and self._model.rowCount(index) > 0:
                self._populate_children(path, menu)
            else:
                self._menu_message(menu, tr("ExportDialog", "子フォルダを取得できません。"))

    def _close_children_menu(self, menu: QMenu) -> None:
        if self._pending_menu is not None and self._pending_menu[1] is menu:
            self._pending_menu = None
        menu.deleteLater()


class OutputMode(Enum):
    FOLDER = "folder"
    FILE = "file"


class ExportDestinationDialog(SimpleDialogController):
    """Reusable destination browser; subclasses supply format settings."""

    def __init__(self, directory: Path, parent: QWidget, *,
                 mode: OutputMode = OutputMode.FOLDER, filename: str = "") -> None:
        super().__init__("dialogs/ExportDialog.ui", parent)
        self._output_mode = mode
        self.filename = require_child(self.dialog, QLineEdit, "editFilename")
        self.filename.setText(filename)
        require_child(self.dialog, QWidget, "filenameRow").setVisible(mode is OutputMode.FILE)
        self._destination = require_child(self.dialog, QLineEdit, "editDestination")
        output_layout = require_child(self.dialog, QFormLayout, "layoutOutput")
        output_layout.setRowVisible(self._destination, mode is OutputMode.FOLDER)
        output_layout.setRowVisible(1, mode is OutputMode.FOLDER)
        self._navigation = require_child(self.dialog, QTreeView, "treeNavigation")
        self._folders = require_child(self.dialog, QTreeView, "treeFolders")
        self._back = require_child(self.dialog, QPushButton, "buttonBack")
        self._forward = require_child(self.dialog, QPushButton, "buttonForward")
        self._up = require_child(self.dialog, QPushButton, "buttonUp")
        self._model = QFileSystemModel(self.dialog)
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self._model.setReadOnly(True)
        # Keep the navigation tree folder-only while the file view shows outputs.
        self._navigation_model = self._model
        if mode is OutputMode.FILE:
            self._navigation_model = QFileSystemModel(self.dialog)
            self._navigation_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
            self._navigation_model.setReadOnly(True)
            self._navigation_model.setRootPath("")
            self._model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        for view in (self._navigation, self._folders):
            view.setModel(self._model)
        self._navigation.setModel(self._navigation_model)
        for column in range(1, self._model.columnCount()):
            self._navigation.hideColumn(column)
        self._folders.hideColumn(1)
        self._folders.hideColumn(2)
        self._folders.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._folders.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        require_child(self.dialog, QSplitter, "splitterFolders").setSizes([200, 600])
        self._history: list[Path] = []
        self._history_index = -1
        self._current = directory.resolve()
        self._address_bar = _AddressBar(self.dialog, self._model, self._navigate)
        self._model.setRootPath("")
        self._back.clicked.connect(lambda: self._move_history(-1))
        self._forward.clicked.connect(lambda: self._move_history(1))
        self._up.clicked.connect(lambda: self._navigate(self._current.parent))
        self._navigation.clicked.connect(lambda index: self._navigate(
            Path(self._navigation_model.filePath(index))) if index.isValid() else None)
        self._folders.doubleClicked.connect(self._open_index)
        self._folders.clicked.connect(self._select_index)
        require_child(self.dialog, QPushButton, "buttonNewFolder").clicked.connect(self._new_folder)
        require_child(self.dialog, QPushButton, "buttonExport").clicked.connect(self.accept)
        require_child(self.dialog, QWidget, "sectionTranslationStates").hide()
        self._navigate(self._current)

    def accept(self) -> None:
        try:
            destination = self.output_path()
            if not self.confirm_overwrite(destination):
                return
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.dialog, tr("ExportDialog", "出力エラー"), str(exc))
            return
        self.destination = destination
        self.dialog.accept()

    def output_path(self, *, suffix: str = "", replace_suffixes: tuple[str, ...] = ()) -> Path:
        """Validate the destination and normalize a file extension without writing."""
        directory = self.output_directory()
        if self._output_mode is OutputMode.FOLDER:
            return directory
        name = self.filename.text().strip()
        if (not name or name in {".", ".."} or any(c in name for c in '/\\:*?"<>|')
                or name.endswith((".", " "))):
            raise ValueError(tr("ExportDialog", "ファイル名が不正です。"))
        if suffix:
            if Path(name).suffix.lower() in {suffix.lower(), *replace_suffixes}:
                name = str(Path(name).with_suffix(""))
            name += suffix
        destination = directory / name
        if destination.is_dir():
            raise ValueError(tr("ExportDialog", "同名のフォルダがあります。"))
        return destination

    def confirm_overwrite(self, destination: Path) -> bool:
        if self._output_mode is OutputMode.FOLDER or not destination.exists():
            return True
        return QMessageBox.question(
            self.dialog, tr("ExportDialog", "上書き確認"),
            tr("ExportDialog", "{name} を上書きしますか？").format(name=destination.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def output_directory(self) -> Path:
        value = self._destination.text().strip()
        destination = Path(value).expanduser()
        if not destination.is_absolute():
            destination = self._current / destination
        if not value or not destination.is_dir():
            raise ValueError(tr("ExportDialog", "出力先フォルダを選択してください。"))
        return destination.resolve()

    def _navigate(self, path: Path, *, record_history: bool = True) -> bool:
        try:
            path = path.expanduser()
            if not path.is_absolute():
                path = self._current / path
            path = Path(QDir.fromNativeSeparators(str(path.resolve())))
            if not path.is_dir():
                raise ValueError(tr("ExportDialog", "フォルダがありません。"))
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self.dialog, tr("ExportDialog", "フォルダ選択エラー"), str(exc))
            return False
        if record_history and (self._history_index < 0 or self._history[self._history_index] != path):
            self._history = self._history[:self._history_index + 1]
            self._history.append(path)
            self._history_index = len(self._history) - 1
        self._current = path
        self._folders.setRootIndex(self._model.index(str(path)))
        self._address_bar.set_path(path)
        self._destination.setText(str(path))
        self._back.setEnabled(self._history_index > 0)
        self._forward.setEnabled(self._history_index + 1 < len(self._history))
        self._up.setEnabled(path.parent != path)
        return True

    def _move_history(self, offset: int) -> None:
        index = self._history_index + offset
        if 0 <= index < len(self._history):
            if not self._history[index].is_dir():
                self._navigate(self._history[index], record_history=False)
                return
            self._history_index = index
            self._navigate(self._history[index], record_history=False)

    def _open_index(self, index: QModelIndex) -> None:
        if index.isValid():
            if self._model.isDir(index):
                self._navigate(Path(self._model.filePath(index)))
            else:
                self._select_index(index)

    def _select_index(self, index: QModelIndex) -> None:
        if index.isValid():
            if self._output_mode is OutputMode.FILE:
                if not self._model.isDir(index):
                    self.filename.setText(self._model.fileName(index))
            else:
                self._destination.setText(self._model.filePath(index))

    def _new_folder(self) -> None:
        name, accepted = QInputDialog.getText(self.dialog, tr("ExportDialog", "新しいフォルダ"),
                                             tr("ExportDialog", "フォルダ名："))
        if not accepted:
            return
        if not name.strip() or name in {".", ".."} or any(char in name for char in '/\\:'):
            QMessageBox.warning(self.dialog, tr("ExportDialog", "フォルダ作成エラー"),
                                tr("ExportDialog", "フォルダ名が不正です。"))
            return
        try:
            path = self._current / name
            path.mkdir()
        except OSError as exc:
            QMessageBox.warning(self.dialog, tr("ExportDialog", "フォルダ作成エラー"), str(exc))
            return
        self._navigate(path)
