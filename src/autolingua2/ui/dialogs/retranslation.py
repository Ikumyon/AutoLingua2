from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton, QWidget

from autolingua2.ui.dialogs.base import SimpleDialogController, require_child
from autolingua2.ui.resources.i18n import tr


class RetranslationDialog(SimpleDialogController):
    def __init__(self, labels: list[str], untranslated_count: int, parent: QWidget) -> None:
        super().__init__("dialogs/RetranslationDialog.ui", parent)
        self.untranslated_only = False
        self.instructions = require_child(self.dialog, QPlainTextEdit, "editInstructions")
        multiple = len(labels) > 1
        self.dialog.setWindowTitle(tr("RetranslationDialog", "選択項目の再翻訳") if multiple else
                                   tr("RetranslationDialog", "再翻訳"))
        summary = (tr("RetranslationDialog", "対象：{total}件（翻訳済み{translated}件／未翻訳{untranslated}件）").format(
            total=len(labels), translated=len(labels) - untranslated_count, untranslated=untranslated_count,
        ) if multiple else tr("RetranslationDialog", "対象：{label}").format(label=labels[0]))
        require_child(self.dialog, QLabel, "labelTargets").setText(summary)
        require_child(self.dialog, QLabel, "labelMultiple").setVisible(multiple)
        translate = require_child(self.dialog, QPushButton, "buttonTranslate")
        translate.setText(tr("RetranslationDialog", "すべて再翻訳") if multiple else
                          tr("RetranslationDialog", "再翻訳する"))
        translate.clicked.connect(self.dialog.accept)
        untranslated = require_child(self.dialog, QPushButton, "buttonUntranslated")
        untranslated.setVisible(0 < untranslated_count < len(labels))
        untranslated.setText(tr("RetranslationDialog", "未翻訳のみ翻訳 ({count}件)").format(count=untranslated_count))
        untranslated.clicked.connect(self._translate_untranslated)
        if 0 < untranslated_count < len(labels):
            untranslated.setDefault(True)
        require_child(self.dialog, QPushButton, "buttonCancel").clicked.connect(self.dialog.reject)
        self.instructions.setFocus()

    def _translate_untranslated(self) -> None:
        self.untranslated_only = True
        self.dialog.accept()

    def additional_instructions(self) -> str:
        return self.instructions.toPlainText().strip()
