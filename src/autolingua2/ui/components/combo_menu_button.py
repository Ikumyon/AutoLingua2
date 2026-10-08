from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QPaintEvent
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QStylePainter


class ComboMenuButton(QPushButton):
    """Menu button with an explicit text inset independent of arrow styling."""

    TEXT_INSET = 6
    ARROW_SPACE = 28

    def text_rect(self) -> QRect:
        return self.rect().adjusted(self.TEXT_INSET, 0, -self.ARROW_SPACE, 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QStylePainter(self)
        # Keep Qt's background, hover, focus and menu-arrow drawing intact.
        # PySide's style-option fields are dynamic and absent from type stubs.
        setattr(option, "text", "")
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        # Custom menu-indicator rules bypass QSS padding for button contents.
        setattr(option, "text", self.text())
        setattr(option, "rect", self.text_rect())
        features = getattr(option, "features")
        if not isinstance(features, QStyleOptionButton.ButtonFeature):
            raise TypeError("Invalid button style features")
        setattr(option, "features", features & ~QStyleOptionButton.ButtonFeature.HasMenu)
        painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, option)
        painter.end()
