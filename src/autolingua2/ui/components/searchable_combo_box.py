from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QPoint, QSize, QSortFilterProxyModel, Qt
from PySide6.QtGui import QFontMetrics, QInputMethodEvent, QKeyEvent, QMouseEvent, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCompleter, QFrame, QGraphicsDropShadowEffect, QLabel, QLineEdit, QListView, QPushButton,
    QStyle, QStyledItemDelegate, QStyleOption, QStyleOptionViewItem, QStylePainter, QVBoxLayout, QWidget,
)

from autolingua2.ui.i18n import tr


@dataclass(frozen=True, slots=True)
class ComboAction:
    """An optional fixed action; callers must explicitly choose its position."""

    text: str
    callback: Callable[[], None]
    position: Literal["top", "bottom"]

    def __post_init__(self) -> None:
        if self.position not in ("top", "bottom"):
            raise ValueError("Combo action position must be 'top' or 'bottom'")


class _CandidateDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        metrics = option.fontMetrics
        if not isinstance(metrics, QFontMetrics):
            raise TypeError("Candidate font metrics must be QFontMetrics")
        size.setHeight(max(size.height(), metrics.height() + 14))
        return size


class _SearchPopup(QFrame):
    def paintEvent(self, event: QPaintEvent | None) -> None:
        # Explicitly paint the rounded QSS background inside the shadow host.
        option = QStyleOption()
        option.initFrom(self)
        painter = QStylePainter(self)
        painter.drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option)


class SearchComboController(QObject):
    """Share inline search and selection between Designer and Python combos."""

    MAX_VISIBLE_ROWS = 10
    SHADOW_MARGIN = 54
    SHADOW_OFFSET_Y = 8

    def __init__(self, combo: QComboBox, *, action: ComboAction | None = None,
                 empty_text: str | None = None,
                 search_role: int = Qt.ItemDataRole.DisplayRole.value) -> None:
        super().__init__(combo)
        self.combo = combo
        self._action = action
        self._searching = False
        self._composing = False
        self._action_active = False
        self._candidate_count = -1
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Suppress QComboBox's independent inline completion; only our proxy
        # supplies candidates. PySide's setCompleter contract requires an object.
        combo.setCompleter(QCompleter([], combo))
        editor = combo.lineEdit()
        if editor is None:
            raise RuntimeError("Editable combo box has no line editor")
        self.editor = editor

        # Leave keyboard/IME ownership with the actual editor. A non-activating
        # Qt tool window needs no synthetic key or input-method event forwarding.
        window_flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                        | Qt.WindowType.WindowDoesNotAcceptFocus)
        # A separate output-only window keeps the shadow outside the input area.
        self._shadow_window = QWidget(combo, window_flags | Qt.WindowType.WindowTransparentForInput)
        self._shadow_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._shadow_window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._shadow_window.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        shadow_layout = QVBoxLayout(self._shadow_window)
        shadow_layout.setContentsMargins(
            self.SHADOW_MARGIN, self.SHADOW_MARGIN,
            self.SHADOW_MARGIN, self.SHADOW_MARGIN + self.SHADOW_OFFSET_Y,
        )
        self._popup = _SearchPopup(self._shadow_window, window_flags)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        frame = self._popup
        shadow_frame = _SearchPopup(self._shadow_window)
        popup_style = (
            "QFrame#searchComboPopup { background-color: palette(window); "
            "border: 1px solid palette(midlight); border-radius: 8px; }"
        )
        for surface in (frame, shadow_frame):
            surface.setObjectName("searchComboPopup")
            surface.setStyleSheet(popup_style)
        shadow = QGraphicsDropShadowEffect(shadow_frame)
        shadow.setBlurRadius(90)
        shadow.setOffset(0, self.SHADOW_OFFSET_Y)
        shadow_color = combo.palette().color(QPalette.ColorRole.Shadow)
        shadow_color.setAlpha(200)
        shadow.setColor(shadow_color)
        shadow_frame.setGraphicsEffect(shadow)
        shadow_layout.addWidget(shadow_frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        self._layout = layout
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(combo.model())
        self.proxy.setFilterRole(search_role)
        self.proxy.setFilterKeyColumn(combo.modelColumn())
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._results = QListView(frame)
        self._results.setStyleSheet("QListView { background-color: transparent; border: none; }")
        self._results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._results.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._results.setMouseTracking(True)
        self._results.setUniformItemSizes(True)
        self._results.setModel(self.proxy)
        self._results.setModelColumn(combo.modelColumn())
        self._results.setItemDelegate(_CandidateDelegate(self))
        self._empty = QLabel(
            empty_text if empty_text is not None else tr("SearchableComboBox", "該当する項目がありません。"),
            frame,
        )
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._results)
        layout.addWidget(self._empty)
        self._button: QPushButton | None = None
        if action is not None:
            self._button = QPushButton(action.text, frame)
            self._button.setAutoDefault(False)
            self._button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._button.clicked.connect(self._request_action)
            separator = QFrame(frame)
            separator.setFrameShape(QFrame.Shape.HLine)
            if action.position == "top":
                layout.insertWidget(0, self._button)
                layout.insertWidget(1, separator)
            else:
                layout.addWidget(separator)
                layout.addWidget(self._button)

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("Searchable combos require QApplication")
        app.installEventFilter(self)
        self.editor.textEdited.connect(self._search)
        self._results.clicked.connect(self._select_result)
        combo.currentIndexChanged.connect(self._selection_changed)
        for signal in (self.proxy.rowsInserted, self.proxy.rowsRemoved,
                       self.proxy.modelReset, self.proxy.dataChanged):
            signal.connect(self._model_changed)

    def _toggle_popup(self) -> None:
        if self._popup.isVisible():
            self.hide_popup()
        else:
            self.show_popup()

    def show_popup(self) -> None:
        if not self.combo.isEnabled():
            return
        opening = not self._popup.isVisible()
        if not self._searching:
            self.proxy.setFilterFixedString("")
        self._refresh_results(reset_selection=opening)
        if opening:
            self._shadow_window.show()
            self._popup.show()
            self.editor.setFocus(Qt.FocusReason.PopupFocusReason)
            if not self._searching:
                self.editor.selectAll()

    def hide_popup(self) -> None:
        self._popup.hide()
        self._shadow_window.hide()
        self._searching = False
        self._composing = False
        self._set_action_active(False)
        self.combo.setEditText(self.combo.itemText(self.combo.currentIndex()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        visible = self._popup.isVisible()
        if visible:
            if kind == QEvent.Type.ApplicationDeactivate:
                self.hide_popup()
            elif kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                point = event.globalPosition().toPoint()
                combo_rect = self.combo.rect().translated(self.combo.mapToGlobal(QPoint()))
                if not combo_rect.contains(point) and not self._popup.geometry().contains(point):
                    self.hide_popup()
            elif kind in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide,
                          QEvent.Type.Close, QEvent.Type.EnabledChange) and isinstance(watched, QWidget):
                if watched is self.combo or watched.isAncestorOf(self.combo):
                    self.hide_popup()
        if watched is self.editor:
            if isinstance(event, QInputMethodEvent):
                self._composing = bool(event.preeditString())
            elif kind == QEvent.Type.FocusOut and (visible or self._searching):
                self.hide_popup()
            elif kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton and not visible:
                    self.show_popup()
                    # Preserve selectAll on first click. Later clicks use normal
                    # QLineEdit cursor positioning and text selection.
                    return True
        if watched in (self.combo, self.editor):
            if kind == QEvent.Type.Wheel:
                return True
            if kind == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                return self._handle_key(event)
            if watched is self.combo and kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_popup()
                    return True
        return super().eventFilter(watched, event)

    def _handle_key(self, event: QKeyEvent) -> bool:
        if self._composing:
            return False
        key = event.key()
        visible = self._popup.isVisible()
        if key == Qt.Key.Key_F4:
            self._toggle_popup()
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self._toggle_popup()
                return True
            self.show_popup()
            self._set_action_active(False)
            if visible:
                indexes = self._selectable_indexes()
                current = self._results.currentIndex()
                row = next((i for i, index in enumerate(indexes) if index == current), -1)
                if indexes:
                    row = max(0, min(len(indexes) - 1, row + (1 if key == Qt.Key.Key_Down else -1)))
                    self._results.setCurrentIndex(indexes[row])
                    self._results.scrollTo(indexes[row])
            return True
        if key == Qt.Key.Key_Escape and (visible or self._searching):
            self.hide_popup()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if visible:
                if self._action_active:
                    self._request_action()
                else:
                    self._select_result(self._results.currentIndex())
                return True
            return False
        if visible and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if key == Qt.Key.Key_Backtab and self._action_active:
                self._set_action_active(False)
                return True
            if key == Qt.Key.Key_Tab and self._button is not None and not self._action_active:
                self._set_action_active(True)
                return True
            self.hide_popup()
        return False

    def _set_action_active(self, active: bool) -> None:
        self._action_active = active
        if self._button is not None:
            self._button.setDown(active)

    def _selectable_indexes(self) -> list[QModelIndex]:
        return [index for row in range(self.proxy.rowCount())
                if (index := self.proxy.index(row, self.combo.modelColumn())).flags()
                & Qt.ItemFlag.ItemIsEnabled and index.flags() & Qt.ItemFlag.ItemIsSelectable]

    def _search(self, text: str) -> None:
        # QComboBox must not commit an exact text match on editingFinished.
        # Selection is committed only by _select_result, including on focus loss.
        self.editor.setModified(False)
        self._searching = True
        self._set_action_active(False)
        self.proxy.setFilterFixedString(text)
        self.show_popup()
        self._refresh_results(reset_selection=True)

    def _model_changed(self, *_args: object) -> None:
        if self._popup.isVisible():
            self._refresh_results(reset_selection=False)

    def _selection_changed(self, *_args: object) -> None:
        if self._popup.isVisible():
            self._refresh_results(reset_selection=True)

    def _refresh_results(self, *, reset_selection: bool) -> None:
        count = self.proxy.rowCount()
        if count != self._candidate_count:
            self._resize_for_count(count)
        if reset_selection or not self._results.currentIndex().isValid():
            indexes = self._selectable_indexes()
            selected = self.proxy.mapFromSource(self.combo.model().index(
                self.combo.currentIndex(), self.combo.modelColumn()))
            current = selected if not self._searching and selected in indexes else next(iter(indexes), QModelIndex())
            self._results.setCurrentIndex(current)
            if current.isValid():
                self._results.scrollTo(current)
        screen = self.combo.screen().availableGeometry()
        width = min(screen.width(), max(self.combo.width(), self._popup.sizeHint().width()))
        height = self._popup.height()
        position = self.combo.mapToGlobal(self.combo.rect().bottomLeft())
        x = max(screen.left(), min(position.x(), screen.right() - width + 1))
        y = position.y() + 4
        if y + height > screen.bottom() + 1:
            y = self.combo.mapToGlobal(QPoint()).y() - height - 3
        self._popup.setGeometry(x, max(screen.top(), y), width, height)
        self._shadow_window.setGeometry(self._popup.geometry().adjusted(
            -self.SHADOW_MARGIN, -self.SHADOW_MARGIN,
            self.SHADOW_MARGIN, self.SHADOW_MARGIN + self.SHADOW_OFFSET_Y,
        ))

    def _resize_for_count(self, count: int) -> None:
        self._candidate_count = count
        self._results.setVisible(count > 0)
        self._empty.setVisible(count == 0)
        if count > 0:
            self._results.ensurePolished()
            self._results.doItemsLayout()
            row_height = self._results.sizeHintForRow(0)
            if row_height <= 0:
                raise RuntimeError("Candidate row height must be positive")
            self._results.setFixedHeight(min(self.MAX_VISIBLE_ROWS, count) * row_height)
        # Activate the updated layout before measuring the frame: its previous
        # minimum size must not preserve empty space after filtering.
        self._layout.invalidate()
        self._layout.activate()
        screen_height = self.combo.screen().availableGeometry().height()
        height = self._layout.totalSizeHint().height()
        if count > 0 and height > screen_height:
            self._results.setFixedHeight(max(1, self._results.height() - (height - screen_height)))
            self._layout.invalidate()
            self._layout.activate()
            height = self._layout.totalSizeHint().height()
        self._popup.setFixedHeight(min(screen_height, height))

    def _select_result(self, index: QModelIndex) -> None:
        if not index.isValid() or not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        if not index.flags() & Qt.ItemFlag.ItemIsSelectable:
            return
        source = self.proxy.mapToSource(index)
        if not source.isValid():
            return
        row = source.row()
        self.hide_popup()
        self.combo.setCurrentIndex(row)
        self.combo.setEditText(self.combo.itemText(row))
        self.combo.activated.emit(row)
        self.combo.textActivated.emit(self.combo.itemText(row))
        self.editor.setFocus()

    def _request_action(self) -> None:
        self.hide_popup()
        if self._action is not None:
            self._action.callback()


def enable_combo_search(
    combo: QComboBox, *, action: ComboAction | None = None,
    empty_text: str | None = None,
    search_role: int = Qt.ItemDataRole.DisplayRole.value,
) -> SearchComboController:
    """Attach the shared component to a Designer-created QComboBox."""
    if combo.findChild(SearchComboController, options=Qt.FindChildOption.FindDirectChildrenOnly) is not None:
        raise ValueError("Search is already enabled on this combo box")
    return SearchComboController(combo, action=action, empty_text=empty_text, search_role=search_role)


class SearchableComboBox(QComboBox):
    """A QComboBox with inline search and an optional explicitly placed action."""

    def __init__(self, parent: QWidget | None = None, *, action: ComboAction | None = None,
                 empty_text: str | None = None,
                 search_role: int = Qt.ItemDataRole.DisplayRole.value) -> None:
        super().__init__(parent)
        self.controller = enable_combo_search(self, action=action, empty_text=empty_text, search_role=search_role)

    @property
    def editor(self) -> QLineEdit:
        return self.controller.editor

    def showPopup(self) -> None:
        self.controller.show_popup()

    def hidePopup(self) -> None:
        self.controller.hide_popup()
