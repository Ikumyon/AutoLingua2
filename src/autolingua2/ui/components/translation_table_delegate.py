from __future__ import annotations

from typing import TYPE_CHECKING, Callable
from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon, QMouseEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QPlainTextEdit,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QWidget,
)

from autolingua2.ir import UnitState
from autolingua2.ui.i18n import tr

if TYPE_CHECKING:
    from autolingua2.ir import TranslationUnit


def _opt_rect(option: QStyleOptionViewItem) -> QRect:
    rect: QRect = getattr(option, "rect")
    return rect


def _opt_palette(option: QStyleOptionViewItem) -> QPalette:
    palette: QPalette = getattr(option, "palette")
    return palette


def _opt_state(option: QStyleOptionViewItem) -> int:
    return int(getattr(option, "state", 0))


class StatusComboBoxDelegate(QStyledItemDelegate):
    """状態（ステータス）列用のDelegate。
    通常時はコンボボックスの見た目をペイントし、クリック時に本物のQComboBoxを展開する。
    """

    status_changed = Signal(int, object)  # row: int, new_status: UnitState | str

    def __init__(self, icon_getter: Callable[[str], QIcon], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.icon_getter = icon_getter

    def _get_status_options(self) -> list[tuple[str, UnitState | str, str]]:
        return [
            (tr("MainWindow", "未翻訳"), UnitState.UNTRANSLATED, "circle"),
            (tr("MainWindow", "AIによる翻訳"), UnitState.AI_TRANSLATED, "robot-edit"),
            (tr("MainWindow", "人間による翻訳"), UnitState.HUMAN_TRANSLATED, "person-edit-32"),
            (tr("MainWindow", "AIによる校閲"), UnitState.AI_REVIEWED, "robot-check"),
            (tr("MainWindow", "人間による校閲"), UnitState.HUMAN_REVIEWED, "person-check"),
            (tr("MainWindow", "疑問あり"), UnitState.DOUBTFUL, "question"),
            (tr("MainWindow", "ロック"), "locked", "lock"),
            (tr("MainWindow", "非表示"), "hidden", "eye-slash"),
        ]

    COMBO_HEIGHT = 28
    COMBO_MARGIN_X = 6

    def _combo_rect(self, option_rect: QRect) -> QRect:
        y = option_rect.top() + max(0, (option_rect.height() - self.COMBO_HEIGHT) // 2)
        return QRect(
            option_rect.left() + self.COMBO_MARGIN_X,
            y,
            max(0, option_rect.width() - self.COMBO_MARGIN_X * 2),
            self.COMBO_HEIGHT,
        )

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        painter.save()
        opt_rect = _opt_rect(option)
        palette = _opt_palette(option)
        rect = self._combo_rect(opt_rect)

        # コンボボックス外枠と背景の描画
        painter.setPen(palette.mid().color())
        painter.setBrush(palette.button())
        painter.drawRoundedRect(rect, 4, 4)

        # アイコン描画
        icon_data = index.data(Qt.ItemDataRole.DecorationRole)
        text_left = rect.left() + 8
        if isinstance(icon_data, QIcon):
            icon_rect = QRect(rect.left() + 6, rect.top() + (rect.height() - 14) // 2, 14, 14)
            icon_data.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)
            text_left += 18

        # ドロップダウン矢印（繊細な∨シェブロン）
        arrow_x = rect.right() - 14
        arrow_y = rect.top() + (rect.height() - 4) // 2
        painter.setPen(QPen(palette.text().color(), 1.5))
        painter.drawLine(arrow_x - 4, arrow_y, arrow_x, arrow_y + 4)
        painter.drawLine(arrow_x, arrow_y + 4, arrow_x + 4, arrow_y)

        # テキスト描画
        text_right = arrow_x - 6
        text_rect = QRect(text_left, rect.top(), max(0, text_right - text_left), rect.height())
        raw_text = index.data(Qt.ItemDataRole.DisplayRole)
        display_text = str(raw_text) if raw_text is not None else ""
        painter.setPen(palette.text().color())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, display_text)

        painter.restore()

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        opt_rect = _opt_rect(option)
        editor.setGeometry(self._combo_rect(opt_rect))

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QWidget:
        combo = QComboBox(parent)
        combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        combo.setStyleSheet(
            "QComboBox { border: 1px solid palette(mid); border-radius: 4px; padding: 2px 6px; } "
            "QComboBox::drop-down { border: none; }"
        )

        for label, val, icon_name in self._get_status_options():
            combo.addItem(self.icon_getter(icon_name), label, val)

        # クリック時に即座に閉じてしまわないよう、少し遅延させてドロップダウンを確実に開く
        QTimer.singleShot(0, combo.showPopup)

        # 項目が選択されたらコミットしてエディタを閉じる
        combo.activated.connect(lambda _: self._commit_and_close(combo))
        return combo

    def _commit_and_close(self, combo: QComboBox) -> None:
        self.commitData.emit(combo)
        self.closeEditor.emit(combo)

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        if not isinstance(editor, QComboBox):
            return
        unit: TranslationUnit | None = index.data(Qt.ItemDataRole.UserRole)
        if unit is None:
            return

        current_val: UnitState | str
        if unit.hidden:
            current_val = "hidden"
        elif unit.locked:
            current_val = "locked"
        else:
            current_val = unit.state

        idx = editor.findData(current_val)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex | QPersistentModelIndex) -> None:
        if not isinstance(editor, QComboBox):
            return
        data = editor.currentData()
        self.status_changed.emit(index.row(), data)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        return QSize(140, 36)


class ActionButtonDelegate(QStyledItemDelegate):
    """操作列用のDelegate。
    スプリットボタンの見た目をペイントし、
    左側クリックで選択中モデル翻訳、右側（chevron-down）クリックで登録全モデル翻訳を発火する。
    """

    action_clicked = Signal(int)  # row: int (選択されたAIモデル)
    action_all_models_clicked = Signal(int)  # row: int (登録された全モデル)

    BUTTON_WIDTH = 76
    BUTTON_HEIGHT = 28
    MENU_WIDTH = 22

    def __init__(self, icon_getter: Callable[[str], QIcon], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.icon_getter = icon_getter
        self._pressed_row: int = -1
        self._pressed_part: str = ""

    def _button_rect(self, option_rect: QRect) -> QRect:
        x = option_rect.left() + max(0, (option_rect.width() - self.BUTTON_WIDTH) // 2)
        y = option_rect.top() + max(0, (option_rect.height() - self.BUTTON_HEIGHT) // 2)
        return QRect(x, y, self.BUTTON_WIDTH, self.BUTTON_HEIGHT)

    def _main_rect(self, btn_rect: QRect) -> QRect:
        return QRect(btn_rect.left(), btn_rect.top(), btn_rect.width() - self.MENU_WIDTH, btn_rect.height())

    def _menu_rect(self, btn_rect: QRect) -> QRect:
        return QRect(btn_rect.right() - self.MENU_WIDTH + 1, btn_rect.top(), self.MENU_WIDTH, btn_rect.height())

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        painter.save()
        opt_rect = _opt_rect(option)
        palette = _opt_palette(option)
        btn_rect = self._button_rect(opt_rect)
        main_rect = self._main_rect(btn_rect)
        menu_rect = self._menu_rect(btn_rect)

        is_row_pressed = index.row() == self._pressed_row
        is_main_pressed = is_row_pressed and self._pressed_part == "main"
        is_menu_pressed = is_row_pressed and self._pressed_part == "menu"

        # 外枠の角丸四角形
        painter.setPen(palette.mid().color())
        painter.setBrush(palette.button())
        painter.drawRoundedRect(btn_rect, 4, 4)

        # プレス領域のハイライト
        if is_main_pressed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.midlight())
            painter.drawRoundedRect(main_rect, 4, 4)
        elif is_menu_pressed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.midlight())
            painter.drawRoundedRect(menu_rect, 4, 4)

        # スプリット区切り線
        sep_x = main_rect.right()
        painter.setPen(palette.mid().color())
        painter.drawLine(sep_x, btn_rect.top() + 3, sep_x, btn_rect.bottom() - 3)

        # 左側（メイン部）: アイコン + テキスト
        icon = self.icon_getter("sparkles")
        icon_rect = QRect(main_rect.left() + 4, main_rect.top() + (main_rect.height() - 14) // 2, 14, 14)
        icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)

        text_rect = QRect(main_rect.left() + 18, main_rect.top(), main_rect.width() - 20, main_rect.height())
        painter.setPen(palette.buttonText().color())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, tr("MainWindow", "翻訳"))

        # 右側（メニュー部）: chevron-down.svg
        arrow_icon = self.icon_getter("chevron-down")
        arrow_rect = QRect(menu_rect.left() + (menu_rect.width() - 12) // 2, menu_rect.top() + (menu_rect.height() - 12) // 2, 12, 12)
        arrow_icon.paint(painter, arrow_rect, Qt.AlignmentFlag.AlignCenter)

        painter.restore()

    def editorEvent(self, event: QEvent, model: QAbstractItemModel, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> bool:
        if not isinstance(event, QMouseEvent):
            return False

        opt_rect = _opt_rect(option)
        btn_rect = self._button_rect(opt_rect)
        main_rect = self._main_rect(btn_rect)
        menu_rect = self._menu_rect(btn_rect)
        pos = event.position().toPoint()

        if event.type() == QEvent.Type.MouseButtonPress:
            if main_rect.contains(pos):
                self._pressed_row = index.row()
                self._pressed_part = "main"
                if hasattr(model, "dataChanged"):
                    model.dataChanged.emit(index, index)
                return True
            elif menu_rect.contains(pos):
                self._pressed_row = index.row()
                self._pressed_part = "menu"
                if hasattr(model, "dataChanged"):
                    model.dataChanged.emit(index, index)
                return True

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self._pressed_row == index.row():
                part = self._pressed_part
                self._pressed_row = -1
                self._pressed_part = ""
                if hasattr(model, "dataChanged"):
                    model.dataChanged.emit(index, index)
                if part == "main" and main_rect.contains(pos):
                    self.action_clicked.emit(index.row())
                    return True
                elif part == "menu" and menu_rect.contains(pos):
                    self.action_all_models_clicked.emit(index.row())
                    return True

        return False

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        return QSize(self.BUTTON_WIDTH + 12, self.BUTTON_HEIGHT + 12)


class MultiLineTextDelegate(QStyledItemDelegate):
    """訳文列用の複数行テキストDelegate。
    通常時は折り返しテキストを描画し、編集時はQPlainTextEditを起動する。
    """

    text_committed = Signal(int, str)  # row: int, new_text: str

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        painter.save()
        opt_rect = _opt_rect(option)
        palette = _opt_palette(option)
        state = _opt_state(option)

        is_selected = bool(state & QStyle.StateFlag.State_Selected.value)
        if is_selected:
            painter.fillRect(opt_rect, palette.highlight())
            painter.setPen(palette.highlightedText().color())
        else:
            painter.setPen(palette.text().color())

        raw_text = index.data(Qt.ItemDataRole.DisplayRole)
        display_text = str(raw_text) if raw_text is not None else ""
        padding_rect = opt_rect.adjusted(6, 4, -6, -4)
        painter.drawText(
            padding_rect,
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            display_text,
        )
        painter.restore()

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QWidget:
        edit = QPlainTextEdit(parent)
        edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        edit.setStyleSheet("QPlainTextEdit { border: 1px solid palette(highlight); background: palette(base); padding: 2px 4px; }")
        return edit

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        if isinstance(editor, QPlainTextEdit):
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""
            editor.setPlainText(text)

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex | QPersistentModelIndex) -> None:
        if isinstance(editor, QPlainTextEdit):
            new_text = editor.toPlainText()
            self.text_committed.emit(index.row(), new_text)
