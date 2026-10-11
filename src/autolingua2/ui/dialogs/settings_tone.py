"""Shared tone drafts and inline branch editing in translation settings."""
from __future__ import annotations

from html import escape
from uuid import uuid4

from PySide6.QtCore import QBuffer, QIODevice, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QWidget,
)

from autolingua2.ir.tone import (
    ConditionalTone, Tone, ToneBlock, ToneBranch, ToneItem, add_tone_branch,
    delete_tone, remove_nested_branches, tone_references, validate_tones,
)
from autolingua2.services.tone_store import ToneStore
from autolingua2.ui.components.searchable_combo_box import SearchableActionComboBox
from autolingua2.ui.icons import IconManager
from .base import require_child
from .tone_rules import BranchLocation, ToneRulesController, branch_text, populate_branches, t


class TonePageController:
    def __init__(self, page: QWidget, icon_manager: IconManager, selected_id: str = "") -> None:
        self.page = page
        self.icon_manager = icon_manager
        self.store = ToneStore()
        self.tones: list[Tone] = []
        self.dirty = False
        self.load_error = ""
        self.creating = False
        self.tree = require_child(page, QTreeWidget, "treeToneBranches")
        selection_container = require_child(page, QWidget, "paneToneSelection")
        selection_layout = selection_container.layout()
        if selection_layout is None:
            raise RuntimeError("口調選択のレイアウトがありません。")
        self.combo = SearchableActionComboBox(
            t("＋新しい口調…"), t("該当する口調がありません。"), selection_container,
            search_role=Qt.ItemDataRole.UserRole + 1,
        )
        self.combo.setObjectName("comboManagedTone")
        self.combo.editor.setPlaceholderText(t("名前を入力して検索"))
        selection_layout.addWidget(self.combo)
        self.creation_row = require_child(page, QWidget, "paneToneCreation")
        self.kind = require_child(page, QComboBox, "comboNewToneKind")
        self.kind.addItems([t("通常口調"), t("条件付き口調")])
        self.kind.setPlaceholderText(t("種類を選択してください"))
        self.kind.setCurrentIndex(-1)
        self.creation_row.hide()
        self.name = require_child(page, QLineEdit, "editToneName")
        self.prompt = require_child(page, QPlainTextEdit, "editTonePrompt")
        self.stack = require_child(page, QStackedWidget, "stackToneEditor")
        self.error = require_child(page, QLabel, "labelRulesError")
        self.depth = require_child(page, QLabel, "labelBranchDepth")
        self.delete_tone = require_child(page, QPushButton, "buttonDeleteTone")
        self.add_branch = require_child(page, QPushButton, "buttonAddToneBranch")
        self.delete_branch = require_child(page, QPushButton, "buttonDeleteBranch")
        self.up = require_child(page, QPushButton, "buttonBranchUp")
        self.down = require_child(page, QPushButton, "buttonBranchDown")
        self.root_item: QTreeWidgetItem | None = None
        self.branches: list[tuple[QTreeWidgetItem, BranchLocation]] = []
        self.rules = ToneRulesController(page, self._changed)
        splitter = require_child(page, QSplitter, "splitterTones")
        splitter.setSizes([330, 430])
        splitter.setChildrenCollapsible(False)
        try:
            self.tones = self.store.load()
        except (OSError, ValueError) as exc:
            self.load_error = str(exc)
        self.combo.currentIndexChanged.connect(self._selected)
        self.combo.actionRequested.connect(self._begin_create)
        self.kind.currentIndexChanged.connect(self._add_tone)
        self.tree.currentItemChanged.connect(self._branch_selected)
        self.name.textChanged.connect(self._name_changed)
        self.prompt.textChanged.connect(self._prompt_changed)
        self.delete_tone.clicked.connect(self._delete_tone)
        self.add_branch.clicked.connect(self._add_branch)
        self.delete_branch.clicked.connect(self._delete_branch)
        self.up.clicked.connect(lambda: self._move_branch(-1))
        self.down.clicked.connect(lambda: self._move_branch(1))
        for button in page.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.combo.setEnabled(not self.load_error)
        self._refresh_choices(selected_id)

    def _normal_tones(self) -> list[ToneItem]:
        return [tone for tone in self.tones if isinstance(tone, ToneItem)]

    def _tone(self) -> Tone | None:
        tone_id = self.combo.currentData()
        return next((tone for tone in self.tones if tone.id == tone_id), None)

    def _location(self) -> BranchLocation | None:
        item = self.tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return data if isinstance(data, BranchLocation) else None

    def _rebuild(self, selected: Tone | ToneBranch | None = None) -> None:
        expanded = {id(loc.branch): item.isExpanded() for item, loc in self.branches}
        with QSignalBlocker(self.tree):
            self.tree.clear()
            self.root_item = None
            self.branches = []
            tone = self._tone()
            if isinstance(tone, ConditionalTone):
                item = QTreeWidgetItem([tone.name])
                item.setData(0, Qt.ItemDataRole.UserRole, tone)
                self.tree.addTopLevelItem(item)
                self.root_item = item
                populate_branches(self.tree, tone.block, self._normal_tones(), item,
                                  locations=self.branches)
                item.setExpanded(True)
                self.tree.setCurrentItem(item)
            for item, loc in self.branches:
                item.setExpanded(expanded.get(id(loc.branch), True))
                if loc.branch is selected:
                    self.tree.setCurrentItem(item)
        self._branch_selected()

    def _label(self, tone: Tone) -> str:
        name = tone.name if tone.name.strip() else t("新しい口調（未保存）")
        return name + (t("［条件付き］") if isinstance(tone, ConditionalTone) else "")

    def _refresh_choices(self, selected_id: str = "") -> None:
        with QSignalBlocker(self.combo):
            self.combo.clear()
            for tone in self.tones:
                self.combo.addItem(self._label(tone), tone.id)
                self.combo.setItemData(self.combo.count() - 1, tone.name, Qt.ItemDataRole.UserRole + 1)
            self.combo.setCurrentIndex(max(0, self.combo.findData(selected_id)) if self.tones else -1)
        self._selected()

    def _selected(self, *_args: object) -> None:
        tone = self._tone()
        self.creating = False
        self.creation_row.hide()
        self.combo.editor.setPlaceholderText(t("名前を入力して検索"))
        self.stack.setCurrentIndex(1 if isinstance(tone, ConditionalTone) else 0 if tone is not None else 2)
        self.name.setEnabled(tone is not None)
        self.delete_tone.setEnabled(tone is not None)
        with QSignalBlocker(self.name), QSignalBlocker(self.prompt):
            self.name.setText(tone.name if tone is not None else "")
            self.prompt.setPlainText(tone.prompt if isinstance(tone, ToneItem) else "")
        self._rebuild(tone)
        self._validate_draft()

    def _branch_selected(self, *_args: object) -> None:
        location = self._location()
        self.rules.select(location.branch if location is not None else None, self._normal_tones())
        self._branch_actions()

    def _branch_actions(self) -> None:
        tone = self._tone()
        location = self._location()
        parent = location.branch if location is not None else tone
        block = parent.block if isinstance(parent, (ConditionalTone, ToneBranch)) else None
        has_children = block is not None and bool(block.branches)
        self.add_branch.setText(t("「そうでなく、～なら」を追加") if has_children else t("「もし～なら」を追加"))
        self.add_branch.setEnabled(isinstance(tone, ConditionalTone))
        self.delete_branch.setText(t("内側の分岐を削除") if has_children else t("分岐を削除"))
        removable = False
        up = down = False
        if location is not None:
            siblings = location.block.branches
            index = next(i for i, branch in enumerate(siblings) if branch is location.branch)
            movable = location.branch.condition is not None
            removable = has_children or (movable and len(siblings) > 2)
            up = movable and index > 0
            down = movable and index < len(siblings) - 2
        self.delete_branch.setEnabled(removable)
        self._update_delete_tooltip(location, has_children)
        self.up.setEnabled(up)
        self.down.setEnabled(down)
        self.depth.setText(t("分岐の深さ：{depth}").format(depth=location.depth)
                           + (t("　深さ5以上の入れ子は非推奨です。") if location.depth >= 5 else "")
                           if location is not None else "")

    def _tooltip_icon(self, name: str) -> str:
        image = self.icon_manager.get_icon(name).pixmap(16, 16).toImage()
        if image.isNull():
            raise RuntimeError(f"削除条件のアイコンがありません: {name}")
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("ツールチップ画像のバッファを開けません。")
        if not image.save(buffer, b"PNG"):
            raise RuntimeError("ツールチップのアイコンを変換できません。")
        encoded = bytes(buffer.data().toBase64().data()).decode("ascii")
        buffer.close()
        return f'<img src="data:image/png;base64,{encoded}" width="16" height="16" />'

    def _update_delete_tooltip(self, location: BranchLocation | None, has_children: bool) -> None:
        requirements: list[tuple[bool, str]] = [
            (location is not None, t("分岐を選択している")),
        ]
        nested = location is not None and has_children
        if nested:
            requirements.append((has_children, t("選択した分岐の内側に分岐がある")))
        else:
            requirements.extend([
                (location is not None and location.branch.condition is not None,
                 t("条件のある分岐である")),
                (location is not None and len(location.block.branches) > 2,
                 t("同じ階層に条件のある分岐が2つ以上ある")),
            ])
        icons = {True: self._tooltip_icon("check"), False: self._tooltip_icon("x")}
        rows = "".join(
            f'<tr><td>{icons[met]}</td><td>{escape(label)}</td></tr>'
            for met, label in requirements
        )
        tooltip = f'<p><b>{escape(t("削除条件（すべて必要）"))}</b></p><table>{rows}</table>'
        if nested:
            tooltip += "<p>" + escape(t(
                "選択中の分岐自体は残り、最も内側の「それ以外の場合」の口調を引き継ぎます。"
            )) + "</p>"
        self.delete_branch.setToolTip(tooltip)

    def _changed(self) -> None:
        self.dirty = True
        with QSignalBlocker(self.combo):
            for tone in self.tones:
                index = self.combo.findData(tone.id)
                if index >= 0:
                    self.combo.setItemText(index, self._label(tone))
                    self.combo.setItemData(index, tone.name, Qt.ItemDataRole.UserRole + 1)
        tone = self._tone()
        if self.root_item is not None and tone is not None:
            self.root_item.setText(0, tone.name)
        for item, loc in self.branches:
            text = branch_text(loc, self._normal_tones())
            item.setText(0, text)
            item.setToolTip(0, text)
        self._branch_actions()
        self._validate_draft()

    def _name_changed(self, value: str) -> None:
        tone = self._tone()
        if tone is not None:
            tone.name = value
            self._changed()

    def _prompt_changed(self) -> None:
        tone = self._tone()
        if isinstance(tone, ToneItem):
            tone.prompt = self.prompt.toPlainText()
            self._changed()

    def _begin_create(self) -> None:
        self.creating = True
        with QSignalBlocker(self.combo), QSignalBlocker(self.name), QSignalBlocker(self.kind):
            self.combo.setCurrentIndex(-1)
            self.combo.setEditText(t("新しい口調"))
            self.name.clear()
            self.kind.setCurrentIndex(-1)
        self.name.setEnabled(False)
        self.delete_tone.setEnabled(False)
        self.creation_row.show()
        self.combo.editor.setPlaceholderText(t("新しい口調"))
        self.stack.setCurrentIndex(2)
        self._rebuild()
        self.error.clear()
        self.depth.clear()
        self.kind.setFocus()

    def _add_tone(self, index: int) -> None:
        if not self.creating or index < 0:
            return
        tone: Tone = (ConditionalTone(str(uuid4()), "", ToneBlock([]))
                      if index == 1 else ToneItem(str(uuid4()), "", ""))
        self.tones.append(tone)
        self._refresh_choices(tone.id)
        self._changed()
        self.name.setFocus()
        self.name.selectAll()

    def _delete_tone(self) -> None:
        tone = self._tone()
        if tone is None:
            return
        message = t("「{name}」を削除しますか？").format(name=tone.name)
        if tone_references(self.tones, tone.id):
            message += t("\n条件付き口調で参照している箇所は「なし」になります。")
        if QMessageBox.question(self.page, t("口調の削除"), message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        delete_tone(self.tones, tone.id)
        self._refresh_choices()
        self._changed()

    def _add_branch(self) -> None:
        tone = self._tone()
        if not isinstance(tone, ConditionalTone):
            return
        location = self._location()
        parent = location.branch if location is not None else tone
        add_tone_branch(parent)
        self._rebuild(parent)
        self._changed()

    def _delete_branch(self) -> None:
        location = self._location()
        if location is None:
            return
        branch = location.branch
        if branch.block is not None:
            if QMessageBox.question(self.page, t("条件分岐の削除"), t("配下の条件分岐を削除しますか？"),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            remove_nested_branches(branch)
            self._rebuild(branch)
        elif branch.condition is not None and len(location.block.branches) > 2:
            index = next(i for i, child in enumerate(location.block.branches) if child is branch)
            location.block.branches.pop(index)
            self._rebuild(location.block.branches[0])
        else:
            return
        self._changed()

    def _move_branch(self, offset: int) -> None:
        location = self._location()
        if location is None or location.branch.condition is None:
            return
        siblings = location.block.branches
        index = next(i for i, branch in enumerate(siblings) if branch is location.branch)
        target = index + offset
        if 0 <= target < len(siblings) - 1:
            siblings[index], siblings[target] = siblings[target], siblings[index]
            self._rebuild(location.branch)
            self._changed()

    def _validate_draft(self) -> bool:
        if self.load_error:
            self.error.setText(self.load_error)
            return False
        try:
            validate_tones(self.tones)
        except ValueError as exc:
            self.error.setText(str(exc))
            return False
        self.error.clear()
        return True

    def validate(self) -> bool:
        if self.creating:
            self.error.setText(t("新しい口調の種類を選択してください。"))
            return False
        return not self.dirty or self._validate_draft()

    def save(self) -> bool:
        if not self.validate():
            return False
        if not self.dirty:
            return True
        try:
            self.store.save(self.tones)
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return False
        self.dirty = False
        return True
