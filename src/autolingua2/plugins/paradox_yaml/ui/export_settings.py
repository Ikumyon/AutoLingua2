"""Output options owned entirely by the Paradox plugin."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from autolingua2.plugins.contracts import ImportedTranslation


class ParadoxExportWidget(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        self.layout_ids = ["language", "mixed"]
        self.folder_layout = QComboBox(self)
        self.folder_layout.addItem(QCoreApplication.translate("ParadoxExport", "言語ごとのフォルダに分ける"))
        self.folder_layout.addItem(QCoreApplication.translate("ParadoxExport", "同じフォルダに配置する"))
        form.addRow(QCoreApplication.translate("ParadoxExport", "フォルダ構成："), self.folder_layout)


class ParadoxExportSettings:
    def create_widget(self, workspaces: list[ImportedTranslation], parent: QWidget) -> QWidget:
        return ParadoxExportWidget(parent)

    def read_settings(self, widget: QWidget) -> dict[str, object]:
        if not isinstance(widget, ParadoxExportWidget):
            raise ValueError("出力設定のウィジェットが不正です。")
        layout_index = widget.folder_layout.currentIndex()
        if layout_index < 0:
            raise ValueError("出力設定を選択してください。")
        return {"layout": widget.layout_ids[layout_index]}
