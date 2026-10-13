from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QIODeviceBase, QObject, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QIcon, QMouseEvent, QShowEvent
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from autolingua2.infrastructure.filesystem import UI_DIR


class DropZone(QWidget):
    """内容と任意のボタンを呼び出し側が配置する汎用ドロップ枠。"""

    files_dropped = Signal(list)
    multiple_files_rejected = Signal()
    clicked = Signal()

    def __init__(
        self, parent: QWidget | None = None,
        hint_text: str = "ここをクリックまたはファイルをドロップ",
        allowed_extensions: set[str] | list[str] | None = None,
        auto_file_dialog: bool = True,
        dialog_filter: str = "All Files (*.*)",
        allow_multiple: bool = True,
    ) -> None:
        super().__init__(parent)
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions} if allowed_extensions else None
        self.auto_file_dialog = auto_file_dialog
        self.dialog_filter = dialog_filter
        self.allow_multiple = allow_multiple
        self._content_widget: QWidget | None = None
        self._ui_widget: QWidget | None = None
        self._hint_text = hint_text

    def _ensure_ui(self) -> None:
        # QUiLoaderによるカスタム部品の生成中に、別の.uiを読み込まない。
        if self._ui_widget is not None:
            return
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        ui_path = UI_DIR / "components" / "DropZone.ui"
        file = QFile(str(ui_path))
        if not file.open(QIODeviceBase.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"UIファイルを開けません: {ui_path}")
        try:
            loader = QUiLoader()
            loader.setLanguageChangeEnabled(True)
            widget = loader.load(file, self)
        finally:
            file.close()
        if widget is None:
            raise RuntimeError(f"UIファイルを読み込めません: {ui_path}")
        self._ui_widget = widget
        root_layout.addWidget(widget)

        frame = widget.findChild(QFrame, "frameDropZone")
        header = widget.findChild(QWidget, "headerDropZone")
        icon = widget.findChild(QLabel, "labelDropIcon")
        hint = widget.findChild(QLabel, "labelDropHint")
        actions = widget.findChild(QHBoxLayout, "layoutDropActions")
        content = widget.findChild(QVBoxLayout, "layoutDropContent")
        if frame is None or header is None or icon is None or hint is None or actions is None or content is None:
            raise RuntimeError("DropZone.ui の必須ウィジェットが見つかりません")
        self.frame_drop_zone = frame
        self.header = header
        self.label_icon = icon
        self.label_hint = hint
        self.layout_actions = actions
        self._content_layout = content
        for target in (frame, icon, hint):
            target.setAcceptDrops(True)
            target.installEventFilter(self)
        self.set_hint_text(self._hint_text)

    def showEvent(self, event: QShowEvent) -> None:
        self._ensure_ui()
        super().showEvent(event)

    def set_hint_text(self, text: str) -> None:
        self._ensure_ui()
        self._hint_text = text
        self.label_hint.setText(text)
        self.label_hint.setVisible(bool(text))
        self.label_icon.setVisible(bool(text))
        self.header.setVisible(bool(text) or self.layout_actions.count() > 0)

    def set_icon_text(self, icon: str) -> None:
        self._ensure_ui()
        self.label_icon.setText(icon)

    def set_content_widget(self, widget: QWidget) -> None:
        """内容を置き換える。以前の内容は枠が破棄する。"""
        self._ensure_ui()
        if self._content_widget is widget:
            return
        if self._content_widget is not None:
            previous = self._content_widget
            previous.removeEventFilter(self)
            self._content_layout.removeWidget(previous)
            previous.hide()
            previous.deleteLater()
        self._content_widget = widget
        self._content_layout.addWidget(widget)
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)
        widget.show()

    def add_button(
        self, text: str, on_clicked: Callable[[], None] | None = None,
        *, icon: QIcon | None = None,
    ) -> QPushButton:
        """文言・アイコン・動作は呼び出し側が指定する。"""
        self._ensure_ui()
        button = QPushButton(text, self.frame_drop_zone)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        if icon is not None:
            button.setIcon(icon)
        if on_clicked is not None:
            button.clicked.connect(on_clicked)
        self.add_action_widget(button)
        return button

    def add_action_widget(self, widget: QWidget) -> None:
        self._ensure_ui()
        self.layout_actions.addWidget(widget)
        self.header.show()

    def _filter_paths(self, paths: list[Path]) -> list[Path]:
        if not self.allowed_extensions:
            return paths
        return [path for path in paths if path.suffix.lower() in self.allowed_extensions]

    def _set_hover(self, active: bool) -> None:
        self.frame_drop_zone.setProperty("dragOver", active and self.isEnabled())
        style = self.frame_drop_zone.style()
        if style is not None:
            style.unpolish(self.frame_drop_zone)
            style.polish(self.frame_drop_zone)

    def _open_file_dialog(self) -> None:
        if self.allow_multiple:
            files, _ = QFileDialog.getOpenFileNames(self, self.label_hint.text(), "", self.dialog_filter)
            paths = [Path(file) for file in files if file]
        else:
            file, _ = QFileDialog.getOpenFileName(self, self.label_hint.text(), "", self.dialog_filter)
            paths = [Path(file)] if file else []
        valid_paths = self._filter_paths(paths)
        if valid_paths:
            self.files_dropped.emit(valid_paths)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        click_targets = (self.frame_drop_zone, self.label_icon, self.label_hint)
        if watched in (*click_targets, self._content_widget):
            if isinstance(event, QDragLeaveEvent):
                self._set_hover(False)
                return True
            if isinstance(event, (QDragEnterEvent, QDragMoveEvent, QDropEvent)):
                if not self.isEnabled():
                    self._set_hover(False)
                    event.ignore()
                    return True
                mime = event.mimeData()
                local_paths = [
                    Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()
                ] if mime is not None else []
                if not self.allow_multiple and len(local_paths) > 1:
                    self._set_hover(False)
                    # Accept the drag without highlighting so the drop can explain the rejection.
                    if isinstance(event, QDropEvent):
                        event.ignore()
                        self.multiple_files_rejected.emit()
                    else:
                        event.acceptProposedAction()
                    return True
                paths = self._filter_paths(local_paths)
                if isinstance(event, QDropEvent) or not paths:
                    self._set_hover(False)
                if not paths:
                    event.ignore()
                    return True
                event.acceptProposedAction()
                if isinstance(event, QDropEvent):
                    self.files_dropped.emit(paths)
                else:
                    self._set_hover(True)
                return True
            if watched in click_targets and isinstance(event, QMouseEvent):
                if not self.isEnabled():
                    return True
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    self.clicked.emit()
                    if self.auto_file_dialog:
                        self._open_file_dialog()
                    return True
        return super().eventFilter(watched, event)
