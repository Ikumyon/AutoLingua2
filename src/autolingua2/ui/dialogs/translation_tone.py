from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from autolingua2.ir.tone import ToneItem
from autolingua2.ui.i18n import tr


class TranslationToneDialog(QDialog):
    def __init__(self, source: str, target: str, tones: Sequence[ToneItem], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("TranslationToneDialog", "訳文の確定"))
        self.resize(600, 480)
        layout = QVBoxLayout(self)
        for label, text in (("原文", source), ("訳文", target)):
            layout.addWidget(QLabel(tr("TranslationToneDialog", label)))
            preview = QPlainTextEdit(text)
            preview.setReadOnly(True)
            layout.addWidget(preview)
        layout.addWidget(QLabel(tr("TranslationToneDialog", "口調を指定してください。")))
        self.choice = QComboBox()
        self.choice.addItem(tr("TranslationToneDialog", "口調を選択…"), None)
        for tone in tones:
            self.choice.addItem(tone.name, tone)
        layout.addWidget(self.choice)
        self.description = QLabel()
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        buttons = QDialogButtonBox()
        self.confirm_button = buttons.addButton(tr("TranslationToneDialog", "確定する"),
                                               QDialogButtonBox.ButtonRole.AcceptRole)
        self.confirm_button.setEnabled(False)
        buttons.addButton(tr("TranslationToneDialog", "編集に戻る"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.choice.currentIndexChanged.connect(self._changed)

    def selected_tone(self) -> ToneItem | None:
        value = self.choice.currentData()
        return value if isinstance(value, ToneItem) else None

    def _changed(self, _index: int) -> None:
        tone = self.selected_tone()
        self.description.setText(tone.prompt if tone is not None else "")
        self.confirm_button.setEnabled(tone is not None)
