from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox
from autolingua2.ui.i18n import tr


class CommonCreationPanel(QWidget):
    def __init__(self, context):
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
        self.cancel.clicked.connect(context.cancel_operation)
        self.set_busy(False)
        self.retranslate_ui()

    def _add(self, paths):
        try:
            for path in paths:
                self.context.add_target_path(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, tr("MainWindow", "エラー"), str(exc))

    def _files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("MainWindow", "ファイル追加"))
        self._add(paths)

    def _folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("MainWindow", "フォルダ追加"))
        if path:
            self._add([path])

    def set_busy(self, busy):
        self.files.setEnabled(not busy)
        self.folders.setEnabled(not busy)
        self.cancel.setEnabled(busy)

    def set_status(self, message):
        self.status.setText(message)

    def retranslate_ui(self):
        self.prompt.setText(tr("MainWindow", "対象ファイル・フォルダをドロップ"))
        self.files.setText(tr("MainWindow", "ファイル追加"))
        self.folders.setText(tr("MainWindow", "フォルダ追加"))
        self.cancel.setText(tr("MainWindow", "キャンセル"))
        self.files.setIcon(self.context.get_icon("file"))
        self.folders.setIcon(self.context.get_icon("folder"))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
