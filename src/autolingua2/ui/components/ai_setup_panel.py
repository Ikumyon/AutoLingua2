from __future__ import annotations

from copy import deepcopy

from PySide6.QtWidgets import QWidget

from autolingua2.plugins.api import AiSetupCallbacks, AiSetupOption, AiSetupPanel, AiSetupValues


def create_plugin_panel(
    option: AiSetupOption, parent: QWidget, initial: AiSetupValues, callbacks: AiSetupCallbacks,
) -> AiSetupPanel:
    factory = option.create_panel
    if factory is None:
        raise ValueError("設定画面が登録されていません。")
    panel = factory(parent, deepcopy(initial), callbacks)
    if (not isinstance(panel, AiSetupPanel) or not isinstance(panel.widget, QWidget)
            or not isinstance(panel.ready, bool)):
        raise TypeError("設定画面の公開契約が不正です。")
    panel.widget.setParent(parent)
    return panel
