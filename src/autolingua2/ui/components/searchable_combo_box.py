from __future__ import annotations

from typing import Callable

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


class SearchComboController(QObject):
    """Search one source model, optionally displaying an action button above scrolling results."""

    actionRequested = Signal()

    def __init__(self, combo: QComboBox, *,
                 action_text: str = "", empty_text: str = "",
                 search_role: int = Qt.ItemDataRole.DisplayRole.value,
                 on_action: Callable[[], None] | None = None) -> None:
        super().__init__(combo)
        self.combo = combo
        self.editor = _search_editor(combo)
        # Keep the native editor's completer empty; all results use our popup.
        combo.setCompleter(QCompleter([], combo))
        self._searching = False
        self._composing = False
        self._popup = QFrame(combo, Qt.WindowType.Popup)
        self._popup.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self._popup.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self._popup)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._action = QPushButton(action_text, self._popup)
        self._action.setAutoDefault(False)
        self._separator = QFrame(self._popup)
        self._separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(self._action)
        layout.addWidget(self._separator)
        if not action_text:
            self._action.hide()
            self._separator.hide()

        self._results = QListView(self._popup)
        self._results.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self._results.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(combo.model())
        self._proxy.setFilterRole(search_role)
        self._proxy.setFilterKeyColumn(combo.modelColumn())
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._results.setModel(self._proxy)
        layout.addWidget(self._results)

        self._empty = QLabel(empty_text, self._popup)
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._empty)
        if not empty_text:
            self._empty.hide()

        for watched in (combo, self.editor, self._popup, self._results, self._action):
            watched.installEventFilter(self)

        self.editor.textEdited.connect(self._search)
        self.editor.editingFinished.connect(self._editing_finished)
        self._results.clicked.connect(self._select_result)
        self._action.clicked.connect(self._request_action)
        if on_action is not None:
            self.actionRequested.connect(on_action)

    def set_action_text(self, text: str) -> None:
        self._action.setText(text)
        self._action.setVisible(bool(text))
        self._separator.setVisible(bool(text))

    def show_popup(self) -> None:
        if not self._searching:
            self._proxy.setFilterFixedString("")
        self._show_results(reset_selection=not self._popup.isVisible())

    def hide_popup(self) -> None:
        self._popup.hide()
        self._restore_selection()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.combo:
            if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    if self._popup.isVisible():
                        self.hide_popup()
                    else:
                        self.show_popup()
                    return True
            elif event.type() == QEvent.Type.Wheel:
                return True
            elif event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if self._handle_key(event):
                    return True
        elif watched is self._popup and event.type() == QEvent.Type.Hide:
            self._restore_selection()
        elif watched in (self._popup, self._results):
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
        elif isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
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
            self.show_popup()
            if visible and key != Qt.Key.Key_F4:
                row = self._results.currentIndex().row() + (1 if key == Qt.Key.Key_Down else -1)
                row = max(0, min(self._proxy.rowCount() - 1, row))
                index = self._proxy.index(row, self.combo.modelColumn())
                self._results.setCurrentIndex(index)
                self._results.scrollTo(index)
            return True
        if key == Qt.Key.Key_Escape and (self._popup.isVisible() or self._searching):
            self.hide_popup()
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
        self._empty.setVisible(count == 0 and bool(self._empty.text()))
        self._results.setVisible(count > 0)
        row_height = self.combo.fontMetrics().height() + 12
        self._results.setFixedHeight(min(8, max(1, count)) * row_height + 4)
        current = self._results.currentIndex()
        if reset_selection or not current.isValid():
            selected = self._proxy.mapFromSource(self.combo.model().index(self.combo.currentIndex(), self.combo.modelColumn()))
            current = (selected if not self._searching and selected.isValid()
                       else self._proxy.index(0, self.combo.modelColumn()))
            self._results.setCurrentIndex(current)
        screen = self.combo.screen().availableGeometry()
        action_width = self._action.sizeHint().width() + 16 if self._action.isVisible() else 0
        width = min(screen.width(), max(self.combo.width(), action_width))
        height = min(screen.height(), self._popup.sizeHint().height())
        position = self.combo.mapToGlobal(self.combo.rect().bottomLeft())
        x = max(screen.left(), min(position.x(), screen.right() - width + 1))
        y = position.y() + 1
        if y + height > screen.bottom() + 1:
            y = self.combo.mapToGlobal(self.combo.rect().topLeft()).y() - height
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
        self.hide_popup()
        self.combo.setCurrentIndex(row)
        self.combo.setEditText(self.combo.itemText(row))
        self.combo.activated.emit(row)
        self.editor.setFocus()

    def _request_action(self) -> None:
        self.hide_popup()
        self.actionRequested.emit()

    def _editing_finished(self) -> None:
        if not self._popup.isVisible():
            self._restore_selection()

    def _restore_selection(self) -> None:
        self._searching = False
        self._composing = False
        self.combo.setEditText(self.combo.itemText(self.combo.currentIndex()))


def enable_combo_search(
    combo: QComboBox,
    *,
    action_text: str = "",
    empty_text: str = "",
    search_role: int = Qt.ItemDataRole.DisplayRole.value,
    on_action: Callable[[], None] | None = None,
) -> SearchComboController:
    """Enable searchable popup on an existing combo, optionally with an action button."""
    controller = SearchComboController(
        combo,
        action_text=action_text,
        empty_text=empty_text,
        search_role=search_role,
        on_action=on_action,
    )
    combo._search_controller = controller  # type: ignore[attr-defined]
    return controller


class SearchableActionComboBox(QComboBox):
    """Search one source model, keeping an action above the scrolling results."""

    actionRequested = Signal()

    def __init__(self, action_text: str, empty_text: str, parent: QWidget,
                 *, search_role: int = Qt.ItemDataRole.DisplayRole.value) -> None:
        super().__init__(parent)
        self.controller = enable_combo_search(
            self,
            action_text=action_text,
            empty_text=empty_text,
            search_role=search_role,
            on_action=self.actionRequested.emit,
        )

    @property
    def editor(self) -> QLineEdit:
        return self.controller.editor

    def showPopup(self) -> None:
        self.controller.show_popup()

    def hidePopup(self) -> None:
        self.controller.hide_popup()
