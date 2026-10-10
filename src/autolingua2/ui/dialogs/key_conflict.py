from __future__ import annotations

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGroupBox, QLabel, QListWidget, QPlainTextEdit,
    QScrollArea, QVBoxLayout, QWidget,
)

from autolingua2.ir.key_conflict import KeyConflict
from autolingua2.ui.i18n import tr


class KeyConflictDialog(QDialog):
    def __init__(self, conflict: KeyConflict, parent: QWidget) -> None:
        super().__init__(parent)
        self.conflict = conflict
        self.setWindowTitle(tr("KeyConflictDialog", "読み込み時のキー競合"))
        self.resize(740, 760)
        layout = QVBoxLayout(self)
        heading = QLabel(tr("KeyConflictDialog", "競合キー：{key}　　{position} / {total}件").format(
            key=conflict.key, position=conflict.position, total=conflict.total))
        layout.addWidget(heading)
        content = QWidget()
        sections = QVBoxLayout(content)
        if not any(side.role == "source" for side in conflict.sides):
            sections.addWidget(QLabel(tr("KeyConflictDialog", "原文なし")))
        self.lists: list[QListWidget] = []
        self.previews: list[QPlainTextEdit] = []
        for index, side in enumerate(conflict.sides):
            name = QLocale(side.language_code.replace("-", "_")).nativeLanguageName() or side.language_code
            role = tr("KeyConflictDialog", "原文候補" if side.role == "source" else "既存訳候補")
            group = QGroupBox(f"{role}［{name} / {side.language_code}］")
            group_layout = QVBoxLayout(group)
            candidates = QListWidget()
            candidates.setMinimumHeight(85)
            candidates.setMaximumHeight(135)
            for candidate in side.candidates:
                text = tr("KeyConflictDialog", "{path}：{line}行目").format(
                    path=candidate.file.path, line=candidate.entry.line_number)
                candidates.addItem(text)
            group_layout.addWidget(candidates)
            preview = QPlainTextEdit()
            preview.setReadOnly(True)
            preview.setMinimumHeight(90)
            preview.setMaximumHeight(160)
            group_layout.addWidget(QLabel(tr("KeyConflictDialog", "選択中の全文")))
            group_layout.addWidget(preview)
            self.lists.append(candidates)
            self.previews.append(preview)
            candidates.currentRowChanged.connect(lambda row, section=index: self._select(section, row))
            candidates.setCurrentRow(0)
            candidates.setEnabled(len(side.candidates) > 1)
            sections.addWidget(group)
        if not any(side.role == "translation" for side in conflict.sides):
            sections.addWidget(QLabel(tr("KeyConflictDialog", "既存訳なし")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        changes = []
        for side in conflict.sides:
            if len(side.candidates) > 1:
                role = tr("KeyConflictDialog", "原文" if side.role == "source" else "既存訳")
                changes.append(tr("KeyConflictDialog", "{role}［{language}］：選択した1行を残し、他の競合{count}行を削除").format(
                    role=role, language=side.language_code, count=len(side.candidates) - 1))
        summary = QLabel(tr("KeyConflictDialog", "修正内容：") + "\n" + "\n".join(changes))
        summary.setWordWrap(True)
        layout.addWidget(summary)
        notice = QLabel(tr("KeyConflictDialog", "採用すると元ファイルを直ちに修正します。途中で中止しても確定済みの修正は保持されます。"))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton(tr("KeyConflictDialog", "採用して元ファイルを修正"),
                                             QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("KeyConflictDialog", "読み込みを中止"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select(self, index: int, row: int) -> None:
        candidates = self.conflict.sides[index].candidates
        self.previews[index].setPlainText(candidates[row].entry.text if 0 <= row < len(candidates) else "")

    def selection(self) -> tuple[int, ...]:
        return tuple(candidates.currentRow() for candidates in self.lists)
