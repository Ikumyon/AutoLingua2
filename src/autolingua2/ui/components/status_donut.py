from __future__ import annotations

from autolingua2.ui.resources.i18n import translation_source

import math

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from autolingua2.ir import UnitState
from autolingua2.ui.resources.i18n import tr


STATUS_LABELS: dict[UnitState, str] = {
    UnitState.UNTRANSLATED: translation_source('MainWindow', '未翻訳'),
    UnitState.AI_TRANSLATED: translation_source('MainWindow', 'AIによる翻訳'),
    UnitState.HUMAN_TRANSLATED: translation_source('MainWindow', '人間による翻訳'),
    UnitState.AI_REVIEWED: translation_source('MainWindow', 'AIによる校閲'),
    UnitState.HUMAN_REVIEWED: translation_source('MainWindow', '人間による校閲'),
    UnitState.REVIEW_ISSUES: translation_source('MainWindow', '校閲指摘あり'),
    UnitState.TRANSLATION_ERROR: translation_source('MainWindow', '翻訳エラー'),
    UnitState.REVIEW_ERROR: translation_source('MainWindow', '校閲エラー'),
    UnitState.DOUBTFUL: translation_source('MainWindow', '疑問あり'),
    UnitState.LOCKED: translation_source('MainWindow', 'ロック'),
    UnitState.HIDDEN: translation_source('MainWindow', '非表示'),
}


class StatusDonut(QWidget):
    """Draw and interpolate the persisted translation states."""

    state_clicked = Signal(object)  # UnitState, or None for the center

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setMinimumSize(216, 216)
        self.setMouseTracking(True)
        self._states = tuple(UnitState)
        self._counts = dict.fromkeys(UnitState, 0)
        self._total = 0
        self._fractions = (0.0,) * len(self._states)
        self._start = self._fractions
        self._target = self._fractions
        self._sweep = 1.0
        self._sweep_start = 1.0
        self._sweep_target = 1.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(500)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._advance)
        self._selected_state: UnitState | None = None
        self._offsets = (0.0,) * len(self._states)
        self._offset_start = self._offsets
        self._offset_target = self._offsets
        self._offset_animation = QVariantAnimation(self)
        self._offset_animation.setDuration(500)
        self._offset_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._offset_animation.setStartValue(0.0)
        self._offset_animation.setEndValue(1.0)
        self._offset_animation.valueChanged.connect(self._advance_selection)

    def state_color(self, state: UnitState) -> QColor:
        if state == UnitState.LOCKED:
            return self.palette().mid().color()
        if state == UnitState.HIDDEN:
            return self.palette().midlight().color()
        return QColor({
            UnitState.UNTRANSLATED: "#8594ab",
            UnitState.AI_TRANSLATED: "#4c91e8",
            UnitState.HUMAN_TRANSLATED: "#9275db",
            UnitState.AI_REVIEWED: "#20a897",
            UnitState.HUMAN_REVIEWED: "#67b64a",
            UnitState.REVIEW_ISSUES: "#c79030",
            UnitState.TRANSLATION_ERROR: "#d94f4f",
            UnitState.REVIEW_ERROR: "#d66c37",
            UnitState.DOUBTFUL: "#e7a33c",
        }[state])

    def set_counts(self, counts: dict[UnitState, int], *, reveal: bool = False) -> None:
        if counts == self._counts and not reveal:
            return
        self._animation.stop()
        self._counts = counts.copy()
        self._total = sum(counts.values())
        target = tuple(counts[state] / self._total if self._total else 0.0
                       for state in self._states)
        self._start = target if reveal else self._fractions
        self._target = target
        self._sweep_start = 0.0 if reveal else self._sweep
        self._sweep_target = 1.0
        self._fractions = self._start
        self._sweep = self._sweep_start
        self._animation.start()
        self._animate_selection()
        self.update()

    def set_selected_state(self, state: UnitState | None, *, animate: bool = True) -> None:
        self._selected_state = state
        self._animate_selection(animate=animate)

    def _animate_selection(self, *, animate: bool = True) -> None:
        target = tuple(12.0 if state == self._selected_state
                       and 0 < self._counts[state] < self._total else 0.0
                       for state in self._states)
        if animate and target == self._offset_target:
            return
        self._offset_animation.stop()
        self._offset_start = self._offsets
        self._offset_target = target
        if animate:
            self._offset_animation.start()
        else:
            self._offsets = target
        self.update()

    def _advance_selection(self, value: object) -> None:
        if not isinstance(value, (int, float)):
            raise TypeError("Donut selection animation requires a numeric value")
        self._offsets = tuple(start + (target - start) * value
                              for start, target in zip(self._offset_start, self._offset_target, strict=True))
        self.update()

    def stop_animation(self) -> None:
        self._animation.stop()
        self._offset_animation.stop()

    def _advance(self, value: object) -> None:
        if not isinstance(value, (int, float)):
            raise TypeError("Donut animation requires a numeric value")
        self._fractions = tuple(start + (target - start) * value
                                for start, target in zip(self._start, self._target, strict=True))
        self._sweep = self._sweep_start + (self._sweep_target - self._sweep_start) * value
        self.update()

    def _ring_rect(self) -> QRectF:
        diameter = min(self.width(), self.height()) - 64.0
        return QRectF((self.width() - diameter) / 2, (self.height() - diameter) / 2,
                      diameter, diameter)

    def _arcs(self) -> list[tuple[UnitState, QRectF, float, float]]:
        ring = self._ring_rect()
        angle = 90.0
        arcs: list[tuple[UnitState, QRectF, float, float]] = []
        for state, fraction, offset in zip(self._states, self._fractions, self._offsets, strict=True):
            sweep = fraction * 360.0 * self._sweep
            # A single 100% state keeps the entire ring centered.
            if self._counts[state] == self._total:
                offset = 0.0
            midpoint = math.radians(angle - sweep / 2)
            rect = ring.translated(offset * math.cos(midpoint), -offset * math.sin(midpoint))
            arcs.append((state, rect, angle, sweep))
            angle -= sweep
        return arcs

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = self._ring_rect()
        if self._total == 0 or self._sweep < 1.0:
            painter.setPen(QPen(self.palette().alternateBase().color(), 28.0))
            painter.drawEllipse(ring)
        for state, rect, angle, sweep in self._arcs():
            if sweep > 0:
                painter.setPen(QPen(self.state_color(state), 28.0,
                                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                painter.drawArc(rect, round(angle * 16), -round(sweep * 16))
        painter.setPen(self.palette().text().color())
        font = painter.font()
        font.setPixelSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(ring, Qt.AlignmentFlag.AlignCenter,
                         tr("MainWindow", "全件数") + f"\n{self._total:,} " + tr("MainWindow", "件"))
        painter.end()

    def _state_at(self, event: QMouseEvent) -> UnitState | None:
        # Check in reverse paint order, using each arc's current translated center.
        for state, rect, start_angle, sweep in reversed(self._arcs()):
            if self._counts[state] == 0 or sweep <= 0:
                continue
            x = event.position().x() - rect.center().x()
            y = event.position().y() - rect.center().y()
            if abs(math.hypot(x, y) - rect.width() / 2) > 14:
                continue
            angle = math.degrees(math.atan2(x, -y)) % 360
            start = (90.0 - start_angle) % 360
            if (angle - start) % 360 < sweep:
                return state
        return None

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        state = self._state_at(event)
        self.setCursor(Qt.CursorShape.PointingHandCursor if state is not None else Qt.CursorShape.ArrowCursor)
        self.setToolTip("" if state is None else
                        f"{tr('MainWindow', STATUS_LABELS[state])}: {self._counts[state]:,}")
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            state = self._state_at(event)
            ring = self._ring_rect()
            distance = math.hypot(event.position().x() - ring.center().x(),
                                  event.position().y() - ring.center().y())
            if state is not None or distance < ring.width() / 2 - 14:
                self.state_clicked.emit(state)
                event.accept()
                return
        super().mousePressEvent(event)

