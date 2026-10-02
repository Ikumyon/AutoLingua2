from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QFile, QIODeviceBase, QObject, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autolingua2.infrastructure.filesystem import UI_DIR


class DropZone(QWidget):
    """汎用ドラッグ＆ドロップ枠ウィジェット。

    クリックによるファイル選択ダイアログ、DnDによるファイル受け入れ、
    および内部への追加ボタン（アクション）配置に対応します。
    """

    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
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

        # DropZone.ui をロードして自身の子ウィジェットとして組み込み
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
        root_layout.addWidget(self._ui_widget)

        frame = self._ui_widget.findChild(QFrame, "frameDropZone")
        icon = self._ui_widget.findChild(QLabel, "labelDropIcon")
        hint = self._ui_widget.findChild(QLabel, "labelDropHint")
        actions = self._ui_widget.findChild(QHBoxLayout, "layoutDropActions")
        if frame is None or icon is None or hint is None or actions is None:
            raise RuntimeError("DropZone.ui の必須ウィジェットが見つかりません")

        self.frame_drop_zone = frame
        self.label_icon = icon
        self.label_hint = hint
        self.layout_actions = actions

        self.set_hint_text(hint_text)

        # イベントフィルタの設定（フレームおよびそのラベルでのクリックとDnDを監視）
        self.frame_drop_zone.installEventFilter(self)
        self.label_icon.installEventFilter(self)
        self.label_hint.installEventFilter(self)

    def set_hint_text(self, text: str) -> None:
        """ヒントテキストを変更します。"""
        self.label_hint.setText(text)

    def set_icon_text(self, icon: str) -> None:
        """アイコン表示（絵文字やテキスト）を変更します。"""
        self.label_icon.setText(icon)

    def add_button(self, text: str, on_clicked: Callable[[], None] | None = None) -> QPushButton:
        """ドロップ枠内の右側ボタンスロットに新しいボタンを追加します。"""
        button = QPushButton(text, self.frame_drop_zone)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        if on_clicked is not None:
            button.clicked.connect(on_clicked)
        self.layout_actions.addWidget(button)
        return button

    def add_action_widget(self, widget: QWidget) -> None:
        """ドロップ枠内の右側ボタンスロットに任意のウィジェットを追加します。"""
        self.layout_actions.addWidget(widget)

    def _set_hover_highlight(self, active: bool) -> None:
        self.frame_drop_zone.setProperty("dragOver", active)
        style = self.frame_drop_zone.style()
        if style is not None:
            style.unpolish(self.frame_drop_zone)
            style.polish(self.frame_drop_zone)

    def _filter_matching_paths(self, paths: list[Path]) -> list[Path]:
        if not self.allowed_extensions:
            return paths
        return [p for p in paths if p.suffix.lower() in self.allowed_extensions]

    def _open_file_dialog(self) -> None:
        if self.allow_multiple:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                self.label_hint.text(),
                "",
                self.dialog_filter,
            )
            paths = [Path(f) for f in files if f]
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self.label_hint.text(),
                "",
                self.dialog_filter,
            )
            paths = [Path(file_path)] if file_path else []

        valid_paths = self._filter_matching_paths(paths)
        if valid_paths:
            self.files_dropped.emit(valid_paths)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in {self.frame_drop_zone, self.label_icon, self.label_hint}:
            if isinstance(event, QDragEnterEvent):
                if event.mimeData().hasUrls():
                    urls = event.mimeData().urls()
                    paths = [Path(u.toLocalFile()) for u in urls if u.toLocalFile()]
                    if self._filter_matching_paths(paths):
                        self._set_hover_highlight(True)
                        event.acceptProposedAction()
                        return True
            elif isinstance(event, QDragMoveEvent):
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif isinstance(event, QDragLeaveEvent):
                self._set_hover_highlight(False)
                return True
            elif isinstance(event, QDropEvent):
                self._set_hover_highlight(False)
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    urls = event.mimeData().urls()
                    paths = [Path(u.toLocalFile()) for u in urls if u.toLocalFile()]
                    valid_paths = self._filter_matching_paths(paths)
                    if valid_paths:
                        self.files_dropped.emit(valid_paths)
                    return True
            elif isinstance(event, QMouseEvent):
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    self.clicked.emit()
                    if self.auto_file_dialog:
                        self._open_file_dialog()
                    return True
        return super().eventFilter(watched, event)
