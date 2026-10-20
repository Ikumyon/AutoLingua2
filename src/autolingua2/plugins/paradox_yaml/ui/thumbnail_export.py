from pathlib import Path
from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QFileDialog, QLineEdit, QPushButton, QWidget

from autolingua2.plugins.api import ExportFile
from autolingua2.ui.ui_loader import load_ui, require_child
from ..parser.thumbnail_export import descriptor_path, update_picture


class ParadoxThumbnailExport:
    def __init__(self, read_text: Callable[[Path], tuple[str, str]]) -> None:
        self.read_text = read_text

    def create_widget(self, directory: Path, parent: QWidget) -> QWidget:
        widget = load_ui("dialogs/ParadoxThumbnailExportSettings.ui", parent)
        enabled = require_child(widget, QCheckBox, "checkUpdatePicture")
        path = require_child(widget, QLineEdit, "editDescriptorPath")
        browse = require_child(widget, QPushButton, "buttonBrowseDescriptor")
        enabled.toggled.connect(path.setEnabled)
        enabled.toggled.connect(browse.setEnabled)

        def select() -> None:
            selected, _ = QFileDialog.getOpenFileName(widget, ".modファイルを選択", str(directory), "MOD (*.mod)")
            if selected:
                path.setText(selected)

        browse.clicked.connect(select)
        return widget

    def read_settings(self, widget: QWidget) -> dict[str, object]:
        enabled = widget.findChild(QCheckBox, "checkUpdatePicture")
        path = widget.findChild(QLineEdit, "editDescriptorPath")
        if enabled is None or path is None:
            raise ValueError("Paradox画像出力設定が見つかりません。")
        return {"update_picture": enabled.isChecked(), "descriptor": path.text()}

    def plan(self, destination: Path, settings: dict[str, object]) -> list[ExportFile]:
        if not settings.get("update_picture"):
            return []
        path = descriptor_path(destination, settings.get("descriptor"))
        text, encoding = self.read_text(path)
        content = update_picture(text, destination.name).encode(encoding)
        return [ExportFile(Path(path.name), content)]
