from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QHeaderView, QLineEdit, QMessageBox, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QWidget

from autolingua2.services.workspaces import WorkspaceService
from autolingua2.ui.dialogs.base import SimpleDialogController, require_child
from autolingua2.ui.i18n import tr
from autolingua2.ui.language_names import workspace_language_name


class WorkspaceLanguageDialog(SimpleDialogController):
    def __init__(self, service: WorkspaceService, changed: Callable[[str | None], None], parent: QWidget) -> None:
        super().__init__("WorkspaceLanguageDialog.ui", parent)
        self.service = service
        self.changed = changed
        self.tabs = require_child(self.dialog, QTabWidget, "tabs")
        self.search = require_child(self.dialog, QLineEdit, "editSearch")
        self.name = require_child(self.dialog, QLineEdit, "editName")
        self.code = require_child(self.dialog, QLineEdit, "editCode")
        self.table = require_child(self.dialog, QTableWidget, "tableLanguages")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.search.textChanged.connect(self.refresh)
        require_child(self.dialog, QPushButton, "buttonRegister").clicked.connect(self.register)
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text().casefold()
        languages = sorted(((language, workspace_language_name(self.service, language.code))
                            for language in self.service.languages.values()),
                           key=lambda item: (item[1], item[0].code))
        languages = [(language, name) for language, name in languages
                     if query in name.casefold() or query in language.name.casefold()
                     or query in language.code.casefold()]
        self.table.setRowCount(len(languages))
        for row, (language, name) in enumerate(languages):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(language.code))
            added = language.code in self.service.workspaces
            button = QPushButton(tr("WorkspaceLanguageDialog", "追加済み · 削除" if added else "追加"))
            button.clicked.connect(lambda checked=False, code=language.code: self.toggle(code))
            self.table.setCellWidget(row, 2, button)

    def toggle(self, code: str) -> None:
        if code in self.service.workspaces:
            name = workspace_language_name(self.service, code)
            answer = QMessageBox.question(self.dialog, tr("WorkspaceLanguageDialog", "ワークスペースを削除"),
                f"{name} / {code}\n" + tr("WorkspaceLanguageDialog", "この言語の訳文と翻訳状態を削除しますか？共通の原文は残ります。"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.service.remove(code)
            self.changed(None)
        else:
            self.service.add(code)
            self.changed(code)
        self.refresh()

    def register(self) -> None:
        try:
            code = self.service.register(self.name.text(), self.code.text())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.dialog, tr("WorkspaceLanguageDialog", "登録できません"), str(exc))
            return
        self.service.add(code)
        self.changed(code)
        self.name.clear()
        self.code.clear()
        self.search.clear()
        self.tabs.setCurrentIndex(0)
        self.refresh()
