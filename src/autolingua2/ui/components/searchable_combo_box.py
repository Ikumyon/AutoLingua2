from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter


def enable_combo_search(combo: QComboBox) -> None:
    """Use an existing combo's editor to search without adding new items."""
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    editor = combo.lineEdit()
    if editor is None:
        raise RuntimeError("Editable combo box has no line editor")

    completer = QCompleter(combo.model(), combo)
    completer.setCompletionColumn(combo.modelColumn())
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)

    def search(text: str) -> None:
        completer.setCompletionPrefix(text)
        completer.complete()

    def restore_selection() -> None:
        # Search text is temporary; only an existing item can be selected.
        combo.setEditText(combo.itemText(combo.currentIndex()))

    editor.textEdited.connect(search)
    editor.editingFinished.connect(restore_selection)
