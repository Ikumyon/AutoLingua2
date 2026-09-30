from typing import TypeVar

from PySide6.QtCore import QFile, QIODeviceBase, QObject
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QWidget

from autolingua2.infrastructure.filesystem import UI_DIR
from autolingua2.ui.i18n import tr


ChildType = TypeVar("ChildType", bound=QObject)


def require_child(parent: QObject, child_type: type[ChildType], name: str) -> ChildType:
    child = parent.findChild(child_type, name)
    if child is None:
        raise RuntimeError(f"UI部品が見つかりません: {name} ({child_type.__name__})")
    return child


def load_ui(name: str, parent: QWidget | None = None) -> QWidget:
    # Source and frozen distributions both use the packaged .ui resources.
    path = UI_DIR / name
    file = QFile(str(path))
    if not file.open(QIODeviceBase.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"UIファイルを開けません: {path}")
    try:
        loader = QUiLoader()
        loader.setLanguageChangeEnabled(True)
        widget = loader.load(file, parent)
    finally:
        file.close()

    if widget is None:
        raise RuntimeError(f"UIファイルを読み込めません: {path}")
    return widget


class SimpleDialogController:
    def __init__(self, ui_file: str, parent: QWidget | None = None) -> None:
        widget = load_ui(ui_file, parent)
        if not isinstance(widget, QDialog):
            raise TypeError(f"{ui_file} は QDialog ではありません")
        self.dialog = widget

    def exec(self) -> int:
        close_button = self.dialog.findChild(QPushButton, "buttonClose")
        if close_button is not None:
            close_button.clicked.connect(self.dialog.close)
        return self.dialog.exec()


def show_not_implemented(parent: QWidget, feature: str) -> None:
    QMessageBox.information(
        parent,
        tr("Common", "未実装"),
        tr("Common", "{feature} は後続の実装で追加します。").format(feature=feature),
    )
