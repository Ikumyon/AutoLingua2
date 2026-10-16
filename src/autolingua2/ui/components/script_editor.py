from __future__ import annotations

import re

from PySide6.QtCore import Property, QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPaintEvent, QPainter, QPalette, QResizeEvent, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from autolingua2.ir.automation_script import RESERVED, TYPES


class _ScriptHighlighter(QSyntaxHighlighter):
    # Include unfinished strings so highlighting remains useful while typing.
    _tokens = re.compile(
        r'(?P<comment>//[^\n]*)|(?P<string>"(?:\\.|[^"\\])*"?)'
        r'|(?P<number>\b\d+(?:\.\d+)?\b)|(?P<name>[^\W\d]\w*)'
    )

    def __init__(self, editor: ScriptEditor) -> None:
        super().__init__(editor.document())
        self.editor = editor

    def highlightBlock(self, text: str) -> None:
        position = offset = 0
        for match in self._tokens.finditer(text):
            kind = match.lastgroup
            if kind == "name":
                name = match.group()
                if name in TYPES or name == "void":
                    kind = "type"
                elif name in RESERVED:
                    kind = "keyword"
                elif text[match.end():].lstrip().startswith("("):
                    kind = "function"
            offset += len(text[position:match.start()].encode("utf-16-le")) // 2
            length = len(match.group().encode("utf-16-le")) // 2
            if kind in self.editor.syntax_formats:
                self.setFormat(offset, length, self.editor.syntax_formats[kind])
            position = match.end()
            offset += length


class _LineNumbers(QWidget):
    def __init__(self, editor: ScriptEditor) -> None:
        super().__init__(editor)
        self.editor = editor

    def paintEvent(self, event: QPaintEvent) -> None:
        self.editor.paint_line_numbers(event)


class ScriptEditor(QPlainTextEdit):
    """Script editor with line numbers and theme-controlled syntax colors."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.syntax_formats: dict[str, QTextCharFormat] = {
            kind: QTextCharFormat() for kind in ("keyword", "type", "function", "string", "number", "comment")
        }
        self.highlighter = _ScriptHighlighter(self)
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self.highlighter.rehighlight)
        self.line_numbers = _LineNumbers(self)
        self.blockCountChanged.connect(self._resize_gutter)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self.line_numbers.update)
        self._resize_gutter()

    def _syntax_color(self, kind: str) -> QColor:
        return self.syntax_formats[kind].foreground().color()

    def _set_syntax_color(self, kind: str, color: QColor) -> None:
        self.syntax_formats[kind].setForeground(color)
        self._highlight_timer.start(0)

    keywordColor = Property(QColor, lambda self: self._syntax_color("keyword"),
                            lambda self, color: self._set_syntax_color("keyword", color))
    typeColor = Property(QColor, lambda self: self._syntax_color("type"),
                         lambda self, color: self._set_syntax_color("type", color))
    functionColor = Property(QColor, lambda self: self._syntax_color("function"),
                             lambda self, color: self._set_syntax_color("function", color))
    stringColor = Property(QColor, lambda self: self._syntax_color("string"),
                           lambda self, color: self._set_syntax_color("string", color))
    numberColor = Property(QColor, lambda self: self._syntax_color("number"),
                           lambda self, color: self._set_syntax_color("number", color))
    commentColor = Property(QColor, lambda self: self._syntax_color("comment"),
                            lambda self, color: self._set_syntax_color("comment", color))

    def _resize_gutter(self) -> None:
        width = 16 + self.fontMetrics().horizontalAdvance("9") * len(str(self.blockCount()))
        self.setViewportMargins(width, 0, 0, 0)
        rect = self.contentsRect()
        self.line_numbers.setGeometry(QRect(rect.left(), rect.top(), width, rect.height()))
        self.line_numbers.update()

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_numbers.scroll(0, dy)
        else:
            self.line_numbers.update(0, rect.y(), self.line_numbers.width(), rect.height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._resize_gutter()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}:
            self._resize_gutter()

    def paint_line_numbers(self, event: QPaintEvent) -> None:
        painter = QPainter(self.line_numbers)
        painter.fillRect(event.rect(), self.palette().brush(QPalette.ColorRole.AlternateBase))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        current = self.textCursor().blockNumber()
        while block.isValid():
            top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
            height = round(self.blockBoundingRect(block).height())
            if top > event.rect().bottom():
                break
            if block.isVisible() and top + height >= event.rect().top():
                role = QPalette.ColorRole.Text if block.blockNumber() == current else QPalette.ColorRole.PlaceholderText
                painter.setPen(self.palette().color(role))
                painter.drawText(
                    0, top, self.line_numbers.width() - 8, self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1),
                )
            block = block.next()
        painter.end()
