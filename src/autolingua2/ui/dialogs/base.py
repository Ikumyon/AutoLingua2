from typing import TypeVar

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QWidget

from autolingua2.ui.i18n import tr
from autolingua2.ui.ui_loader import load_ui as load_ui


ChildType = TypeVar("ChildType", bound=QObject)


def require_child(parent: QObject, child_type: type[ChildType], name: str) -> ChildType:
    child = parent.findChild(child_type, name)
    if child is None:
        raise RuntimeError(f"UI部品が見つかりません: {name} ({child_type.__name__})")
    return child


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
