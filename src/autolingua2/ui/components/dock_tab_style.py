from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QProxyStyle, QStyle, QStyleOption, QStyleOptionTab, QTabBar, QWidget,
)


class DockTabStyle(QProxyStyle):
    """Keep Qt's dock tabs, with optional upright labels on either side."""

    def __init__(self, bar: QTabBar, horizontal_text: bool) -> None:
        # A proxy owns its base style; never give it the shared application style.
        super().__init__()
        self.setParent(bar)
        self.horizontal_text = horizontal_text

    def _upright(self, option: QStyleOption) -> bool:
        return (
            self.horizontal_text
            and isinstance(option, QStyleOptionTab)
            and option.shape in (QTabBar.Shape.RoundedWest, QTabBar.Shape.RoundedEast)
        )

    def sizeFromContents(
        self, type: QStyle.ContentsType, option: QStyleOption,
        size: QSize, widget: QWidget, /,
    ) -> QSize:
        if type == QStyle.ContentsType.CT_TabBarTab and self._upright(option):
            if not isinstance(option, QStyleOptionTab):
                raise TypeError("Dock tab sizing requires QStyleOptionTab")
            horizontal = QStyleOptionTab(option)
            horizontal.shape = QTabBar.Shape.RoundedNorth
            return super().sizeFromContents(type, horizontal, size.transposed(), widget)
        return super().sizeFromContents(type, option, size, widget)

    def drawControl(
        self, element: QStyle.ControlElement, option: QStyleOption,
        painter: QPainter, /, widget: QWidget | None = None,
    ) -> None:
        if element == QStyle.ControlElement.CE_TabBarTabLabel and self._upright(option):
            if not isinstance(option, QStyleOptionTab) or not isinstance(widget, QTabBar):
                raise TypeError("Dock tab labels require a QTabBar and QStyleOptionTab")
            horizontal = QStyleOptionTab(option)
            horizontal.shape = QTabBar.Shape.RoundedNorth
            # Qt elides side-tab text against the tab height. Use its width instead.
            index = widget.tabAt(option.rect.center())
            if index >= 0:
                padding = self.pixelMetric(QStyle.PixelMetric.PM_TabBarTabHSpace, horizontal, widget)
                icon_width = 0 if horizontal.icon.isNull() else horizontal.iconSize.width() + 4
                horizontal.text = widget.fontMetrics().elidedText(
                    widget.tabText(index), Qt.TextElideMode.ElideRight,
                    max(0, horizontal.rect.width() - padding - icon_width),
                )
            super().drawControl(element, horizontal, painter, widget)
            return
        super().drawControl(element, option, painter, widget)
