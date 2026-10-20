from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFormLayout, QGroupBox,
    QMessageBox, QPushButton, QSpinBox, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from autolingua2.plugins.api import ThumbnailExportPanel
from autolingua2.services.exporting.thumbnail_export import ThumbnailExportSettings
from autolingua2.ui.export.destination_dialog import ExportDestinationDialog, OutputMode
from autolingua2.ui.ui_loader import load_ui, require_child
from autolingua2.ui.resources.i18n import tr


class ThumbnailExportDialog(ExportDestinationDialog):
    def __init__(self, directory: Path, parent: QWidget,
                 extension: ThumbnailExportPanel | None = None) -> None:
        super().__init__(directory, parent, mode=OutputMode.FILE, filename="thumbnail")
        self.dialog.setProperty("guidePage", "thumbnail")
        self.dialog.setProperty("guideAnchor", "export-image")
        self.dialog.setWindowTitle(tr("ThumbnailExportDialog", "サムネイルを出力"))
        self.extension = extension
        self.destination: Path | None = None
        self.settings = ThumbnailExportSettings()
        self.plugin_settings: dict[str, object] = {}
        group = require_child(self.dialog, QGroupBox, "groupSettings")
        group.show()
        require_child(self.dialog, QToolButton, "buttonSettings").hide()
        layout = require_child(self.dialog, QVBoxLayout, "layoutSettings")
        panel = load_ui("dialogs/ThumbnailExportSettings.ui", group)
        layout.addWidget(panel)
        self.formats = require_child(panel, QComboBox, "comboImageFormat")
        old_formats = require_child(self.dialog, QComboBox, "comboFileFormat")
        panel.layout().removeWidget(self.formats)
        output_layout = require_child(self.dialog, QFormLayout, "layoutFileOutput")
        output_layout.replaceWidget(old_formats, self.formats)
        old_formats.hide()
        old_formats.deleteLater()
        self.pages = require_child(panel, QStackedWidget, "stackImageSettings")
        self.compression = require_child(panel, QSpinBox, "spinCompression")
        self.png_optimize = require_child(panel, QCheckBox, "checkPngOptimize")
        self.png_optimize.toggled.connect(lambda enabled: self.compression.setEnabled(not enabled))
        self.quality = require_child(panel, QSpinBox, "spinQuality")
        self.subsampling = require_child(panel, QComboBox, "comboSubsampling")
        self.progressive = require_child(panel, QCheckBox, "checkProgressive")
        self.jpeg_optimize = require_child(panel, QCheckBox, "checkJpegOptimize")
        self.background_button = require_child(panel, QPushButton, "buttonBackground")
        self.background = QColor(self.background_button.text())
        self.background_button.clicked.connect(self.choose_background)
        self.formats.currentIndexChanged.connect(self.pages.setCurrentIndex)
        self.metadata = require_child(panel, QCheckBox, "checkMetadata")
        self.plugin_widget = extension.create_widget(directory, group) if extension is not None else None
        if self.plugin_widget is not None:
            layout.addWidget(self.plugin_widget)

    def choose_background(self) -> None:
        color = QColorDialog.getColor(self.background, self.dialog)
        if color.isValid():
            self.background = color
            self.background_button.setText(color.name())

    def accept(self) -> None:
        try:
            suffix = ".png" if self.formats.currentIndex() == 0 else ".jpg"
            destination = self.output_path(suffix=suffix, replace_suffixes=(".png", ".jpg", ".jpeg"))
            if self.extension is not None:
                if self.plugin_widget is None:
                    raise ValueError("プラグインの出力設定が見つかりません。")
                self.plugin_settings = self.extension.read_settings(self.plugin_widget)
                self.extension.plan(destination, self.plugin_settings)
            if not self.confirm_overwrite(destination):
                return
            self.destination = destination
            self.settings = ThumbnailExportSettings(
                format="PNG" if suffix == ".png" else "JPEG", metadata=self.metadata.isChecked(),
                compression=self.compression.value(),
                optimize=self.png_optimize.isChecked() if suffix == ".png" else self.jpeg_optimize.isChecked(),
                quality=self.quality.value(), subsampling=self.subsampling.currentIndex(),
                progressive=self.progressive.isChecked(), background=self.background.name())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.dialog, "サムネイル出力", str(exc))
            return
        self.dialog.accept()
