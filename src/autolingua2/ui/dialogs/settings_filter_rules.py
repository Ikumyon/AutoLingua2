from __future__ import annotations

import re
import uuid
from collections.abc import Mapping

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHeaderView, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem,
)

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.filter_rules import AdapterFilterConfig, FilterRule, TagKind
from autolingua2.services.filter_rules import get_default_filter_config, get_filter_config
from autolingua2.services.settings_store import save_game_filter_rules
from autolingua2.ui.i18n import tr
from .base import require_child


class FilterRulesPageController(QObject):
    """Edit drafts of game-specific tag rules; persist only on dialog acceptance."""

    def __init__(
        self, dialog: QDialog, parsers: Mapping[str, FileAdapter],
        adapter_id: str = "", game_id: str = "",
    ) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.parsers = parsers
        self._configs: dict[tuple[str, str], AdapterFilterConfig] = {}
        self._originals: dict[tuple[str, str], list[FilterRule]] = {}
        self.changed_keys: set[tuple[str, str]] = set()
        self._current_key: tuple[str, str] | None = None
        self.combo_game = require_child(dialog, QComboBox, "comboRuleGame")
        self.table = require_child(dialog, QTableWidget, "tableFilterRules")
        self.button_add = require_child(dialog, QPushButton, "buttonAddRule")
        self.button_remove = require_child(dialog, QPushButton, "buttonRemoveRule")
        self.button_reset = require_child(dialog, QPushButton, "buttonResetRules")

        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            tr("SettingsDialog", value) for value in ("有効", "タグ区分", "正規表現", "例")
        ])
        header = self.table.horizontalHeader()
        for column in (0, 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

        games = [(adapter, game) for adapter in parsers.values() for game in adapter.supported_games]
        names = [game.name for _, game in games]
        self._keys = [(adapter.id, game.id) for adapter, game in games]
        for adapter, game in games:
            name = game.name if names.count(game.name) == 1 else f"{game.name} ({adapter.name})"
            self.combo_game.addItem(name)
        if (adapter_id, game_id) in self._keys:
            self.combo_game.setCurrentIndex(self._keys.index((adapter_id, game_id)))
        if self._keys:
            self._select_game(self.combo_game.currentIndex())
        else:
            for widget in (self.combo_game, self.table, self.button_add, self.button_remove, self.button_reset):
                widget.setEnabled(False)
        self.combo_game.currentIndexChanged.connect(self._select_game)
        self.button_add.clicked.connect(self._add_rule)
        self.button_remove.clicked.connect(self._remove_rule)
        self.button_reset.clicked.connect(self._reset_rules)

    def _select_game(self, index: int) -> None:
        self._store_table()
        self._current_key = self._keys[index] if 0 <= index < len(self._keys) else None
        key = self._current_key
        if key is None:
            return
        if key not in self._configs:
            config = get_filter_config(self.parsers[key[0]], key[1])
            self._configs[key] = config
            self._originals[key] = list(config.rules)
        self._populate_table()

    def _store_table(self) -> None:
        key = self._current_key
        if key is None:
            return
        rules: list[FilterRule] = []
        for row in range(self.table.rowCount()):
            check = self.table.item(row, 0)
            kind = self.table.cellWidget(row, 1)
            pattern = self.table.item(row, 2)
            example = self.table.item(row, 3)
            if check is None or not isinstance(kind, QComboBox) or pattern is None or example is None:
                raise RuntimeError("除外ルールの編集行が不完全です。")
            rule_id = check.data(Qt.ItemDataRole.UserRole)
            if not isinstance(rule_id, str):
                raise TypeError("除外ルールIDが不正です。")
            rules.append(FilterRule(
                rule_id, TagKind(kind.currentData()),
                enabled=check.checkState() == Qt.CheckState.Checked,
                pattern=pattern.text(), example=example.text(),
            ))
        self._configs[key].rules = rules

    def _populate_table(self) -> None:
        key = self._current_key
        if key is None:
            return
        rules = self._configs[key].rules
        tooltips = (
            tr("SettingsDialog", "文字・数字・アイコンそのものを表示せず、色や改行などを制御するタグです。\n例：§Y、§!、\\n"),
            tr("SettingsDialog", "ゲーム画面で文字・数字・アイコンとして表示される内容を表すタグです。\n例：[Root]、$NAME$、£gold£"),
        )
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, rule.id)
            self.table.setItem(row, 0, check)
            kind = QComboBox(self.table)
            kind.addItem(tr("SettingsDialog", "非文字タグ"), TagKind.NON_TEXT.value)
            kind.addItem(tr("SettingsDialog", "文字タグ"), TagKind.TEXT.value)
            for index, tooltip in enumerate(tooltips):
                kind.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            kind.setCurrentIndex(kind.findData(rule.kind.value))
            kind.setToolTip(tooltips[kind.currentIndex()])
            kind.currentIndexChanged.connect(
                lambda index, combo=kind, tips=tooltips: combo.setToolTip(tips[index]),
            )
            self.table.setCellWidget(row, 1, kind)
            self.table.setItem(row, 2, QTableWidgetItem(rule.pattern))
            self.table.setItem(row, 3, QTableWidgetItem(rule.example))

    def _add_rule(self) -> None:
        self._store_table()
        key = self._current_key
        if key is None:
            return
        self._configs[key].rules.append(FilterRule(f"custom_{uuid.uuid4().hex}", TagKind.NON_TEXT))
        self._populate_table()
        row = self.table.rowCount() - 1
        self.table.selectRow(row)
        item = self.table.item(row, 2)
        if item is not None:
            self.table.editItem(item)

    def _remove_rule(self) -> None:
        selection = self.table.selectionModel()
        if selection is None:
            return
        rows = selection.selectedRows()
        key = self._current_key
        if not rows or key is None:
            return
        self._store_table()
        self._configs[key].rules.pop(rows[0].row())
        self._populate_table()

    def _reset_rules(self) -> None:
        key = self._current_key
        if key is None:
            return
        self._configs[key] = get_default_filter_config(self.parsers[key[0]])
        self._populate_table()

    def validate(self) -> bool:
        self._store_table()
        for key, config in self._configs.items():
            for row, rule in enumerate(config.rules):
                try:
                    re.compile(rule.pattern)
                except re.error as exc:
                    self.combo_game.setCurrentIndex(self._keys.index(key))
                    self.table.selectRow(row)
                    self.table.setCurrentCell(row, 2)
                    QMessageBox.warning(
                        self.dialog, tr("SettingsDialog", "除外ルール"),
                        tr("SettingsDialog", "{game} の {row} 行目の正規表現が不正です。\n{error}").format(
                            game=self.combo_game.currentText(), row=row + 1, error=exc,
                        ),
                    )
                    return False
        return True

    def save(self) -> None:
        self._store_table()
        for key, config in self._configs.items():
            if config.rules != self._originals[key]:
                save_game_filter_rules(key[0], key[1], config.to_dict())
                self.changed_keys.add(key)
