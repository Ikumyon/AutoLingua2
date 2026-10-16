from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QEvent, QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QSizePolicy, QToolButton, QWidget

from autolingua2.ui.ui_loader import load_ui, require_child


class SearchBar(QWidget):
    """Shared search input and options; callers own query interpretation."""

    placeholder_changed = Signal(str)
    query_tooltip_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._placeholder_text = ""
        self._query_tooltip = ""

    def initialize_ui(self) -> None:
        """Called by load_ui only after the containing form has finished loading."""
        self.contents = load_ui("components/SearchBar.ui", self)
        self.frame = require_child(self.contents, QFrame, "frameSearch")
        self.replace_toggle = require_child(self.contents, QToolButton, "buttonToggleReplace")
        self._fold_icons = (QIcon(), QIcon())
        self.replace_toggle.toggled.connect(self._update_replace_icon)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.contents)
        self.editor = require_child(self.frame, QLineEdit, "editSearch")
        self._search_action = QAction(self.editor)
        self.editor.addAction(self._search_action, QLineEdit.ActionPosition.LeadingPosition)
        self.case_button = require_child(self.frame, QToolButton, "buttonSearchCase")
        self.word_button = require_child(self.frame, QToolButton, "buttonSearchWord")
        self.regex_button = require_child(self.frame, QToolButton, "buttonSearchRegex")
        self.editor.setPlaceholderText(self._placeholder_text)
        self.editor.setToolTip(self._query_tooltip)
        self.placeholder_changed.connect(self.editor.setPlaceholderText)
        self.query_tooltip_changed.connect(self.editor.setToolTip)
        self.setFocusProxy(self.editor)
        self.editor.installEventFilter(self)

    def set_icons(self, get_icon: Callable[[str], QIcon]) -> None:
        self._search_action.setIcon(get_icon("search-16"))
        self.case_button.setIcon(get_icon("case-sensitive"))
        self.word_button.setIcon(get_icon("whole-word"))
        self.regex_button.setIcon(get_icon("regex"))
        self._fold_icons = (get_icon("chevron-right"), get_icon("chevron-down"))
        self._update_replace_icon(self.replace_toggle.isChecked())

    def _update_replace_icon(self, expanded: bool) -> None:
        self.replace_toggle.setIcon(self._fold_icons[int(expanded)])

    def bind_replace_panel(self, panel: QWidget) -> None:
        self.replace_toggle.toggled.connect(panel.setVisible)
        panel.setVisible(self.replace_toggle.isChecked())

    def _set_placeholder_text(self, text: str) -> None:
        self._placeholder_text = text
        self.placeholder_changed.emit(text)

    def _set_query_tooltip(self, text: str) -> None:
        self._query_tooltip = text
        self.query_tooltip_changed.emit(text)

    placeholderText = Property(str, lambda self: self._placeholder_text, _set_placeholder_text,
                               notify=placeholder_changed)
    queryToolTip = Property(str, lambda self: self._query_tooltip, _set_query_tooltip,
                            notify=query_tooltip_changed)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.editor and event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
            self.frame.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            style = self.frame.style()
            style.unpolish(self.frame)
            style.polish(self.frame)
            self.frame.update()
        return super().eventFilter(watched, event)
