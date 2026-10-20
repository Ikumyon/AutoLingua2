"""UI settings panel for BMFont character list export."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QWidget

from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ui.resources.i18n import tr
from autolingua2.ui.ui_loader import load_ui, require_child


class BmFontExportWidget(QWidget):
    """Widget allowing user to choose between target (translation) and source text."""

    def __init__(self, workspaces: list[ImportedTranslation], parent: QWidget) -> None:
        super().__init__(parent)
        panel = load_ui("dialogs/BmFontExportSettings.ui", self)
        self.combo_target = require_child(panel, QComboBox, "comboTarget")
        self.setLayout(panel.layout())
        panel.deleteLater()
        self.combo_target.setItemData(0, "target")
        self.combo_target.setItemData(1, "source")


class BmFontExportSettingsPanel:
    """Panel adapter for ExportDialog settings protocol."""

    def create_widget(self, workspaces: list[ImportedTranslation], parent: QWidget) -> QWidget:
        return BmFontExportWidget(workspaces, parent)

    def read_settings(self, widget: QWidget) -> dict[str, object]:
        if not isinstance(widget, BmFontExportWidget):
            raise ValueError(tr("BmFontExport", "出力設定のウィジェットが不正です。"))
        target_mode = widget.combo_target.currentData()
        if target_mode not in {"target", "source"}:
            target_mode = "target"
        return {"target_mode": target_mode}
