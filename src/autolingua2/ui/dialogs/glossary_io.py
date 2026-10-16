"""Designer-backed glossary transfer dialogs."""
from pathlib import Path
from collections.abc import Mapping

from PySide6.QtWidgets import (
    QComboBox, QDialogButtonBox, QFileDialog, QLabel, QMessageBox,
    QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QWidget,
)

from autolingua2.ir.glossary import Glossary, GlossaryTerm, glossary_chain, orient_term
from autolingua2.services.settings.glossary_io import (
    ExportMode, GlossaryDocument, ImportMode, build_export, write_document,
    external_document, read_json, parse_document, write_json,
)
from autolingua2.services.settings.glossary_format import GlossaryFormat, GlossaryExportData
from autolingua2.ui.resources.i18n import tr
from .base import SimpleDialogController, require_child


def _summary(document: GlossaryDocument) -> str:
    return tr("Glossary", "{glossaries}用語集 / {terms}語 / {inheritance}").format(
        glossaries=len(document.glossaries), terms=len(document.terms),
        inheritance=tr("Glossary", "継承あり") if len(document.glossaries) > 1 else tr("Glossary", "継承なし"))


def _fill_tree(tree: QTreeWidget, glossaries: tuple[Glossary, ...],
               terms: tuple[GlossaryTerm, ...] = (), selected_id: str = "", source_language: str = "") -> None:
    tree.clear()
    items = {g.id: QTreeWidgetItem([g.name]) for g in glossaries}
    for glossary in glossaries:
        item = items[glossary.id]
        if glossary.parent_id is None:
            tree.addTopLevelItem(item)
        else:
            items[glossary.parent_id].addChild(item)
        if glossary.id == selected_id:
            tree.setCurrentItem(item)
    for term in terms:
        languages = glossary_chain(glossaries, term.glossary_id)[0].languages
        if languages is None:
            raise ValueError("最上位の親で2言語を設定してください。")
        view = orient_term(term, languages, source_language or languages[0])
        term_item = QTreeWidgetItem([
            f"[{view.source_language} → {view.target_language}] {view.source} → {view.translation}"])
        items[term.glossary_id].addChild(term_item)
        for label, side in ((view.source_language, term.a if view.source_is_a else term.b),
                            (view.target_language, term.b if view.source_is_a else term.a)):
            if side.variants:
                term_item.addChild(
                    QTreeWidgetItem([tr("Glossary", "{language}の他形態：{variants}").format(
                        language=label, variants=" / ".join(side.variants))]))
    tree.expandAll()


class GlossaryExportDialog(SimpleDialogController):
    def __init__(self, glossaries: list[Glossary], terms: list[GlossaryTerm],
                 selected: Glossary, parent: QWidget, source_language: str,
                 formats: Mapping[str, GlossaryFormat]) -> None:
        super().__init__("dialogs/GlossaryExportDialog.ui", parent)
        self.glossaries, self.terms, self.selected = glossaries, terms, selected
        self.source_language = source_language
        self.formats = formats
        self.format = require_child(self.dialog, QComboBox, "comboExportFormat")
        self.format.addItem(tr("Glossary", "AUTOlingua2用語集"), "")
        for key, value in formats.items():
            self.format.addItem(value.name, key)
        self.format.currentIndexChanged.connect(self._format_changed)
        require_child(self.dialog, QPushButton, "buttonSwapExport").clicked.connect(self._swap)
        self.direction = require_child(self.dialog, QLabel, "labelExportDirection")
        self.external_output: GlossaryExportData | None = None
        require_child(self.dialog, QLabel, "labelScope").setText(tr("Glossary", "対象：") + selected.name)
        self.mode = require_child(self.dialog, QComboBox, "comboExportMode")
        self.modes = (ExportMode.OWN, ExportMode.FLAT, ExportMode.ANCESTORS, ExportMode.ALL)
        self.mode.addItems([
            tr("Glossary", "選択した用語集のみ：登録分"),
            tr("Glossary", "選択した用語集のみ：継承を統合"),
            tr("Glossary", "選択した用語集＋祖先"), tr("Glossary", "継承関係全体"),
        ])
        self.output = require_child(self.dialog, QTreeWidget, "treeOutput")
        self.summary = require_child(self.dialog, QLabel, "labelSummary")
        self.document = build_export(glossaries, terms, selected.id, ExportMode.OWN)
        _fill_tree(require_child(self.dialog, QTreeWidget, "treeCurrent"), tuple(glossaries), selected_id=selected.id)
        self.mode.currentIndexChanged.connect(self._refresh)
        box = require_child(self.dialog, QDialogButtonBox, "buttonBox")
        save = box.button(QDialogButtonBox.StandardButton.Save)
        if save is None:
            raise ValueError("書き出しボタンがありません。")
        save.setText(tr("Glossary", "書き出す…"))
        self.save_button = save
        box.accepted.connect(self._save)
        box.rejected.connect(self.dialog.reject)
        self._refresh()

    def _format_changed(self, _index: int) -> None:
        external = bool(self.format.currentData())
        self.mode.clear()
        modes = [tr("Glossary", "選択した用語集のみ：登録分"), tr("Glossary", "選択した用語集のみ：継承を統合")]
        if not external:
            modes += [tr("Glossary", "選択した用語集＋祖先"), tr("Glossary", "継承関係全体")]
        self.mode.addItems(modes)

    def _swap(self) -> None:
        languages = glossary_chain(self.glossaries, self.selected.id)[0].languages
        if languages is not None:
            self.source_language = languages[1] if self.source_language == languages[0] else languages[0]
            self._refresh()

    def _refresh(self, _index: int = 0) -> None:
        if self.mode.currentIndex() < 0:
            return
        self.document = build_export(self.glossaries, self.terms, self.selected.id,
                                     self.modes[self.mode.currentIndex()])
        _fill_tree(self.output, self.document.glossaries, self.document.terms, source_language=self.source_language)
        self.summary.setText(_summary(self.document))
        languages = self.document.glossaries[0].languages
        if languages is None:
            raise ValueError("最上位の親で2言語を設定してください。")
        source = self.source_language or languages[0]
        target = languages[1] if source == languages[0] else languages[0]
        self.direction.setText(tr("Glossary", "原文：{source} / 訳：{target}").format(source=source, target=target))
        self.external_output = None
        self.save_button.setEnabled(True)
        key = self.format.currentData()
        if key:
            try:
                self.external_output = self.formats[key].encode(tuple(orient_term(t, languages, source) for t in self.document.terms))
                output = self.external_output
                self.summary.setText(_summary(self.document) + "\n" + tr("Glossary",
                    "出力されない情報：訳の他形態 {variants}件 / 大文字小文字の設定 {settings}件 / 継承構造").format(
                        variants=output.omitted_target_variants, settings=output.omitted_case_settings))
            except ValueError as exc:
                self.summary.setText(str(exc))
                self.save_button.setEnabled(False)

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self.dialog, tr("Glossary", "用語集を書き出す"),
                                             "glossary.json", "JSON (*.json)")
        if not path:
            return
        try:
            if self.format.currentData():
                if self.external_output is None:
                    raise ValueError("出力内容を確認してください。")
                write_json(Path(path), self.external_output.payload)
            else:
                write_document(Path(path), self.document)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.dialog, tr("Glossary", "用語集の操作に失敗しました"), str(exc))
            return
        self.dialog.accept()


class GlossaryImportDialog(SimpleDialogController):
    def __init__(self, path: Path, destination: str, parent: QWidget,
                 formats: Mapping[str, GlossaryFormat], languages: tuple[str, str] | None,
                 source_language: str) -> None:
        super().__init__("dialogs/GlossaryImportDialog.ui", parent)
        self.path, self.destination = path, destination
        self.value = read_json(path)
        self.formats, self.languages = formats, languages
        self.source_language = source_language
        self.document: GlossaryDocument | None = None
        self.details = require_child(self.dialog, QLabel, "labelDetails")
        self.direction = require_child(self.dialog, QLabel, "labelImportDirection")
        self.swap = require_child(self.dialog, QPushButton, "buttonSwapImport")
        self.swap.clicked.connect(self._swap)
        self.format = require_child(self.dialog, QComboBox, "comboImportFormat")
        self.format.addItem(tr("Glossary", "AUTOlingua2用語集"), "")
        for key, value in formats.items():
            self.format.addItem(value.name, key)
        self.format.currentIndexChanged.connect(self._refresh)
        self.merge = require_child(self.dialog, QRadioButton, "radioMerge")
        self.create = require_child(self.dialog, QRadioButton, "radioNew")
        self.explanation = require_child(self.dialog, QLabel, "labelExplanation")
        self.merge.toggled.connect(self._explain)
        box = require_child(self.dialog, QDialogButtonBox, "buttonBox")
        accept = box.button(QDialogButtonBox.StandardButton.Ok)
        if accept is None:
            raise ValueError("取り込みボタンがありません。")
        self.accept_button = accept
        accept.setText(tr("Glossary", "取り込む"))
        box.accepted.connect(self.dialog.accept)
        box.rejected.connect(self.dialog.reject)
        self._refresh()

    @property
    def combine(self) -> bool:
        return bool(self.format.currentData())

    def _swap(self) -> None:
        if self.languages is not None:
            self.source_language = self.languages[1] if self.source_language == self.languages[0] else self.languages[0]
            self._refresh()

    def _refresh(self, _index: int = 0) -> None:
        self.document = None
        self.accept_button.setEnabled(False)
        key = self.format.currentData()
        self.swap.setEnabled(bool(key) and self.languages is not None)
        self.direction.setText("")
        prefix = tr("Glossary", "ファイル：{file}\n取り込み先：{destination}").format(
            file=self.path.name, destination=self.destination)
        try:
            extra = ""
            if key:
                languages = self.languages
                if languages is None:
                    raise ValueError(tr("Glossary", "最上位の親で2言語を設定してください。"))
                source = self.source_language if self.source_language in languages else languages[0]
                target = languages[1] if source == languages[0] else languages[0]
                self.direction.setText(tr("Glossary", "原文：{source} / 訳：{target}").format(source=source, target=target))
                data = self.formats[key].decode(self.value)
                document = external_document(data, self.path.stem, languages, source)
                extra = "\n" + tr("Glossary", "ファイル内：{count}件 / 他形態へ統合：{merged}件").format(
                    count=data.input_count, merged=data.input_count - len(data.terms))
            else:
                document = parse_document(self.value)
            self.document = document
            self.details.setText(prefix + "\n" + _summary(document) + extra)
            multiple = len(document.glossaries) > 1
            was_disabled = not self.merge.isEnabled()
            self.merge.setEnabled(not multiple)
            if multiple:
                self.create.setChecked(True)
            elif was_disabled:
                self.merge.setChecked(True)
            self.accept_button.setEnabled(True)
        except ValueError as exc:
            self.details.setText(prefix + "\n" + str(exc))
        self._explain()

    def _explain(self) -> None:
        if self.document is not None and len(self.document.glossaries) > 1:
            text = tr("Glossary", "継承付き用語集は、親子関係を保持して配下に新規作成します。統合はできません。")
        elif not self.merge.isChecked():
            text = tr("Glossary", "既存の用語は変更せず、ファイル内の名前で配下に新規作成します。")
        elif self.combine:
            text = tr("Glossary", "既存の代表表現・他形態・大文字小文字設定を保持し、表現とメモを統合します。親の用語は子で上書きします。")
        else:
            text = tr("Glossary", "同じ用語の両言語の情報を更新します。用語集名は変更しません。")
        self.explanation.setText(text)

    @property
    def mode(self) -> ImportMode:
        return ImportMode.MERGE if self.merge.isChecked() else ImportMode.NEW
