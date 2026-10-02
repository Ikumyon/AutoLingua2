from __future__ import annotations

from typing import Callable, Literal
from PySide6.QtCore import Property, QEvent, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QMouseEvent, QPaintEvent, QPainter, QPainterPath
from PySide6.QtWidgets import QLineEdit, QWidget


class RangeScrubberWidget(QWidget):
    """汎用スクラバー・スライダーコンポーネント。

    - 長方形のバーに「塗り色（現在値）」と「ホバー色（プレビュー）」の2層描画。
    - クリック移動（ジャンプ）判定が、数字入力判定を全周囲（上下左右）で包み込む（GIMPモデル）。
    - 数字表示位置: 'left'（左端）、'center'（中央）、'right'（右端）を宣言可能。
    """

    value_changed = Signal(int)
    page_changed = Signal(int)  # 互換用シグナル

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        text_alignment: Literal["left", "center", "right"] | Qt.AlignmentFlag,
        min_value: int = 1,
        max_value: int = 1,
        fill_color: QColor | str = "#0d6efd",
        hover_color: QColor | str = QColor(255, 255, 255, 36),
        bg_color: QColor | str = "#2b2d30",
        border_color: QColor | str = "#3c3f41",
        text_color: QColor | str = "#ffffff",
        format_text: Callable[[int, int], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFixedHeight(26)

        self._min_value: int = min_value
        self._max_value: int = max(min_value, max_value)
        self._current_value: int = min_value
        self._hover_value: int | None = None

        # 色・スタイルの抽象化
        self.fill_color: QColor = QColor(fill_color) if isinstance(fill_color, str) else fill_color
        self.hover_color: QColor = QColor(hover_color) if isinstance(hover_color, str) else hover_color
        self.bg_color: QColor = QColor(bg_color) if isinstance(bg_color, str) else bg_color
        self.border_color: QColor = QColor(border_color) if isinstance(border_color, str) else border_color
        self.text_color: QColor = QColor(text_color) if isinstance(text_color, str) else text_color

        self._text_align_flag: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter
        self._align_type: str = "center"
        self._set_text_alignment(text_alignment)

        self._format_text: Callable[[int, int], str] = (
            format_text if format_text is not None else (lambda v, total: f"{v} / {total}")
        )

        font = self.font()
        font.setPointSize(10)
        font.setBold(True)
        self.setFont(font)

        # 直接入力用インラインエディット
        self._input_edit = QLineEdit(self)
        self._input_edit.hide()
        self._update_input_edit_alignment()
        self._input_edit.setFont(font)
        self._input_edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: #1e1f22;"
            "  color: #ffffff;"
            "  border: 1px solid #0d6efd;"
            "  border-radius: 2px;"
            "  padding: 0px;"
            "}"
        )
        self._input_edit.returnPressed.connect(self._commit_inline_edit)
        self._input_edit.installEventFilter(self)
        self._update_minimum_width()

    def _set_text_alignment(
        self, align: Literal["left", "center", "right"] | Qt.AlignmentFlag
    ) -> None:
        if align in ("left", Qt.AlignmentFlag.AlignLeft):
            self._text_align_flag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            self._align_type = "left"
        elif align in ("right", Qt.AlignmentFlag.AlignRight):
            self._text_align_flag = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            self._align_type = "right"
        else:
            self._text_align_flag = Qt.AlignmentFlag.AlignCenter
            self._align_type = "center"

    def _update_input_edit_alignment(self) -> None:
        if self._align_type == "left":
            self._input_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        elif self._align_type == "right":
            self._input_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            self._input_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)

    @property
    def text_alignment(self) -> str:
        return self._align_type

    @text_alignment.setter
    def text_alignment(
        self, align: Literal["left", "center", "right"] | Qt.AlignmentFlag
    ) -> None:
        self._set_text_alignment(align)
        self._update_input_edit_alignment()
        self.update()

    # ------------------------------------------------------------------
    # QSS スタイルプロパティ (qproperty-<name>)
    # ------------------------------------------------------------------
    @Property(QColor)
    def fillColor(self) -> QColor:
        return self.fill_color

    @fillColor.setter
    def fillColor(self, color: QColor) -> None:
        self.fill_color = color
        self.update()

    @Property(QColor)
    def hoverColor(self) -> QColor:
        return self.hover_color

    @hoverColor.setter
    def hoverColor(self, color: QColor) -> None:
        self.hover_color = color
        self.update()

    @Property(QColor)
    def bgColor(self) -> QColor:
        return self.bg_color

    @bgColor.setter
    def bgColor(self, color: QColor) -> None:
        self.bg_color = color
        self.update()

    @Property(QColor)
    def borderColor(self) -> QColor:
        return self.border_color

    @borderColor.setter
    def borderColor(self, color: QColor) -> None:
        self.border_color = color
        self.update()

    @Property(QColor)
    def textColor(self) -> QColor:
        return self.text_color

    @textColor.setter
    def textColor(self, color: QColor) -> None:
        self.text_color = color
        self.update()

    # ------------------------------------------------------------------
    # プロパティ
    # ------------------------------------------------------------------
    @property
    def current_page(self) -> int:
        return self._current_value

    @property
    def total_pages(self) -> int:
        return self._max_value

    def set_pages(self, current_page: int, total_pages: int) -> None:
        new_max = max(self._min_value, total_pages)
        new_val = max(self._min_value, min(new_max, current_page))
        if self._current_value != new_val or self._max_value != new_max:
            max_changed = self._max_value != new_max
            self._current_value = new_val
            self._max_value = new_max
            if max_changed:
                self._update_minimum_width()
            if self._input_edit.isVisible():
                self._cancel_inline_edit()
            self.update()

    def set_current_page(self, current_page: int) -> None:
        self.set_pages(current_page, self._max_value)

    def _update_minimum_width(self) -> None:
        """桁数に応じた最小幅を自動計算して設定。"""
        sample_text = self._format_text(self._max_value, self._max_value)
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance(sample_text)
        min_w = max(60, text_w + 24)
        self.setMinimumWidth(min_w)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        sample_text = self._format_text(self._max_value, self._max_value)
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance(sample_text)
        return QSize(max(60, text_w + 24), 26)

    def sizeHint(self) -> QSize:
        min_hint = self.minimumSizeHint()
        return QSize(max(100, min_hint.width() + 20), 26)

    # ------------------------------------------------------------------
    # 座標・判定計算
    # ------------------------------------------------------------------
    def _val_to_width(self, val: int) -> float:
        """値から1の色のゲージ描画幅（px）を計算。"""
        w = float(self.width())
        total_range = self._max_value - self._min_value
        if total_range <= 0:
            return w
        min_w = 6.0
        ratio = (val - self._min_value) / float(total_range)
        return min_w + ratio * (w - min_w)

    def _x_to_value(self, x: float) -> int:
        """X座標から値を計算。"""
        total_range = self._max_value - self._min_value
        if total_range <= 0:
            return self._min_value
        w = max(1.0, float(self.width()))
        ratio = max(0.0, min(1.0, x / w))
        val = round(self._min_value + ratio * total_range)
        return max(self._min_value, min(self._max_value, val))

    def _get_input_hit_rect(self) -> QRectF:
        """数字入力判定ボックス（クリック移動判定に包まれている芯の部分）。"""
        w = float(self.width())
        h = float(self.height())
        v_margin = 4.0  # 上下4pxはジャンプ判定
        h_padding = 8.0  # 左右端のマージン
        box_h = max(12.0, h - v_margin * 2)

        display_text = self._format_text(self._current_value, self._max_value)
        fm = QFontMetrics(self.font())
        text_w = float(fm.horizontalAdvance(display_text))
        box_w = min(w - 16.0, max(44.0, text_w + 14.0))

        if self._align_type == "left":
            box_x = h_padding
        elif self._align_type == "right":
            box_x = max(0.0, w - box_w - h_padding)
        else:
            box_x = (w - box_w) / 2.0

        box_y = v_margin
        return QRectF(box_x, box_y, box_w, box_h)

    # ------------------------------------------------------------------
    # 描画
    # ------------------------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        radius = 2.0  # 長方形バー

        # 外枠クリップ
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        # 1. ベース背景（長方形バー）
        painter.fillPath(path, self.bg_color)

        cur_w = self._val_to_width(self._current_value)

        # 2. 塗り色（左端から現在値まで満たす）
        painter.fillRect(QRectF(0, 0, cur_w, h), self.fill_color)

        # 3. ホバー色（塗り色の上に重ねて描画）
        if (
            self._hover_value is not None
            and self._hover_value != self._current_value
            and not self._input_edit.isVisible()
        ):
            hover_w = self._val_to_width(self._hover_value)
            hl_left = min(cur_w, hover_w)
            hl_w = abs(hover_w - cur_w)
            painter.fillRect(QRectF(hl_left, 0, hl_w, h), self.hover_color)

        # 4. 境界線
        painter.setClipping(False)
        painter.setPen(self.border_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        # 5. テキスト描画 (直接入力中は非表示)
        if not self._input_edit.isVisible():
            display_val = (
                self._hover_value if self._hover_value is not None else self._current_value
            )
            text = self._format_text(display_val, self._max_value)
            painter.setPen(self.text_color)
            text_rect = rect.adjusted(8.0, 0, -8.0, 0)
            painter.drawText(text_rect, self._text_align_flag, text)

    # ------------------------------------------------------------------
    # マウス・クリック判定（GIMPモデル：周囲はジャンプ、芯は数字入力）
    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        hit_rect = self._get_input_hit_rect()

        # カーソル形状：芯の部分ならIビーム、周囲ならポインター
        if hit_rect.contains(pos) and not self._input_edit.isVisible():
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        if not self._input_edit.isVisible():
            val = self._x_to_value(pos.x())
            if self._hover_value != val:
                self._hover_value = val
                self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            hit_rect = self._get_input_hit_rect()

            if hit_rect.contains(pos):
                # 中央の芯をクリック：数字入力モード開始
                self._start_inline_editing(hit_rect)
            else:
                # 包んでいる外側（上下ヘリ・左右余白）をクリック：その位置へジャンプ！
                val = self._x_to_value(pos.x())
                if self._input_edit.isVisible():
                    self._cancel_inline_edit()
                if self._current_value != val:
                    self._current_value = val
                    self.value_changed.emit(val)
                    self.page_changed.emit(val)
                    self.update()
        super().mousePressEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self._hover_value is not None:
            self._hover_value = None
            self.update()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # 直接入力モード
    # ------------------------------------------------------------------
    def _start_inline_editing(self, rect: QRectF) -> None:
        self._hover_value = None
        rx = int(rect.x())
        ry = int(rect.y())
        rw = int(rect.width())
        rh = int(rect.height())
        self._input_edit.setGeometry(rx, ry, rw, rh)
        self._input_edit.setText(str(self._current_value))
        self._input_edit.show()
        self._input_edit.setFocus()
        self._input_edit.selectAll()
        self.update()

    def _commit_inline_edit(self) -> None:
        text = self._input_edit.text().strip()
        self._input_edit.hide()
        if text.isdigit():
            val = int(text)
            target_val = max(self._min_value, min(self._max_value, val))
            if self._current_value != target_val:
                self._current_value = target_val
                self.value_changed.emit(target_val)
                self.page_changed.emit(target_val)
        self.update()

    def _cancel_inline_edit(self) -> None:
        self._input_edit.hide()
        self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._input_edit:
            if event.type() == QEvent.Type.KeyPress:
                assert isinstance(event, QKeyEvent)
                if event.key() == Qt.Key.Key_Escape:
                    self._cancel_inline_edit()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                self._commit_inline_edit()
                return True
        return super().eventFilter(watched, event)


