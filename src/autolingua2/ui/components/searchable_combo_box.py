from __future__ import annotations

from PySide6.QtCore import (
    QCoreApplication, QEvent, QModelIndex, QObject, QPoint, QRectF,
    QSortFilterProxyModel, Qt, Signal,
)
from PySide6.QtGui import QInputMethodEvent, QInputMethodQueryEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QFrame, QLabel, QLineEdit, QListView, QPushButton,
    QVBoxLayout, QWidget,
)


def _search_editor(combo: QComboBox) -> QLineEdit:
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    editor = combo.lineEdit()
    if editor is None:
        raise RuntimeError("Editable combo box has no line editor")
    return editor


def enable_combo_search(combo: QComboBox) -> None:
    """Use an existing combo's editor to search without adding new items."""
    editor = _search_editor(combo)

    completer = QCompleter(combo.model(), combo)
    completer.setCompletionColumn(combo.modelColumn())
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)

    def search(text: str) -> None:
        completer.setCompletionPrefix(text)
        completer.complete()

    def restore_selection() -> None:
        # Search text is temporary; only an existing item can be selected.
        combo.setEditText(combo.itemText(combo.currentIndex()))

    editor.textEdited.connect(search)
    editor.editingFinished.connect(restore_selection)


class SearchableActionComboBox(QComboBox):
    """Search one source model, keeping an action above the scrolling results."""

    actionRequested = Signal()

    def __init__(self, action_text: str, empty_text: str, parent: QWidget,
                 *, search_role: int = Qt.ItemDataRole.DisplayRole.value) -> None:
        super().__init__(parent)
        self.editor = _search_editor(self)
        # Keep the native editor's completer empty; all results use our popup.
        self.setCompleter(QCompleter([], self))
        self._searching = False
        self._composing = False
        self._popup = QFrame(self, Qt.WindowType.Popup)
        self._popup.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self._popup.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self._popup)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._action = QPushButton(action_text, self._popup)
        self._action.setAutoDefault(False)
        layout.addWidget(self._action)
        separator = QFrame(self._popup)
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        self._results = QListView(self._popup)
        self._results.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self._results.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self.model())
        self._proxy.setFilterRole(search_role)
        self._proxy.setFilterKeyColumn(self.modelColumn())
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._results.setModel(self._proxy)
        layout.addWidget(self._results)
        self._empty = QLabel(empty_text, self._popup)
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._empty)
        for watched in (self.editor, self._popup, self._results, self._action):
            watched.installEventFilter(self)
        self.editor.textEdited.connect(self._search)
        self.editor.editingFinished.connect(self._editing_finished)
        self._results.clicked.connect(self._select_result)
        self._action.clicked.connect(self._request_action)

    def showPopup(self) -> None:
        if not self._searching:
            self._proxy.setFilterFixedString("")
        self._show_results(reset_selection=not self._popup.isVisible())

    def hidePopup(self) -> None:
        self._popup.hide()
        super().hidePopup()
        self._restore_selection()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # The native combo suppresses its popup when there are no items.
        # Creation must remain available even for an empty collection.
        if event.button() == Qt.MouseButton.LeftButton:
            if self._popup.isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            event.accept()
        else:
            super().mousePressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._handle_key(event):
            super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._popup and event.type() == QEvent.Type.Hide:
            self._restore_selection()
            super().hidePopup()
        if watched in (self._popup, self._results):
            if isinstance(event, QInputMethodEvent):
                self._composing = bool(event.preeditString())
                QCoreApplication.sendEvent(self.editor, event)
                return True
            if isinstance(event, QInputMethodQueryEvent) and isinstance(watched, QWidget):
                QCoreApplication.sendEvent(self.editor, event)
                offset = self.editor.mapToGlobal(QPoint()) - watched.mapToGlobal(QPoint())
                for query in (Qt.InputMethodQuery.ImCursorRectangle, Qt.InputMethodQuery.ImAnchorRectangle):
                    value = event.value(query)
                    if isinstance(value, QRectF):
                        event.setValue(query, value.translated(offset.x(), offset.y()))
                return True
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if watched is self._action and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._request_action()
                return True
            if self._handle_key(event):
                return True
            if watched in (self._popup, self._results, self._action) and event.key() not in (
                Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
            ) and not (watched is self._action and event.key() == Qt.Key.Key_Space):
                QCoreApplication.sendEvent(self.editor, event)
                return True
        return super().eventFilter(watched, event)

    def _handle_key(self, event: QKeyEvent) -> bool:
        if self._composing:
            return False
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_F4):
            visible = self._popup.isVisible()
            self.showPopup()
            if visible and key != Qt.Key.Key_F4:
                row = self._results.currentIndex().row() + (1 if key == Qt.Key.Key_Down else -1)
                row = max(0, min(self._proxy.rowCount() - 1, row))
                index = self._proxy.index(row, self.modelColumn())
                self._results.setCurrentIndex(index)
                self._results.scrollTo(index)
            return True
        if key == Qt.Key.Key_Escape and (self._popup.isVisible() or self._searching):
            self.hidePopup()
            self.editor.setFocus()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._popup.isVisible():
                self._select_result(self._results.currentIndex())
            else:
                self._restore_selection()
            return True
        return False

    def _search(self, text: str) -> None:
        self.editor.setModified(False)
        self._searching = True
        self._proxy.setFilterFixedString(text)
        self._show_results(reset_selection=True)

    def _show_results(self, *, reset_selection: bool) -> None:
        count = self._proxy.rowCount()
        self._empty.setVisible(count == 0)
        self._results.setVisible(count > 0)
        row_height = self.fontMetrics().height() + 12
        self._results.setFixedHeight(min(8, max(1, count)) * row_height + 4)
        current = self._results.currentIndex()
        if reset_selection or not current.isValid():
            selected = self._proxy.mapFromSource(self.model().index(self.currentIndex(), self.modelColumn()))
            current = (selected if not self._searching and selected.isValid()
                       else self._proxy.index(0, self.modelColumn()))
            self._results.setCurrentIndex(current)
        screen = self.screen().availableGeometry()
        width = min(screen.width(), max(self.width(), self._action.sizeHint().width() + 16))
        height = min(screen.height(), self._popup.sizeHint().height())
        position = self.mapToGlobal(self.rect().bottomLeft())
        x = max(screen.left(), min(position.x(), screen.right() - width + 1))
        y = position.y() + 1
        if y + height > screen.bottom() + 1:
            y = self.mapToGlobal(self.rect().topLeft()).y() - height
        y = max(screen.top(), y)
        self._popup.setGeometry(x, y, width, height)
        if not self._popup.isVisible():
            if not self._searching:
                self.editor.selectAll()
            self._popup.show()
            self._results.setFocus() if count else self._popup.setFocus()

    def _select_result(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        source = self._proxy.mapToSource(index)
        if not source.isValid():
            return
        row = source.row()
        self.hidePopup()
        self.setCurrentIndex(row)
        self.setEditText(self.itemText(row))
        self.activated.emit(row)
        self.editor.setFocus()

    def _request_action(self) -> None:
        self.hidePopup()
        self.actionRequested.emit()

    def _editing_finished(self) -> None:
        if not self._popup.isVisible():
            self._restore_selection()

    def _restore_selection(self) -> None:
        self._searching = False
        self._composing = False
        self.setEditText(self.itemText(self.currentIndex()))
