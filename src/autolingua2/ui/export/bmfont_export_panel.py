"""UI settings panel for BMFont character list export."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ui.resources.i18n import tr


class BmFontExportWidget(QWidget):
    """Widget allowing user to choose between target (translation) and source text."""

    def __init__(self, workspaces: list[ImportedTranslation], parent: QWidget) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        self.combo_target = QComboBox(self)
        self.combo_target.addItem(tr("BmFontExport", "訳文（翻訳）"), "target")
        self.combo_target.addItem(tr("BmFontExport", "原文"), "source")
        layout.addRow(tr("BmFontExport", "対象テキスト："), self.combo_target)


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
