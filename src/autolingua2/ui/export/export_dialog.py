"""Translation export settings and workspace selection."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QMessageBox,
    QToolButton, QVBoxLayout, QWidget,
)

from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.state import UnitState
from autolingua2.plugins.api import ExportSettingsPanel
from autolingua2.services.exporting.bmfont_exporter import BmFontCharListExporter
from autolingua2.services.exporting.export_contract import TranslationExporter
from autolingua2.ui.export.bmfont_export_panel import BmFontExportSettingsPanel
from autolingua2.ui.export.destination_dialog import ExportDestinationDialog
from autolingua2.ui.dialogs.base import require_child
from autolingua2.ui.resources.i18n import tr

class ExportDialog(ExportDestinationDialog):
    def __init__(self, workspaces: list[ImportedTranslation], exporters: Mapping[str, TranslationExporter],
                 panels: Mapping[str, ExportSettingsPanel], directory: Path,
                 preferred_plugin: str, parent: QWidget) -> None:
        super().__init__(directory, parent)
        require_child(self.dialog, QWidget, "sectionTranslationStates").show()
        merged_exporters: dict[str, TranslationExporter] = dict(exporters)
        merged_panels: dict[str, ExportSettingsPanel] = dict(panels)
        builtin_key = "builtin:bmfont_chars"
        if builtin_key not in merged_exporters:
            merged_exporters[builtin_key] = BmFontCharListExporter()
        if builtin_key not in merged_panels:
            merged_panels[builtin_key] = BmFontExportSettingsPanel()

        self._workspaces = workspaces
        self._exporters = merged_exporters
        self._panels = merged_panels
        self._keys = list(merged_exporters)
        self._panel: ExportSettingsPanel | None = None
        self._widget: QWidget | None = None
        self.exporter: TranslationExporter | None = None
        self.settings: dict[str, object] = {}
        self.destination: Path | None = None
        self._formats = require_child(self.dialog, QComboBox, "comboFormat")
        self._settings_group = require_child(self.dialog, QGroupBox, "groupSettings")
        self._settings_layout = require_child(self.dialog, QVBoxLayout, "layoutSettings")
        self._settings_section = require_child(self.dialog, QWidget, "sectionSettings")
        self._settings_toggle = require_child(self.dialog, QToolButton, "buttonSettings")
        states_widget = require_child(self.dialog, QWidget, "widgetTranslationStates")
        states_toggle = require_child(self.dialog, QToolButton, "buttonTranslationStates")
        self._state_checkboxes = {
            state: require_child(states_widget, QCheckBox, f"checkState_{state.value}")
            for state in UnitState
        }
        for toggle, content in ((states_toggle, states_widget), (self._settings_toggle, self._settings_group)):
            toggle.toggled.connect(content.setVisible)
            toggle.toggled.connect(lambda expanded, button=toggle: button.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
        for exporter in self._exporters.values():
            self._formats.addItem(exporter.name)
        preferred = next((index for index, key in enumerate(self._keys)
                          if key.startswith(preferred_plugin + ":")), 0)
        self._formats.setCurrentIndex(preferred)
        self._formats.currentIndexChanged.connect(self._format_changed)
        self._format_changed()
        self._navigate(self._current)

    def _format_changed(self) -> None:
        if self._widget is not None:
            self._settings_layout.removeWidget(self._widget)
            self._widget.deleteLater()
            self._widget = None
        index = self._formats.currentIndex()
        self.dialog.setProperty("guidePage", {"paradox_yaml:yaml": "export-yaml",
            "paratranz:json": "export-paratranz", "builtin:bmfont_chars": "export-bmfont"}.get(
                self._keys[index] if index >= 0 else "", "export"))
        self._panel = self._panels.get(self._keys[index]) if index >= 0 else None
        self._settings_section.setVisible(self._panel is not None)
        self._settings_group.setVisible(self._panel is not None and self._settings_toggle.isChecked())
        if self._panel is not None:
            try:
                self._widget = self._panel.create_widget(self._workspaces, self._settings_group)
                self._settings_layout.addWidget(self._widget)
            except Exception as exc:
                QMessageBox.warning(self.dialog, tr("ExportDialog", "出力設定エラー"), str(exc))

    def accept(self) -> None:
        index = self._formats.currentIndex()
        if index < 0:
            QMessageBox.warning(self.dialog, tr("ExportDialog", "出力エラー"),
                                tr("ExportDialog", "出力方式を選択してください。"))
            return
        try:
            destination = self.output_path()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.dialog, tr("ExportDialog", "出力エラー"),
                                str(exc))
            return
        try:
            if self._panel is None:
                settings: dict[str, object] = {}
            else:
                if self._widget is None:
                    raise ValueError(tr("ExportDialog", "出力設定を読み込めません。"))
                settings = self._panel.read_settings(self._widget)
        except Exception as exc:
            QMessageBox.warning(self.dialog, tr("ExportDialog", "出力設定エラー"), str(exc))
            return
        self.exporter = self._exporters[self._keys[index]]
        self.settings = {**settings, "translation_states": [
            state.value for state, checkbox in self._state_checkboxes.items() if checkbox.isChecked()
        ]}
        self.destination = destination.resolve()
        self.dialog.accept()
