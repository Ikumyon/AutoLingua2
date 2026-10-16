"""Debug-only widget IDs with delayed pinning and clipboard access."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QEvent, QObject, QParallelAnimationGroup, QPauseAnimation, QPoint,
    QPropertyAnimation, QSequentialAnimationGroup, Qt,
)
from PySide6.QtGui import QHelpEvent, QIcon, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QMenu,
    QLabel, QProgressBar, QPushButton, QToolButton, QToolTip, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from autolingua2.ui.i18n import tr
from autolingua2.ui.shortcuts import ShortcutManager


class DebugTooltips(QObject):
    """Intercept tooltips application-wide, including dynamically created widgets."""

    def __init__(self, app: QApplication, get_icon: Callable[[str], QIcon]) -> None:
        super().__init__(app)
        self.app = app
        self.source: QWidget | None = None
        self.pinned = False
        self.widget_id = ""

        self.popup = QFrame(None, Qt.WindowType.ToolTip | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.popup.setObjectName("debugIdTooltip")
        self.popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.popup.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(8, 0, 4, 8)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.progress = QProgressBar(self.popup)
        self.progress.setRange(0, 2000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        top.addWidget(self.progress, 1, Qt.AlignmentFlag.AlignTop)

        self.corner = QToolButton(self.popup)
        self.corner.setAutoRaise(True)
        self.corner.setFixedSize(24, 24)
        self.corner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.corner.setAccessibleName(tr("DebugTooltips", "閉じる"))
        self.corner.clicked.connect(self._close_if_pinned)
        top.addWidget(self.corner, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self.shortcut_info = QLabel(self.popup)
        self.shortcut_info.setWordWrap(True)
        self.shortcut_info.setTextFormat(Qt.TextFormat.PlainText)
        self.shortcut_info.hide()
        layout.addWidget(self.shortcut_info)

        self.effects: list[QGraphicsOpacityEffect] = []
        for name in ("lock-open-1", "lock", "x"):
            label = QLabel(self.corner)
            label.setGeometry(4, 4, 16, 16)
            label.setPixmap(get_icon(name).pixmap(16, 16))
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            effect = QGraphicsOpacityEffect(label)
            label.setGraphicsEffect(effect)
            self.effects.append(effect)

        self.description = QLabel(self.popup)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.shortcut_button = QPushButton(tr("DebugTooltips", "この操作のキー設定を開く"), self.popup)
        self.shortcut_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.shortcut_button.clicked.connect(self._edit_shortcut)
        self.shortcut_button.hide()
        self.shortcut_id = ""
        layout.addWidget(self.shortcut_button)
        bottom = QHBoxLayout()
        self.id_label = QLabel(self.popup)
        self.id_label.setTextFormat(Qt.TextFormat.PlainText)
        self.id_label.setWordWrap(True)
        bottom.addWidget(self.id_label, 1)
        self.copy_button = QPushButton(tr("DebugTooltips", "コピー"), self.popup)
        self.copy_button.setIcon(get_icon("copy"))
        self.copy_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_button.clicked.connect(self._copy)
        bottom.addWidget(self.copy_button)
        layout.addLayout(bottom)
        for widget in (self.progress, self.copy_button):
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            widget.setSizePolicy(policy)

        self.countdown = QPropertyAnimation(self.progress, b"value", self)
        self.countdown.setDuration(2000)
        self.countdown.setStartValue(0)
        self.countdown.setEndValue(2000)
        self.countdown.finished.connect(self._pin)
        self.transition = QSequentialAnimationGroup(self)
        self.transition.addAnimation(self._fade(0, 1))
        self.transition.addAnimation(QPauseAnimation(700, self.transition))
        self.transition.addAnimation(self._fade(1, 2))
        app.installEventFilter(self)
        app.aboutToQuit.connect(self._close)

    def _fade(self, outgoing: int, incoming: int) -> QParallelAnimationGroup:
        group = QParallelAnimationGroup()
        for index, start, end in ((outgoing, 1.0, 0.0), (incoming, 0.0, 1.0)):
            animation = QPropertyAnimation(self.effects[index], b"opacity", group)
            animation.setDuration(150)
            animation.setStartValue(start)
            animation.setEndValue(end)
            group.addAnimation(animation)
        return group

    def _copy(self) -> None:
        if self.pinned:
            self.app.clipboard().setText(self.widget_id)

    def _close_if_pinned(self) -> None:
        if self.pinned:
            self._close()

    def _close(self) -> None:
        self.countdown.stop()
        self.transition.stop()
        self.source = None
        self.pinned = False
        self.widget_id = ""
        self.popup.hide()

    def _pin(self) -> None:
        source = self.source
        if source is None or not isValid(source) or not source.isVisible():
            self._close()
            return
        # Pin immediately. Icon animation is visual feedback, not a state gate.
        self.pinned = True
        self.progress.hide()
        self.copy_button.show()
        self.shortcut_button.setEnabled(True)
        self.transition.start()

    def refresh_shortcut(self) -> None:
        source = self.source
        self.shortcut_id = ""
        if source is None or not isValid(source):
            self.shortcut_info.hide()
            self.shortcut_button.hide()
            return
        manager = ShortcutManager.current()
        command = manager.command_for(source)
        if isinstance(source, QMenu):
            action = source.activeAction()
            command_id = action.property("shortcutId") if action is not None else None
            if isinstance(command_id, str):
                command = manager.commands.get(command_id)
        visible = manager.debug and manager.index_mode and command is not None
        self.shortcut_info.setVisible(visible)
        self.shortcut_button.setVisible(visible)
        self.shortcut_button.setEnabled(self.pinned)
        if visible and command is not None:
            self.shortcut_id = command.id
            keys = " / ".join(manager.effective(command.id)) or tr("DebugTooltips", "未割り当て")
            self.shortcut_info.setText(tr("DebugTooltips", "{name}  {keys}\n場所：{location}").format(
                name=command.name, keys=keys, location=command.location))
        if self.popup.isVisible():
            self.popup.adjustSize()

    def _edit_shortcut(self) -> None:
        if self.pinned and self.shortcut_id:
            command_id = self.shortcut_id
            self._close()
            ShortcutManager.current().edit_requested.emit(command_id)

    def _show(self, source: QWidget, event: QHelpEvent) -> bool:
        owner: QWidget | None = source
        while owner is not None:
            name = owner.objectName()
            if name and not name.startswith("qt_"):
                break
            owner = owner.parentWidget()
        if owner is None:
            return False
        screen = source.screen()
        if screen is None:
            return False
        self._close()
        self.source = source
        self.widget_id = owner.objectName()
        description = source.toolTip() or owner.toolTip()
        if isinstance(owner, QAbstractItemView):
            index = owner.indexAt(owner.viewport().mapFromGlobal(event.globalPos()))
            item_tip = index.data(Qt.ItemDataRole.ToolTipRole)
            if isinstance(item_tip, str) and item_tip:
                description = item_tip
        self.description.setText(description)
        self.description.setVisible(bool(description))
        self.refresh_shortcut()
        self.id_label.setText(f"ID: {self.widget_id}")
        self.copy_button.hide()
        self.progress.setValue(0)
        self.progress.show()
        for index, effect in enumerate(self.effects):
            effect.setOpacity(1.0 if index == 0 else 0.0)
        # Associate with the modal window without giving it ownership of the popup.
        # A dynamically destroyed dialog must not destroy this shared tooltip.
        self.popup.winId()
        popup_window = self.popup.windowHandle()
        if popup_window is None:
            raise RuntimeError("デバッグツールチップのウィンドウを作成できません。")
        popup_window.setTransientParent(source.window().windowHandle())
        available = screen.availableGeometry()
        self.popup.setFixedWidth(min(480, available.width()))
        self.popup.adjustSize()
        position = event.globalPos() + QPoint(16, 20)
        self.popup.move(
            max(available.left(), min(position.x(), available.right() - self.popup.width() + 1)),
            max(available.top(), min(position.y(), available.bottom() - self.popup.height() + 1)),
        )
        QToolTip.hideText()
        self.popup.show()
        self.countdown.start()
        return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self.popup.isVisible():
            if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
                if event.type() == QEvent.Type.ShortcutOverride:
                    event.accept()
                    return True
                if event.type() == QEvent.Type.KeyPress:
                    self._close()
                    return True
            if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                position = self.popup.mapFromGlobal(event.globalPosition().toPoint())
                if not self.popup.rect().contains(position):
                    self._close()
            source = self.source
            if source is not None:
                if not isValid(source):
                    self._close()
                elif isinstance(watched, QWidget) and (
                    watched is source or watched.isAncestorOf(source)
                ) and event.type() in {QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.DeferredDelete}:
                    self._close()
                elif watched is source and event.type() == QEvent.Type.Leave and not self.pinned:
                    self._close()
            if event.type() == QEvent.Type.ApplicationDeactivate:
                self._close()
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent) and isinstance(watched, QWidget):
            if watched is self.popup or self.popup.isAncestorOf(watched) or self.pinned:
                return True
            if watched is self.source and self.popup.isVisible():
                return True
            if self._show(watched, event):
                event.accept()
                return True
        return super().eventFilter(watched, event)
