from __future__ import annotations

from importlib import import_module
from pathlib import PurePosixPath
import sys
from typing import Protocol, TypeVar, runtime_checkable

from PySide6.QtCore import QEvent, QFile, QIODeviceBase, QObject
from PySide6.QtWidgets import QWidget

from autolingua2.infrastructure.filesystem import UI_DIR


ChildType = TypeVar("ChildType", bound=QObject)


def require_child(parent: QObject, child_type: type[ChildType], name: str) -> ChildType:
    child = parent.findChild(child_type, name)
    if child is None:
        raise RuntimeError(f"UI部品が見つかりません: {name} ({child_type.__name__})")
    return child


def _initialize_search_bars(widget: QWidget) -> None:
    from autolingua2.ui.components.search_bar import SearchBar

    if isinstance(widget, SearchBar):
        widget.initialize_ui()
    for search_bar in widget.findChildren(SearchBar):
        search_bar.initialize_ui()


def _initialize_guide(widget: QWidget, name: str) -> None:
    from autolingua2.ui.guide import bind_guide

    bind_guide(widget, name)


@runtime_checkable
class UiForm(Protocol):
    def setupUi(self, widget: QWidget) -> None: ...

    def retranslateUi(self, widget: QWidget) -> None: ...


class _FormBinding(QObject):
    """生成フォームを画面とともに保持し、言語変更を反映する。"""

    def __init__(self, widget: QWidget, form: UiForm) -> None:
        super().__init__(widget)
        self._widget = widget
        self._form = form
        widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._widget and event.type() == QEvent.Type.LanguageChange:
            self._form.retranslateUi(self._widget)
        return super().eventFilter(watched, event)


def load_ui(name: str, parent: QWidget | None = None) -> QWidget:
    """ui/ からの相対パスを、開発時はXML、exeでは生成モジュールから読む。"""
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".ui":
        raise ValueError(f"UIの相対パスが不正です: {name}")

    if getattr(sys, "frozen", False):
        module_name = ".".join(("ui", *relative.with_suffix("").parts))
        module = import_module(module_name)
        root_class = getattr(module, "UI_ROOT_CLASS", None)
        if not isinstance(root_class, type) or not issubclass(root_class, QWidget):
            raise TypeError(f"UIのルート型が不正です: {module_name}")
        form_class = getattr(module, "UI_FORM_CLASS", None)
        if not isinstance(form_class, type):
            raise TypeError(f"UIのフォームクラスがありません: {module_name}")
        form = form_class()
        if not isinstance(form, UiForm):
            raise TypeError(f"UIのフォーム契約が不正です: {module_name}")
        widget = root_class(parent)
        form.setupUi(widget)
        _FormBinding(widget, form)
        _initialize_search_bars(widget)
        _initialize_guide(widget, name)
        return widget

    # カスタム部品もこの窓口を利用するため、開発用の登録は読み込み時に行う。
    from PySide6.QtUiTools import QUiLoader

    from autolingua2.ui.components.chat_composer import ChatComposer, ChatReferenceTable
    from autolingua2.ui.components.chat_web_view import ChatWebView
    from autolingua2.ui.components.combo_menu_button import ComboMenuButton
    from autolingua2.ui.components.drop_zone import DropZone
    from autolingua2.ui.components.script_editor import ScriptEditor
    from autolingua2.ui.components.search_bar import SearchBar

    path = UI_DIR.joinpath(*relative.parts)
    file = QFile(str(path))
    if not file.open(QIODeviceBase.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"UIファイルを開けません: {path}")
    try:
        loader = QUiLoader()
        for custom_widget in (ComboMenuButton, ChatComposer, ChatReferenceTable, ChatWebView, DropZone, ScriptEditor, SearchBar):
            loader.registerCustomWidget(custom_widget)
        loader.setLanguageChangeEnabled(True)
        widget = loader.load(file, parent)
    finally:
        file.close()
    if widget is None:
        raise RuntimeError(f"UIファイルを読み込めません: {path}")
    _initialize_search_bars(widget)
    _initialize_guide(widget, name)
    return widget
