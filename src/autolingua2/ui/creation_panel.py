from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox
from autolingua2.ui.i18n import tr
from autolingua2.plugins.api import PluginContext


class CommonCreationAdapter:
    def __init__(self) -> None:
        self._panels: set[CommonCreationPanel] = set()
        self._subscribed = False

    def create_creation_panel(self, context: PluginContext) -> QWidget:
        if not self._subscribed:
            context.on_language_changed(self._change_language)
            context.on_close(self._panels.clear)
            self._subscribed = True
        panel = CommonCreationPanel(context)
        self._panels.add(panel)
        return panel

    def on_paths_dropped(self, paths: list[Path], context: PluginContext) -> list[Path]:
        return paths

    def on_game_selected(self, game_id: str, context: PluginContext) -> None:
        pass

    def format_target_path_label(self, path: Path, current_source_lang: str) -> tuple[str, str, str]:
        return path.name, "", str(path)

    def dispose_creation_panel(self, panel: QWidget) -> None:
        if not isinstance(panel, CommonCreationPanel):
            raise TypeError("Unexpected common panel")
        self._panels.discard(panel)

    def _change_language(self, language: str) -> None:
        for panel in self._panels:
            panel.retranslate_ui()


class CommonCreationPanel(QWidget):
    def __init__(self, context: PluginContext) -> None:
        super().__init__()
        self.context = context
        layout = QVBoxLayout(self)
        self.prompt = QLabel(self)
        layout.addWidget(self.prompt)
        row = QHBoxLayout()
        self.files = QPushButton(self)
        self.folders = QPushButton(self)
        self.cancel = QPushButton(self)
        self.status = QLabel(self)
        for button in (self.files, self.folders, self.cancel):
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(self.status)
        self.files.clicked.connect(self._files)
        self.folders.clicked.connect(self._folder)
        self.cancel.clicked.connect(context.creation.cancel_operation)
        self.set_busy(False)
        self.retranslate_ui()

    def _add(self, paths: list[str]) -> None:
        try:
            for path in paths:
                self.context.creation.add_target_path(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, tr("MainWindow", "エラー"), str(exc))

    def _files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("MainWindow", "ファイル追加"))
        self._add(paths)

    def _folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("MainWindow", "フォルダ追加"))
        if path:
            self._add([path])

    def set_busy(self, busy: bool) -> None:
        self.files.setEnabled(not busy)
        self.folders.setEnabled(not busy)
        self.cancel.setEnabled(busy)

    def set_status(self, message: str) -> None:
        self.status.setText(message)

    def retranslate_ui(self) -> None:
        self.prompt.setText(tr("MainWindow", "対象ファイル・フォルダをドロップ"))
        self.files.setText(tr("MainWindow", "ファイル追加"))
        self.folders.setText(tr("MainWindow", "フォルダ追加"))
        self.cancel.setText(tr("MainWindow", "キャンセル"))
        self.files.setIcon(self.context.get_icon("file"))
        self.folders.setIcon(self.context.get_icon("folder"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
