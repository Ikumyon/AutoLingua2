"""Output options owned entirely by the Paradox plugin."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from autolingua2.plugins.contracts import ImportedTranslation
from autolingua2.ui.ui_loader import load_ui, require_child


class ParadoxExportWidget(QWidget):
    def __init__(self, workspaces: list[ImportedTranslation], parent: QWidget) -> None:
        super().__init__(parent)
        panel = load_ui("dialogs/ParadoxExportSettings.ui", self)
        self.layout_ids = ["language", "mixed"]
        self.folder_layout = require_child(panel, QComboBox, "comboFolderLayout")
        self.encoding_ids = ["utf8", "escaped"]
        self.eu4_encoding: QComboBox | None = None
        eu4_projects = [item.project for item in workspaces if item.project.game_id == "eu4"]
        encoding = require_child(panel, QComboBox, "comboEncoding")
        require_child(panel, QFormLayout, "layoutParadox").setRowVisible(encoding, bool(eu4_projects))
        if eu4_projects:
            if any(project.target_language.lower().replace("_", "-").split("-")[0]
                   in {"zh", "ja", "ko"} for project in eu4_projects):
                encoding.setCurrentIndex(1)
            self.eu4_encoding = encoding
        self.setLayout(panel.layout())
        panel.deleteLater()


class ParadoxExportSettings:
    def create_widget(self, workspaces: list[ImportedTranslation], parent: QWidget) -> QWidget:
        return ParadoxExportWidget(workspaces, parent)

    def read_settings(self, widget: QWidget) -> dict[str, object]:
        if not isinstance(widget, ParadoxExportWidget):
            raise ValueError("出力設定のウィジェットが不正です。")
        layout_index = widget.folder_layout.currentIndex()
        if layout_index < 0:
            raise ValueError("出力設定を選択してください。")
        encoding_index = 0 if widget.eu4_encoding is None else widget.eu4_encoding.currentIndex()
        if encoding_index < 0:
            raise ValueError("エンコード方式を選択してください。")
        return {"layout": widget.layout_ids[layout_index],
                "eu4_encoding": widget.encoding_ids[encoding_index]}
