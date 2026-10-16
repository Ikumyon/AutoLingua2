from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, QPoint, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemDelegate, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QHeaderView, QLabel, QLineEdit, QListWidget,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QTableWidgetSelectionRange, QTreeWidget, QTreeWidgetItem, QWidget,
)

from autolingua2.extensions import ExtensionEntrance
from autolingua2.ir.glossary import (
    DirectedTerm, Glossary, GlossaryTerm, TermSide, PARTS_OF_SPEECH,
    edited_term, glossary_chain, orient_term,
)
from autolingua2.ir.text_search import SearchSyntaxError, TextSearch
from autolingua2.services.settings.glossary_store import GlossaryStore
from autolingua2.ui.components.drop_zone import DropZone
from autolingua2.ui.components.searchable_combo_box import enable_combo_search
from autolingua2.ui.resources.i18n import tr
from .base import SimpleDialogController, require_child
from .glossary_io import GlossaryExportDialog, GlossaryImportDialog


ID_ROLE = Qt.ItemDataRole.UserRole
DRAFT_ROLE = Qt.ItemDataRole.UserRole + 1
STORAGE_ERRORS = (OSError, sqlite3.Error, ValueError)


class GlossaryNameDelegate(QStyledItemDelegate):
    """Tree names commit on Enter/focus loss; Esc removes only unsaved drafts."""

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)
        self.tree = tree

    def setModelData(self, editor: QWidget, model: QAbstractItemModel,
                     index: QModelIndex | QPersistentModelIndex) -> None:
        if isinstance(editor, QLineEdit):
            value = editor.text().strip()
            unchanged = model.data(index, Qt.ItemDataRole.EditRole) == value
            model.setData(index, value, Qt.ItemDataRole.EditRole)
            if unchanged:
                item = self.tree.itemFromIndex(model.index(index.row(), index.column(), index.parent()))
                if item is not None:
                    self.tree.itemChanged.emit(item, 0)


class GlossaryTermDialog(SimpleDialogController):
    def __init__(self, store: GlossaryStore, term: DirectedTerm, glossary_name: str,
                 inherited: bool, parent: QWidget) -> None:
        super().__init__("dialogs/GlossaryTermDialog.ui", parent)
        self.store = store
        self.term = term
        self.part = require_child(self.dialog, QComboBox, "comboTermPart")
        self.source = require_child(self.dialog, QLineEdit, "editTermSource")
        self.translation = require_child(self.dialog, QLineEdit, "editTermTranslation")
        self.variant = require_child(self.dialog, QLineEdit, "editTermVariant")
        self.variants = require_child(self.dialog, QListWidget, "listTermVariants")
        self.memo = require_child(self.dialog, QPlainTextEdit, "editTermMemo")
        self.case_sensitive = require_child(self.dialog, QCheckBox, "checkTermCaseSensitive")
        self.target_variant = require_child(self.dialog, QLineEdit, "editTargetVariant")
        self.target_variants = require_child(self.dialog, QListWidget, "listTargetVariants")
        self.target_sensitive = require_child(self.dialog, QCheckBox, "checkTargetCaseSensitive")
        self.target_variants.addItems(list(term.target_variants))
        self.target_sensitive.setChecked(term.target_case_sensitive)
        self.target_variant.returnPressed.connect(self._add_target_variant)
        require_child(self.dialog, QPushButton, "buttonAddTargetVariant").clicked.connect(self._add_target_variant)
        require_child(self.dialog, QPushButton, "buttonRemoveTargetVariant").clicked.connect(self._remove_target_variant)
        require_child(self.dialog, QLabel, "labelSource").setText(tr("Glossary", "原文：") + term.source_language)
        require_child(self.dialog, QLabel, "labelTranslation").setText(tr("Glossary", "訳：") + term.target_language)
        self.part.addItems([tr("Glossary", part) for part in PARTS_OF_SPEECH])
        self.part.setCurrentIndex(PARTS_OF_SPEECH.index(term.part_of_speech)
                                  if term.part_of_speech in PARTS_OF_SPEECH else -1)
        self.source.setText(term.source)
        self.translation.setText(term.translation)
        self.variants.addItems(list(term.variants))
        self.memo.setPlainText(term.memo)
        self.case_sensitive.setChecked(term.case_sensitive)
        scope = tr("Glossary", "この用語集で上書き：") if inherited else tr("Glossary", "保存先：")
        require_child(self.dialog, QLabel, "labelTermScope").setText(scope + glossary_name)
        self.variant.returnPressed.connect(self._add_variant)
        require_child(self.dialog, QPushButton, "buttonAddVariant").clicked.connect(self._add_variant)
        require_child(self.dialog, QPushButton, "buttonRemoveVariant").clicked.connect(self._remove_variant)
        box = require_child(self.dialog, QDialogButtonBox, "buttonBox")
        box.accepted.connect(self._save)
        box.rejected.connect(self.dialog.reject)
        for button in self.dialog.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.source.setFocus()

    def _add_variant(self) -> None:
        value = self.variant.text().strip()
        if value and not self.variants.findItems(value, Qt.MatchFlag.MatchExactly):
            self.variants.addItem(value)
        self.variant.clear()
        self.variant.setFocus()

    def _remove_variant(self) -> None:
        row = self.variants.currentRow()
        if row >= 0:
            self.variants.takeItem(row)

    def _add_target_variant(self) -> None:
        value = self.target_variant.text().strip()
        if value and not self.target_variants.findItems(value, Qt.MatchFlag.MatchExactly):
            self.target_variants.addItem(value)
        self.target_variant.clear()

    def _remove_target_variant(self) -> None:
        row = self.target_variants.currentRow()
        if row >= 0:
            self.target_variants.takeItem(row)

    def _save(self) -> None:
        part_index = self.part.currentIndex()
        if part_index < 0:
            QMessageBox.warning(self.dialog, tr("Glossary", "用語を保存できません"),
                                tr("Glossary", "品詞を選択してください。"))
            self.part.setFocus()
            return
        # Include an unfinished variant instead of silently discarding it on Save.
        self._add_variant()
        self._add_target_variant()
        variants: list[str] = []
        for row in range(self.variants.count()):
            item = self.variants.item(row)
            if item is not None:
                variants.append(item.text())
        target_variants: list[str] = []
        for row in range(self.target_variants.count()):
            item = self.target_variants.item(row)
            if item is not None:
                target_variants.append(item.text())
        candidate = edited_term(self.term,
            TermSide(self.source.text(), tuple(variants), self.case_sensitive.isChecked()),
            TermSide(self.translation.text(), tuple(target_variants), self.target_sensitive.isChecked()),
            PARTS_OF_SPEECH[part_index], self.memo.toPlainText())
        try:
            self.store.save_term(candidate)
        except STORAGE_ERRORS as exc:
            QMessageBox.warning(self.dialog, tr("Glossary", "用語を保存できません"), str(exc))
            return
        self.dialog.accept()


class GlossaryPageController:
    def __init__(self, widget: QWidget, entrance: ExtensionEntrance,
                 languages: dict[str, str], adapter_id: str = "", game_id: str = "",
                 glossary_id: str = "", source_language: str = "", target_language: str = "") -> None:
        self.widget = widget
        self.store = GlossaryStore()
        self.glossary_formats = entrance.plugins.glossary_formats
        self.glossaries: list[Glossary] = []
        self.rows: list[DirectedTerm] = []
        self.language_names = languages
        self.games = require_child(widget, QComboBox, "comboGlossaryGame")
        self.tree = require_child(widget, QTreeWidget, "treeGlossaries")
        self.tree_search = require_child(widget, QLineEdit, "editGlossarySearch")
        self.table = require_child(widget, QTableWidget, "tableGlossaryTerms")
        self.term_search = require_child(widget, QLineEdit, "editTermSearch")
        self.search_error = require_child(widget, QLabel, "labelTermSearchError")
        self.search_error.hide()
        self.source_language = require_child(widget, QComboBox, "comboGlossarySourceLanguage")
        self.target_language = require_child(widget, QComboBox, "comboGlossaryTargetLanguage")
        self.swap_languages = require_child(widget, QPushButton, "buttonSwapGlossaryLanguages")
        self.swap_languages.clicked.connect(self._swap_languages)
        self.name = require_child(widget, QLineEdit, "editGlossaryName")
        self.parent = require_child(widget, QLabel, "labelGlossaryParent")
        self.parent.setTextFormat(Qt.TextFormat.PlainText)
        self.add_glossary = require_child(widget, QPushButton, "buttonAddGlossary")
        self.delete_glossary = require_child(widget, QPushButton, "buttonDeleteGlossary")
        self.export_glossary = require_child(widget, QPushButton, "buttonExportGlossary")
        self.export_glossary.clicked.connect(self._export_glossary)
        self.add_term = require_child(widget, QPushButton, "buttonAddTerm")
        self.edit_term = require_child(widget, QPushButton, "buttonEditTerm")
        self.delete_term = require_child(widget, QPushButton, "buttonDeleteTerm")
        self.import_drop = require_child(widget, DropZone, "dropGlossaryImport")
        self.import_drop.allowed_extensions = {".json"}
        self.import_drop.allow_multiple = False
        self.import_drop.dialog_filter = "JSON (*.json)"
        self.import_drop.set_hint_text(tr("Glossary", "用語集JSONをドロップ（取り込み時に形式を選択）"))
        self.import_drop.add_button(tr("Glossary", "ファイルを選択"), self._select_import_file)
        self.import_drop.files_dropped.connect(self._import_paths)
        self.import_drop.multiple_files_rejected.connect(self._reject_multiple_import_files)
        splitter = require_child(widget, QSplitter, "splitterGlossary")
        splitter.setSizes([1, 3])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, 200)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.verticalHeader().hide()
        header.sectionResized.connect(lambda *_args: self._resize_rows())
        delegate = GlossaryNameDelegate(self.tree)
        self.tree.setItemDelegate(delegate)
        delegate.closeEditor.connect(self._name_editor_closed)
        for parser_id, parser in entrance.plugins.parsers.items():
            for game in parser.supported_games:
                self.games.addItem(f"{game.name} ({parser.name})", (parser_id, game.id, game.name))
        for combo, selected in (
            (self.source_language, source_language),
            (self.target_language, target_language),
        ):
            for code, label in sorted(languages.items(), key=lambda item: (item[1], item[0])):
                combo.addItem(f"{label} [{code}]", code)
            combo.setCurrentIndex(combo.findData(selected) if selected else -1)
            enable_combo_search(combo)
        selected_game = next((row for row in range(self.games.count())
                              if self.games.itemData(row)[:2] == (adapter_id, game_id)), 0)
        self.games.setCurrentIndex(selected_game)
        self.games.currentIndexChanged.connect(self._game_changed)
        self.tree.itemChanged.connect(self._name_changed)
        self.name.editingFinished.connect(self._save_name)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree_search.textChanged.connect(self._filter_tree)
        self.term_search.textChanged.connect(self._refresh_terms)
        self.source_language.currentIndexChanged.connect(lambda: self._language_changed(True))
        self.target_language.currentIndexChanged.connect(lambda: self._language_changed(False))
        self.add_glossary.clicked.connect(self._add_glossary)
        self.delete_glossary.clicked.connect(self._delete_glossary)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._glossary_menu)
        self.add_term.clicked.connect(lambda: self._open_term(False))
        self.edit_term.clicked.connect(lambda: self._open_term(True))
        self.delete_term.clicked.connect(self._delete_term)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self._open_term(True))
        self.table.itemSelectionChanged.connect(self._term_selection_changed)
        self._game_changed(glossary_id=glossary_id)

    def _error(self, exc: Exception) -> None:
        QMessageBox.warning(self.widget, tr("Glossary", "用語集の操作に失敗しました"), str(exc))

    def _selected_glossary(self) -> Glossary | None:
        item = self.tree.currentItem()
        if item is None or item.data(0, DRAFT_ROLE):
            return None
        return next((g for g in self.glossaries if g.id == item.data(0, ID_ROLE)), None)

    def _game_changed(self, _index: int = 0, *, glossary_id: str = "") -> None:
        data = self.games.currentData()
        with QSignalBlocker(self.tree):
            self.tree.clear()
        self.glossaries = []
        self._selection_changed()
        if data is None:
            return
        adapter_id, game_id, game_name = data
        try:
            root = self.store.ensure_root(adapter_id, game_id, game_name)
            self.glossaries = self.store.list_glossaries(adapter_id, game_id)
            for glossary in self.glossaries:
                glossary_chain(self.glossaries, glossary.id)
        except STORAGE_ERRORS as exc:
            self._error(exc)
            return
        items: dict[str, QTreeWidgetItem] = {}
        with QSignalBlocker(self.tree):
            for glossary in self.glossaries:
                item = QTreeWidgetItem([glossary.name])
                item.setData(0, ID_ROLE, glossary.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                items[glossary.id] = item
            for glossary in self.glossaries:
                if glossary.parent_id is None:
                    self.tree.addTopLevelItem(items[glossary.id])
                else:
                    items[glossary.parent_id].addChild(items[glossary.id])
            self.tree.expandAll()
            self.tree.setCurrentItem(items.get(glossary_id, items[root.id]))
        self._filter_tree()
        self._selection_changed()

    def _filter_tree(self, _text: str = "") -> None:
        query = self.tree_search.text().strip().casefold()
        by_id = {g.id: g for g in self.glossaries}
        visible: set[str] = set()
        for glossary in self.glossaries:
            if query in glossary.name.casefold():
                current: Glossary | None = glossary
                while current is not None and current.id not in visible:
                    visible.add(current.id)
                    current = by_id.get(current.parent_id) if current.parent_id is not None else None
        pending = [self.tree.topLevelItem(row) for row in range(self.tree.topLevelItemCount())]
        while pending:
            item = pending.pop()
            if item is None:
                continue
            item.setHidden(not item.data(0, DRAFT_ROLE) and item.data(0, ID_ROLE) not in visible)
            pending.extend(item.child(row) for row in range(item.childCount()))
        if query:
            self.tree.expandAll()

    def _add_glossary(self) -> None:
        parent = self.tree.currentItem()
        if parent is None or self._selected_glossary() is None:
            return
        self.tree_search.clear()
        with QSignalBlocker(self.tree):
            item = QTreeWidgetItem([tr("Glossary", "新しい用語集")])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(0, DRAFT_ROLE, True)
            parent.addChild(item)
            parent.setExpanded(True)
            self.tree.setCurrentItem(item)
        self._selection_changed()
        self.tree.editItem(item, 0)

    def _glossary_delete_reason(self, glossary: Glossary | None) -> str:
        if glossary is None:
            return tr("Glossary", "用語集を選択してください")
        if glossary.parent_id is None:
            return tr("Glossary", "ゲームの共通用語集は削除できません")
        if any(g.parent_id == glossary.id for g in self.glossaries):
            return tr("Glossary", "子用語集があるため削除できません")
        return ""

    def _term_add_reason(self, glossary: Glossary | None) -> str:
        if glossary is None:
            return tr("Glossary", "用語集を選択してください")
        if glossary_chain(self.glossaries, glossary.id)[0].languages is None:
            return tr("Glossary", "最上位の親で2言語を設定してください")
        return ""

    def _update_term_actions(self) -> None:
        glossary = self._selected_glossary()
        reason = self._term_add_reason(glossary)
        self.add_term.setEnabled(not reason)
        self.add_term.setToolTip(reason)
        import_reason = tr("Glossary", "用語集を選択してください") if glossary is None else ""
        self.import_drop.setEnabled(glossary is not None)
        self.import_drop.set_hint_text(import_reason or tr("Glossary", "用語集JSONをドロップ（取り込み時に形式を選択）"))
        self.import_drop.setToolTip(import_reason)

    def _reject_multiple_import_files(self) -> None:
        self._error(ValueError(tr("Glossary", "JSONファイルは1つずつ取り込んでください。")))

    def _select_import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.widget, tr("Glossary", "用語集JSONを取り込む"), "", "JSON (*.json)")
        if path:
            self._import_paths([Path(path)])

    def _import_paths(self, paths: list[Path]) -> None:
        if len(paths) != 1:
            self._reject_multiple_import_files()
            return
        glossary = self._selected_glossary()
        if glossary is None:
            self._error(ValueError(tr("Glossary", "用語集を選択してください")))
            return
        try:
            chain = glossary_chain(self.glossaries, glossary.id)
            destination = " / ".join(g.name for g in chain)
            dialog = GlossaryImportDialog(paths[0], destination, self.widget, self.glossary_formats,
                chain[0].languages, str(self.source_language.currentData() or ""))
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            document = dialog.document
            if document is None:
                raise ValueError(tr("Glossary", "取り込む用語集を確認してください。"))
            result = self.store.import_document(document, glossary.id, dialog.mode, combine=dialog.combine)
        except STORAGE_ERRORS as exc:
            self._error(exc)
            return
        self._game_changed(glossary_id=result.glossary_id)
        QMessageBox.information(
            self.widget, tr("Glossary", "取り込み完了"),
            tr("Glossary", "作成用語集：{created}件\n追加用語：{added}件\n更新用語：{updated}件").format(
                created=result.created, added=result.added, updated=result.updated))

    def _export_glossary(self) -> None:
        glossary = self._selected_glossary()
        if glossary is None:
            return
        try:
            terms = [term for item in self.glossaries for term in self.store.list_terms(item.id)]
            GlossaryExportDialog(self.glossaries, terms, glossary, self.widget,
                                 str(self.source_language.currentData() or ""), self.glossary_formats).exec()
        except STORAGE_ERRORS as exc:
            self._error(exc)

    def _sync_languages(self) -> None:
        glossary = self._selected_glossary()
        if glossary is None:
            self.swap_languages.setEnabled(False)
            return
        root = glossary_chain(self.glossaries, glossary.id)[0]
        source = str(self.source_language.currentData() or "")
        target = str(self.target_language.currentData() or "")
        if root.languages is None and glossary.id == root.id and source and target and source != target:
            try:
                self.store.set_root_languages(root.id, source, target)
            except STORAGE_ERRORS as exc:
                self._error(exc)
                return
            root = replace(root, languages=(source, target))
            self.glossaries = [root if g.id == root.id else g for g in self.glossaries]
        languages = root.languages
        choices = languages if languages is not None else tuple(self.language_names)
        if languages is not None:
            source = source if source in languages else languages[0]
            target = languages[1] if source == languages[0] else languages[0]
        for combo, value in ((self.source_language, source), (self.target_language, target)):
            with QSignalBlocker(combo):
                combo.clear()
                for code in choices:
                    combo.addItem(f"{self.language_names.get(code, code)} [{code}]", code)
                combo.setCurrentIndex(combo.findData(value))
            combo.setEnabled(languages is not None or glossary.id == root.id)
        self.swap_languages.setEnabled(languages is not None)
        self.table.setHorizontalHeaderLabels([
            tr("Glossary", "品詞"), tr("Glossary", "原文：") + source, tr("Glossary", "訳：") + target,
            tr("Glossary", "原文の他形態"), tr("Glossary", "訳の他形態"), tr("Glossary", "メモ")])

    def _language_changed(self, source_changed: bool) -> None:
        glossary = self._selected_glossary()
        if glossary is None:
            return
        languages = glossary_chain(self.glossaries, glossary.id)[0].languages
        if languages is not None:
            changed = self.source_language if source_changed else self.target_language
            other = self.target_language if source_changed else self.source_language
            opposite = languages[1] if changed.currentData() == languages[0] else languages[0]
            with QSignalBlocker(other):
                other.setCurrentIndex(other.findData(opposite))
        self._sync_languages()
        self._update_term_actions()
        self._refresh_terms()

    def _swap_languages(self) -> None:
        target = self.target_language.currentData()
        self.source_language.setCurrentIndex(self.source_language.findData(target))

    def _glossary_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        glossary = self._selected_glossary()
        menu = QMenu(self.tree)
        menu.setToolTipsVisible(True)
        rename = menu.addAction(tr("Glossary", "名前変更"))
        rename.setEnabled(glossary is not None)
        delete = menu.addAction(tr("Glossary", "削除"))
        reason = self._glossary_delete_reason(glossary)
        delete.setEnabled(not reason)
        delete.setToolTip(reason)
        action = menu.exec(self.tree.viewport().mapToGlobal(position))
        if action == rename:
            self.name.setFocus()
            self.name.selectAll()
        elif action == delete:
            self._delete_glossary()

    def _delete_glossary(self) -> None:
        glossary = self._selected_glossary()
        if glossary is None or self._glossary_delete_reason(glossary):
            return
        if QMessageBox.question(
            self.widget, tr("Glossary", "用語集を削除"),
            tr("Glossary", "この用語集と登録された用語を削除しますか？") + "\n" + glossary.name,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete_glossary(glossary.id)
        except STORAGE_ERRORS as exc:
            self._error(exc)
            return
        self._game_changed(glossary_id=glossary.parent_id or "")

    def _save_name(self) -> None:
        glossary = self._selected_glossary()
        item = self.tree.currentItem()
        if glossary is None or item is None:
            return
        name = self.name.text().strip()
        if name != glossary.name:
            item.setText(0, name)
        else:
            self.name.setText(glossary.name)

    def _name_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        try:
            if item.data(0, DRAFT_ROLE):
                parent = item.parent()
                if parent is None:
                    raise ValueError("親用語集を選択してください。")
                glossary = self.store.add_glossary(str(parent.data(0, ID_ROLE)), item.text(0))
                self.glossaries.append(glossary)
                with QSignalBlocker(self.tree):
                    item.setData(0, ID_ROLE, glossary.id)
                    item.setData(0, DRAFT_ROLE, False)
                    item.setText(0, glossary.name)
            else:
                glossary_id = str(item.data(0, ID_ROLE))
                self.store.rename_glossary(glossary_id, item.text(0))
                self.glossaries = [replace(g, name=item.text(0).strip()) if g.id == glossary_id else g
                                   for g in self.glossaries]
        except STORAGE_ERRORS as exc:
            self._error(exc)
            # Keep the unsaved input available for correction/retry.
            QTimer.singleShot(0, lambda: self.tree.editItem(item, 0))
            return
        self._filter_tree()
        self._selection_changed()

    def _name_editor_closed(self, _editor: QWidget, hint: QAbstractItemDelegate.EndEditHint) -> None:
        item = self.tree.currentItem()
        if hint == QAbstractItemDelegate.EndEditHint.RevertModelCache and item is not None and item.data(0, DRAFT_ROLE):
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)
                self.tree.setCurrentItem(parent)
            self._selection_changed()
        elif hint == QAbstractItemDelegate.EndEditHint.RevertModelCache and item is not None:
            glossary = next((g for g in self.glossaries if g.id == item.data(0, ID_ROLE)), None)
            if glossary is not None:
                with QSignalBlocker(self.tree):
                    item.setText(0, glossary.name)

    def _selection_changed(self, *_args: object) -> None:
        glossary = self._selected_glossary()
        self.add_glossary.setEnabled(glossary is not None)
        self.export_glossary.setEnabled(glossary is not None)
        reason = self._glossary_delete_reason(glossary)
        self.delete_glossary.setEnabled(not reason)
        self.delete_glossary.setToolTip(reason)
        self._sync_languages()
        self._update_term_actions()
        self.name.setEnabled(glossary is not None)
        self.name.setText(glossary.name if glossary is not None else "")
        if glossary is not None:
            chain = glossary_chain(self.glossaries, glossary.id)
            path = " → ".join(g.name for g in chain[:-1]) or tr("Glossary", "なし")
            self.parent.setText(tr("Glossary", "親：") + path)
        else:
            self.parent.setText(tr("Glossary", "親：なし"))
        self._refresh_terms()

    def _refresh_terms(self, *_args: object) -> None:
        self.search_error.hide()
        self.search_error.clear()
        glossary = self._selected_glossary()
        self.rows = []
        self.table.clearSpans()
        self.table.setRowCount(0)
        self._term_selection_changed()
        if glossary is None:
            return
        try:
            terms = self.store.effective_terms(self.glossaries, glossary.id,
                                               str(self.source_language.currentData() or ""),
                                               str(self.target_language.currentData() or ""))
        except STORAGE_ERRORS as exc:
            self._error(exc)
            return
        try:
            search = TextSearch(self.term_search.text(), fields=("source", "target", "variant", "memo"))
        except SearchSyntaxError as error:
            self.search_error.setText(tr("Glossary", "検索エラー：{error}").format(error=error))
            self.search_error.show()
            return
        terms = [term for term in terms if search.matches_fields({
            "source": (term.source,), "target": (term.translation,),
            "variant": (*term.variants, *term.target_variants), "memo": (term.memo,),
        })]
        by_id = {g.id: g for g in self.glossaries}
        for term in terms:
            start = len(self.rows)
            span = max(1, len(term.variants), len(term.target_variants))
            self.rows.extend([term] * span)
            self.table.setRowCount(len(self.rows))
            for offset in range(span):
                variant = term.variants[offset] if offset < len(term.variants) else ""
                target_variant = term.target_variants[offset] if offset < len(term.target_variants) else ""
                for column, text in enumerate((tr("Glossary", term.part_of_speech), term.source,
                                               term.translation, variant, target_variant, term.memo)):
                    if offset and column not in (3, 4):
                        continue
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    if term.glossary_id != glossary.id:
                        item.setForeground(self.table.palette().brush(QPalette.ColorRole.PlaceholderText))
                        item.setToolTip(tr("Glossary", "継承元：") + by_id[term.glossary_id].name)
                    self.table.setItem(start + offset, column, item)
            if span > 1:
                for column in (0, 1, 2, 5):
                    self.table.setSpan(start, column, span, 1)
        self._resize_rows()

    def _resize_rows(self) -> None:
        self.table.resizeRowsToContents()
        # Qt's automatic row sizing does not account for vertically merged cells.
        row = 0
        while row < len(self.rows):
            term = self.rows[row]
            span = max(1, len(term.variants), len(term.target_variants))
            required = 0
            for column in (0, 1, 2, 5):
                item = self.table.item(row, column)
                if item is None:
                    continue
                width = max(20, self.table.columnWidth(column) - 16)
                bounds = self.table.fontMetrics().boundingRect(
                    0, 0, width, 100000, Qt.TextFlag.TextWordWrap, item.text())
                required = max(required, bounds.height() + 16)
            available = sum(self.table.rowHeight(row + offset) for offset in range(span))
            if required > available:
                extra = (required - available + span - 1) // span
                for offset in range(span):
                    self.table.setRowHeight(row + offset, self.table.rowHeight(row + offset) + extra)
            row += span

    def _selected_term(self) -> DirectedTerm | None:
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def _term_selection_changed(self) -> None:
        term, glossary = self._selected_term(), self._selected_glossary()
        self.edit_term.setEnabled(term is not None)
        self.delete_term.setEnabled(term is not None and glossary is not None and term.glossary_id == glossary.id)
        if term is not None:
            start = self.rows.index(term)
            end = start + max(1, len(term.variants), len(term.target_variants)) - 1
            with QSignalBlocker(self.table):
                self.table.clearSelection()
                self.table.setRangeSelected(QTableWidgetSelectionRange(start, 0, end, 5), True)

    def _open_term(self, edit: bool) -> None:
        glossary = self._selected_glossary()
        if glossary is None or (not edit and bool(self._term_add_reason(glossary))):
            return
        term = self._selected_term() if edit else None
        if edit and term is None:
            return
        inherited = term is not None and term.glossary_id != glossary.id
        if term is None:
            languages = glossary_chain(self.glossaries, glossary.id)[0].languages
            if languages is None:
                return
            record = GlossaryTerm("", glossary.id, PARTS_OF_SPEECH[0], TermSide(""), TermSide(""))
            term = orient_term(record, languages, str(self.source_language.currentData()))
        elif inherited:
            term = replace(term, term=replace(term.term, id="", glossary_id=glossary.id))
        dialog = GlossaryTermDialog(self.store, term, glossary.name, inherited, self.widget)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_terms()

    def _delete_term(self) -> None:
        term, glossary = self._selected_term(), self._selected_glossary()
        if term is None or glossary is None or term.glossary_id != glossary.id:
            return
        try:
            self.store.delete_term(glossary.id, term.id)
        except STORAGE_ERRORS as exc:
            self._error(exc)
            return
        self._refresh_terms()
