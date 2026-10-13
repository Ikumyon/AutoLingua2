from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMimeData, QRect, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QInputMethodEvent, QKeyEvent,
    QMouseEvent, QPainter, QPalette, QPyTextObject, QTextCharFormat, QTextCursor,
    QTextDocument, QTextFormat,
)
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTextEdit, QWidget

from autolingua2.services.chat_references import ChatAttachment, read_chat_file

REFERENCE_MIME = "application/x-autolingua-chat-reference"
REFERENCE_OBJECT = int(QTextFormat.ObjectTypes.UserObject) + 1
REFERENCE_ID = int(QTextFormat.Property.UserProperty) + 1


class ReferenceObject(QPyTextObject):
    def __init__(self, editor: ChatComposer) -> None:
        super().__init__(editor)
        self.editor = editor

    def intrinsicSize(self, doc: QTextDocument, pos: int, format: QTextFormat) -> QSizeF:
        reference = self.editor.reference(format)
        metrics = self.editor.fontMetrics()
        return QSizeF(metrics.horizontalAdvance(reference.name) + 18, metrics.height() + 8)

    def drawObject(self, painter: QPainter, rect: QRectF | QRect, doc: QTextDocument,
                   pos: int, format: QTextFormat) -> None:
        rect = QRectF(rect)
        reference = self.editor.reference(format)
        palette = self.editor.palette()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.brush(QPalette.ColorRole.AlternateBase))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)
        painter.setPen(palette.color(QPalette.ColorRole.Link))
        painter.setFont(self.editor.font())
        painter.drawText(rect.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, reference.name)
        painter.restore()


class ChatComposer(QTextEdit):
    reference_requested = Signal(object)
    reference_error = Signal(str)
    send_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        self._references: dict[str, ChatAttachment] = {}
        self._preediting = False
        self._reference_object = ReferenceObject(self)
        layout = self.document().documentLayout()
        if layout is None:
            raise RuntimeError("Chat composer requires a document layout")
        layout.registerHandler(REFERENCE_OBJECT, self._reference_object)

    def reference(self, format: QTextFormat) -> ChatAttachment:
        key = format.property(REFERENCE_ID)
        if not isinstance(key, str) or key not in self._references:
            raise ValueError("文中参照が見つかりません")
        return self._references[key]

    def insert_reference(self, reference: ChatAttachment, cursor: QTextCursor | None = None) -> None:
        self._references[reference.id] = reference
        insertion = QTextCursor(cursor if cursor is not None else self.textCursor())
        format = QTextCharFormat()
        format.setObjectType(REFERENCE_OBJECT)
        format.setProperty(REFERENCE_ID, reference.id)
        format.setToolTip(reference.origin)
        insertion.insertText("\ufffc", format)
        insertion.setCharFormat(QTextCharFormat())
        self.setTextCursor(insertion)
        self.setFocus()

    def message(self) -> tuple[str, tuple[ChatAttachment, ...]]:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        parts: list[str] = []
        references: dict[str, ChatAttachment] = {}
        while cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor):
            text = cursor.selectedText()
            if text == "\ufffc":
                reference = self.reference(cursor.charFormat())
                references[reference.id] = reference
                parts.append(f"［{reference.name}］")
            else:
                parts.append(text.replace("\u2029", "\n"))
            cursor.clearSelection()
        return "".join(parts).strip(), tuple(references.values())

    def clear(self) -> None:
        super().clear()
        self._references.clear()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (not self._preediting and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if not self.isReadOnly():
                self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        self._preediting = bool(event.preeditString())
        super().inputMethodEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        cursor = self.cursorForPosition(event.position().toPoint())
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        if cursor.selectedText() != "\ufffc":
            cursor = self.cursorForPosition(event.position().toPoint())
            cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor)
        if (cursor.selectedText() == "\ufffc" and event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            cursor.setPosition(cursor.selectionEnd())
            self.reference_requested.emit(self.reference(cursor.charFormat()))
        super().mouseReleaseEvent(event)

    def _accepts(self, mime: QMimeData) -> bool:
        return not self.isReadOnly() and (mime.hasUrls() or mime.hasFormat(REFERENCE_MIME))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accepts(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._accepts(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if not self._accepts(mime):
            super().dropEvent(event)
            return
        cursor = self.cursorForPosition(event.position().toPoint())
        try:
            if mime.hasFormat(REFERENCE_MIME):
                value = json.loads(bytes(mime.data(REFERENCE_MIME).data()).decode("utf-8"))
                if not isinstance(value, dict) or not all(isinstance(value.get(k), str)
                                                         for k in ("id", "name", "origin", "content")):
                    raise ValueError("行参照の形式が不正です")
                self.insert_reference(ChatAttachment(value["id"], value["name"], value["origin"], value["content"]), cursor)
            else:
                for url in mime.urls():
                    if not url.isLocalFile():
                        raise ValueError("ローカルのテキストファイルを選択してください")
                    try:
                        reference = read_chat_file(Path(url.toLocalFile()))
                        self.insert_reference(reference, cursor)
                        cursor = self.textCursor()
                    except (OSError, ValueError) as exc:
                        self.reference_error.emit(str(exc))
        except (ValueError, UnicodeError) as exc:
            self.reference_error.emit(str(exc))
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def createMimeDataFromSelection(self) -> QMimeData:
        # Copying to another application produces the readable reference names.
        mime = QMimeData()
        selected = self.textCursor()
        cursor = QTextCursor(self.document())
        cursor.setPosition(selected.selectionStart())
        parts: list[str] = []
        while cursor.position() < selected.selectionEnd():
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            text = cursor.selectedText()
            parts.append(self.reference(cursor.charFormat()).name if text == "\ufffc" else text.replace("\u2029", "\n"))
            cursor.clearSelection()
        mime.setText("".join(parts))
        return mime


class ChatReferenceTable(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.reference_supplier: Callable[[], ChatAttachment | None] | None = None
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        if self.reference_supplier is None:
            return
        reference = self.reference_supplier()
        if reference is None:
            return
        mime = QMimeData()
        mime.setData(REFERENCE_MIME, json.dumps(reference.document(), ensure_ascii=False).encode("utf-8"))
        mime.setText(reference.name)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
