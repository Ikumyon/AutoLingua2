from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget,
)

from autolingua2.services.settings_store import AiModel
from autolingua2.ui.resource_api import IconAPI


class _InlineLineEdit(QLineEdit):
    escapePressed = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            self.clearFocus()
            return
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self.escapePressed.emit()
            return
        super().keyPressEvent(event)

class InlineEditableField(QWidget):
    valueChanged = Signal(str)

    def __init__(
        self,
        text: str = "",
        placeholder: str = "",
        *,
        icon_manager: IconAPI,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._placeholder = placeholder
        self.icon_manager = icon_manager

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)

        self.label = QLabel(text or placeholder, self)
        if not text:
            self.label.setStyleSheet("color: #888;")
        self.icon_pencil = QLabel(self)
        pencil_icon = self.icon_manager.get_icon("pencil")
        if not pencil_icon.isNull():
            self.icon_pencil.setPixmap(pencil_icon.pixmap(QSize(13, 13)))
        else:
            self.icon_pencil.setText("✏")
        self.icon_pencil.setVisible(False)

        self.line_edit = _InlineLineEdit(text, self)
        self.line_edit.setPlaceholderText(placeholder)
        self.line_edit.setVisible(False)

        layout.addWidget(self.label, 1)
        layout.addWidget(self.icon_pencil)
        layout.addWidget(self.line_edit, 1)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.line_edit.editingFinished.connect(self._on_editing_finished)
        self.line_edit.escapePressed.connect(self._on_escape_pressed)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.label.setText(text or self._placeholder)
        if not text:
            self.label.setStyleSheet("color: #888;")
        else:
            self.label.setStyleSheet("")
        self.line_edit.setText(text)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if not self.line_edit.isVisible():
            self.icon_pencil.setVisible(True)
            self.setStyleSheet(
                "InlineEditableField { border: 1px dashed rgba(160, 160, 160, 0.6); border-radius: 4px; background: rgba(255, 255, 255, 0.05); }"
            )

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if not self.line_edit.isVisible():
            self.icon_pencil.setVisible(False)
            self.setStyleSheet("InlineEditableField { border: 1px solid transparent; background: transparent; }")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.line_edit.isVisible():
            self.start_edit()
            return
        super().mousePressEvent(event)

    def start_edit(self) -> None:
        self.label.setVisible(False)
        self.icon_pencil.setVisible(False)
        self.setStyleSheet("InlineEditableField { border: none; background: transparent; }")
        self.line_edit.setVisible(True)
        self.line_edit.setText(self._text)
        self.line_edit.setFocus()
        self.line_edit.selectAll()

    def _on_escape_pressed(self) -> None:
        self.line_edit.setText(self._text)
        self.line_edit.setVisible(False)
        self.label.setVisible(True)
        self.icon_pencil.setVisible(False)
        self.setStyleSheet("InlineEditableField { border: 1px solid transparent; background: transparent; }")

    def _on_editing_finished(self) -> None:
        if not self.line_edit.isVisible():
            return
        new_text = self.line_edit.text().strip()
        changed = (new_text != self._text)
        self._text = new_text
        self.label.setText(new_text or self._placeholder)
        if not new_text:
            self.label.setStyleSheet("color: #888;")
        else:
            self.label.setStyleSheet("")
        self.line_edit.setVisible(False)
        self.label.setVisible(True)
        if self.underMouse():
            self.icon_pencil.setVisible(True)
            self.setStyleSheet(
                "InlineEditableField { border: 1px dashed rgba(160, 160, 160, 0.6); border-radius: 4px; background: rgba(255, 255, 255, 0.05); }"
            )
        else:
            self.icon_pencil.setVisible(False)
            self.setStyleSheet("InlineEditableField { border: 1px solid transparent; background: transparent; }")
        if changed:
            self.valueChanged.emit(self._text)

class ModelRowWidget(QFrame):
    deleted = Signal(object)
    modelCommitted = Signal(object)

    def __init__(
        self,
        entry: AiModel,
        icon_manager: IconAPI,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.icon_manager = icon_manager
        self.setStyleSheet("ModelRowWidget { border-radius: 6px; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self.check_enabled = QCheckBox(self)
        self.check_enabled.setChecked(entry.enabled)
        self.check_enabled.setToolTip("有効/無効")

        self.field_name = InlineEditableField(entry.name, placeholder="表示名", icon_manager=self.icon_manager, parent=self)
        self.field_model = InlineEditableField(entry.model, placeholder="モデル名 (例: gpt-6.1-sol)", icon_manager=self.icon_manager, parent=self)

        self.button_delete = QToolButton(self)
        trash_icon = self.icon_manager.get_icon("trash")
        if not trash_icon.isNull():
            self.button_delete.setIcon(trash_icon)
            self.button_delete.setIconSize(QSize(15, 15))
        else:
            self.button_delete.setText("✕")
        self.button_delete.setToolTip("このモデルを削除")
        self.button_delete.setFixedSize(26, 26)
        self.button_delete.setStyleSheet(
            "QToolButton { border: none; border-radius: 4px; padding: 2px; }"
            "QToolButton:hover { background-color: #e81123; }"
        )

        layout.addWidget(self.check_enabled)
        layout.addWidget(self.field_name, 1)
        layout.addWidget(self.field_model, 1)
        layout.addWidget(self.button_delete)

        self.button_delete.clicked.connect(lambda: self.deleted.emit(self))
        self.field_model.valueChanged.connect(lambda _: self.modelCommitted.emit(self))

        self._status: str | None = None
        self._status_tooltip: str = ""
        self.check_enabled.toggled.connect(self._on_enabled_toggled)
        if not entry.enabled:
            self.set_status("disabled", "無効化されています")

    def _on_enabled_toggled(self, checked: bool) -> None:
        if not checked:
            self.set_status("disabled", "無効化されています")
        else:
            self.set_status(
                self._status if self._status != "disabled" else None,
                self._status_tooltip if self._status != "disabled" else "",
            )

    def set_status(self, status: str | None, tooltip: str = "") -> None:
        if status != "disabled":
            self._status = status
            self._status_tooltip = tooltip
        self.setProperty("status", status or "")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setToolTip(tooltip)

    def to_ai_model(self) -> AiModel:
        name = self.field_name.text().strip()
        model = self.field_model.text().strip()
        return AiModel(
            name=name or model,
            model=model,
            enabled=self.check_enabled.isChecked(),
        )
