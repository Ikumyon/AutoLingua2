"""GUI editor for ordered branches and boolean expression trees."""
from __future__ import annotations

from autolingua2.ui.i18n import translation_source

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QMenu,
    QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QWidget,
)

from autolingua2.ir.tone import (
    COMPARISONS, TARGETS, ToneBlock, ToneBranch, ToneCondition, ToneExpression,
    ToneGroup, ToneItem, ToneOperator, validate_expression,
)
from autolingua2.ui.i18n import tr
from .base import require_child


TARGET_LABELS = (translation_source('TonePage', 'ファイル名'), translation_source('TonePage', 'キー'), translation_source('TonePage', '原文'))
COMPARISON_LABELS = (translation_source('TonePage', '一致する'), translation_source('TonePage', '含む'), translation_source('TonePage', 'で始まる'), translation_source('TonePage', 'で終わる'), translation_source('TonePage', '正規表現で検索'))


def expression_text(expression: ToneExpression) -> str:
    if isinstance(expression, ToneCondition):
        target = tr('TonePage', TARGET_LABELS[TARGETS.index(expression.target)])
        comparison = tr('TonePage', COMPARISON_LABELS[COMPARISONS.index(expression.comparison)])
        return f'{target} {comparison} 「{expression.value}」'
    children = [expression_text(child) for child in expression.children]
    if expression.operator == "not":
        return f"NOT ({children[0] if children else tr('TonePage', '未指定')})"
    separator = "、" if expression.operator == "and" else " OR "
    return "(" + separator.join(children) + ")"


@dataclass(slots=True)
class BranchLocation:
    block: ToneBlock
    branch: ToneBranch
    depth: int


@dataclass(slots=True)
class ExpressionLocation:
    expression: ToneExpression
    parent: ToneGroup | None


def branch_text(location: BranchLocation, tones: list[ToneItem]) -> str:
    branch = location.branch
    if branch.condition is None:
        label = tr('TonePage', 'それ以外の場合')
    else:
        index = next(i for i, item in enumerate(location.block.branches) if item is branch)
        template = tr('TonePage', 'もし {condition} なら') if index == 0 else tr('TonePage', 'そうでなく、{condition} なら')
        label = template.format(condition=expression_text(branch.condition))
    if branch.block is not None:
        output = None
    elif branch.tone_id is None:
        output = tr('TonePage', 'なし')
    else:
        output = next((tone.name for tone in tones if tone.id == branch.tone_id), tr('TonePage', '未登録の口調'))
    warning = tr('TonePage', '［深さ5以上・非推奨］') if location.depth >= 5 else ""
    return f"{warning}{label}" + (f" → {output}" if output is not None else "")


def populate_branches(tree: QTreeWidget, block: ToneBlock, tones: list[ToneItem],
                      parent: QTreeWidgetItem | None = None, depth: int = 1,
                      locations: list[tuple[QTreeWidgetItem, BranchLocation]] | None = None) -> None:
    for branch in block.branches:
        location = BranchLocation(block, branch, depth)
        label = branch_text(location, tones)
        item = QTreeWidgetItem([label])
        item.setToolTip(0, label)
        item.setData(0, Qt.ItemDataRole.UserRole, location)
        if parent is None:
            tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        if locations is not None:
            locations.append((item, location))
        if branch.block is not None:
            populate_branches(tree, branch.block, tones, item, depth + 1, locations)


class ToneRulesController:
    """Edit a selected branch's expression directly on the tone settings page."""

    def __init__(self, page: QWidget, changed: Callable[[], None]) -> None:
        self.page = page
        self.changed = changed
        self.branch: ToneBranch | None = None
        self.expression_items: list[tuple[QTreeWidgetItem, ExpressionLocation]] = []
        self.expressions = require_child(page, QTreeWidget, "treeExpressions")
        self.target = require_child(page, QComboBox, "comboToneTarget")
        self.comparison = require_child(page, QComboBox, "comboToneComparison")
        self.value = require_child(page, QLineEdit, "editToneValue")
        self.operator = require_child(page, QComboBox, "comboToneOperator")
        self.predicate_form = require_child(page, QFormLayout, "formPredicate")
        self.output = require_child(page, QComboBox, "comboToneOutput")
        self.output_row = require_child(page, QWidget, "paneToneOutput")
        self.expression_editor = require_child(page, QWidget, "paneExpressionEditor")
        self.select_branch = require_child(page, QLabel, "labelSelectBranch")
        self.preview = require_child(page, QPlainTextEdit, "editExpressionPreview")
        self.condition_error = require_child(page, QLabel, "labelConditionError")
        self.target.addItems([tr('TonePage', label) for label in TARGET_LABELS])
        self.comparison.addItems([tr('TonePage', label) for label in COMPARISON_LABELS])
        self.add_condition = require_child(page, QPushButton, "buttonAddCondition")
        self.add_group = require_child(page, QPushButton, "buttonAddGroup")
        self.toggle_not = require_child(page, QPushButton, "buttonToggleNot")
        self.delete_expression = require_child(page, QPushButton, "buttonDeleteExpression")
        self.expression_up = require_child(page, QPushButton, "buttonExpressionUp")
        self.expression_down = require_child(page, QPushButton, "buttonExpressionDown")
        group_menu = QMenu(self.add_group)
        group_menu.addAction(tr('TonePage', 'AND'), lambda: self._add_group("and"))
        group_menu.addAction(tr('TonePage', 'OR'), lambda: self._add_group("or"))
        self.add_group.setMenu(group_menu)
        self.expressions.currentItemChanged.connect(self._expression_selected)
        self.target.currentIndexChanged.connect(self._predicate_changed)
        self.comparison.currentIndexChanged.connect(self._predicate_changed)
        self.value.textChanged.connect(self._predicate_changed)
        self.operator.currentIndexChanged.connect(self._operator_changed)
        self.output.currentIndexChanged.connect(self._output_changed)
        self.add_condition.clicked.connect(lambda: self._insert_expression(ToneCondition()))
        self.toggle_not.clicked.connect(self._toggle_not)
        self.delete_expression.clicked.connect(self._delete_expression)
        self.expression_up.clicked.connect(lambda: self._move_expression(-1))
        self.expression_down.clicked.connect(lambda: self._move_expression(1))

    def select(self, branch: ToneBranch | None, tones: list[ToneItem]) -> None:
        self.branch = branch
        self.expression_editor.setVisible(branch is not None and branch.condition is not None)
        self.select_branch.setVisible(branch is None)
        leaf = branch is not None and branch.block is None
        self.output_row.setVisible(leaf)
        with QSignalBlocker(self.output):
            self.output.clear()
            self.output.addItem(tr('TonePage', 'なし'), None)
            for tone in tones:
                self.output.addItem(tone.name, tone.id)
            self.output.setCurrentIndex(max(0, self.output.findData(branch.tone_id))
                                        if branch is not None else 0)
        self._rebuild_expressions(branch.condition if branch is not None else None)

    def _expression(self) -> ExpressionLocation | None:
        item = self.expressions.currentItem()
        location = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return location if isinstance(location, ExpressionLocation) else None

    def _rebuild_expressions(self, selected: ToneExpression | None) -> None:
        expanded = {id(location.expression): item.isExpanded() for item, location in self.expression_items}
        with QSignalBlocker(self.expressions):
            self.expressions.clear()
            self.expression_items = []

            def add(expression: ToneExpression, parent_item: QTreeWidgetItem | None,
                    parent_group: ToneGroup | None) -> None:
                # Conjunction is implicit at the root and inside NOT. Within OR,
                # keep its operands grouped so flattening cannot change meaning.
                if (isinstance(expression, ToneGroup) and expression.operator == "and"
                        and expression.children
                        and (parent_group is None or parent_group.operator != "or")):
                    for child in expression.children:
                        add(child, parent_item, expression)
                    return
                item = QTreeWidgetItem()
                location = ExpressionLocation(expression, parent_group)
                item.setData(0, Qt.ItemDataRole.UserRole, location)
                if parent_item is None:
                    self.expressions.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self.expression_items.append((item, location))
                if isinstance(expression, ToneGroup):
                    for child in expression.children:
                        add(child, item, expression)
                item.setExpanded(expanded.get(id(expression), True))
                if expression is selected:
                    self.expressions.setCurrentItem(item)

            root = self.branch.condition if self.branch is not None else None
            if root is not None:
                add(root, None, None)
            if self.expressions.currentItem() is None and self.expression_items:
                self.expressions.setCurrentItem(self.expression_items[0][0])
        self._expression_selected()
        self._refresh_labels()

    def _expression_selected(self, *_args: object) -> None:
        location = self._expression()
        expression = location.expression if location is not None else None
        predicate = expression if isinstance(expression, ToneCondition) else None
        group = expression if isinstance(expression, ToneGroup) and expression.operator != "not" else None
        for widget in (self.target, self.comparison, self.value):
            widget.setEnabled(predicate is not None)
        with QSignalBlocker(self.target), QSignalBlocker(self.comparison), QSignalBlocker(self.value), QSignalBlocker(self.operator):
            self.target.setCurrentIndex(TARGETS.index(predicate.target) if predicate is not None else -1)
            self.comparison.setCurrentIndex(COMPARISONS.index(predicate.comparison) if predicate is not None else -1)
            self.value.setText(predicate.value if predicate is not None else "")
            self.operator.clear()
            if group is not None:
                self.operator.addItems([tr('TonePage', 'すべて満たす（既定）'), tr('TonePage', 'OR（いずれか満たす）')])
                self.operator.setCurrentIndex(("and", "or").index(group.operator))
        self.operator.setEnabled(group is not None)
        self.predicate_form.setRowVisible(self.operator, group is not None)
        for widget in (self.target, self.comparison, self.value):
            self.predicate_form.setRowVisible(widget, predicate is not None)
        enabled = expression is not None
        self.toggle_not.setText(tr('TonePage', 'NOTを解除') if isinstance(expression, ToneGroup)
                                and expression.operator == "not" else tr('TonePage', 'NOTを付ける'))
        for button in (self.add_condition, self.add_group, self.toggle_not):
            button.setEnabled(enabled)
        parent = location.parent if location is not None else None
        movable = parent is not None and parent.operator != "not" and len(parent.children) > 1
        self.delete_expression.setEnabled(movable)
        index = next((i for i, child in enumerate(parent.children) if child is expression), -1) if parent else -1
        self.expression_up.setEnabled(movable and index > 0)
        self.expression_down.setEnabled(movable and parent is not None and index < len(parent.children) - 1)
        self._validate()

    def _refresh_labels(self) -> None:
        for item, location in self.expression_items:
            expression = location.expression
            if isinstance(expression, ToneGroup) and expression.operator == "and":
                label = "AND" if expression.children else tr('TonePage', '条件を追加してください')
            else:
                label = expression.operator.upper() if isinstance(expression, ToneGroup) else expression_text(expression)
            item.setText(0, label)
            item.setToolTip(0, expression_text(expression))
        condition = self.branch.condition if self.branch is not None else None
        self.preview.setPlainText(expression_text(condition) if condition is not None
                                  else tr('TonePage', 'それ以外の場合（条件なし）') if self.branch is not None else "")
        self._validate()

    def _validate(self) -> None:
        location = self._expression()
        try:
            if location is not None:
                validate_expression(location.expression)
        except ValueError as exc:
            self.condition_error.setText(str(exc))
        else:
            self.condition_error.clear()

    def _predicate_changed(self, *_args: object) -> None:
        location = self._expression()
        if location is None or not isinstance(location.expression, ToneCondition):
            return
        expression = location.expression
        expression.target = TARGETS[self.target.currentIndex()]
        expression.comparison = COMPARISONS[self.comparison.currentIndex()]
        expression.value = self.value.text()
        self._refresh_labels()
        self.changed()

    def _operator_changed(self, index: int) -> None:
        location = self._expression()
        if location is None or not isinstance(location.expression, ToneGroup) or location.expression.operator == "not":
            return
        location.expression.operator = ("and", "or")[index]
        self._rebuild_expressions(location.expression)
        self.changed()

    def _output_changed(self, _index: int) -> None:
        branch = self.branch
        if branch is None or branch.block is not None:
            return
        value = self.output.currentData()
        branch.tone_id = value if isinstance(value, str) else None
        self.changed()

    def _replace_expression(self, location: ExpressionLocation, replacement: ToneExpression) -> None:
        if location.parent is None:
            if self.branch is None:
                raise RuntimeError("編集する分岐が選択されていません。")
            self.branch.condition = replacement
        else:
            index = next(i for i, item in enumerate(location.parent.children) if item is location.expression)
            location.parent.children[index] = replacement

    def _insert_expression(self, expression: ToneExpression) -> None:
        location = self._expression()
        if location is None:
            return
        current = location.expression
        if isinstance(current, ToneGroup) and current.operator == "not":
            child = current.children[0]
            if isinstance(child, ToneGroup) and child.operator == "and":
                child.children.append(expression)
            else:
                current.children[0] = ToneGroup("and", [child, expression])
        elif isinstance(current, ToneGroup):
            current.children.append(expression)
        elif location.parent is not None and location.parent.operator != "not":
            index = next(i for i, item in enumerate(location.parent.children) if item is current)
            location.parent.children.insert(index + 1, expression)
        else:
            self._replace_expression(location, ToneGroup("and", [current, expression]))
        self._rebuild_expressions(expression)
        self.changed()

    def _add_group(self, operator: ToneOperator) -> None:
        self._insert_expression(ToneGroup(operator, [ToneCondition(), ToneCondition()]))

    def _toggle_not(self) -> None:
        location = self._expression()
        if location is None:
            return
        expression = location.expression
        replacement = expression.children[0] if isinstance(expression, ToneGroup) and expression.operator == "not" else ToneGroup("not", [expression])
        self._replace_expression(location, replacement)
        self._rebuild_expressions(replacement)
        self.changed()

    def _delete_expression(self) -> None:
        location = self._expression()
        if location is None or location.parent is None or location.parent.operator == "not":
            return
        parent = location.parent
        if len(parent.children) <= 1:
            return
        index = next(i for i, item in enumerate(parent.children) if item is location.expression)
        parent.children.pop(index)
        selected = parent.children[min(index, len(parent.children) - 1)]
        if len(parent.children) == 1:
            root = self.branch.condition if self.branch is not None else None
            pending = [ExpressionLocation(root, None)] if root is not None else []
            while pending:
                parent_location = pending.pop()
                if parent_location.expression is parent:
                    self._replace_expression(parent_location, selected)
                    break
                expression = parent_location.expression
                if isinstance(expression, ToneGroup):
                    pending.extend(ExpressionLocation(child, expression) for child in expression.children)
        self._rebuild_expressions(selected)
        self.changed()

    def _move_expression(self, offset: int) -> None:
        location = self._expression()
        if location is None or location.parent is None or location.parent.operator == "not":
            return
        children = location.parent.children
        index = next(i for i, item in enumerate(children) if item is location.expression)
        destination = index + offset
        if 0 <= destination < len(children):
            children[index], children[destination] = children[destination], children[index]
            self._rebuild_expressions(location.expression)
            self.changed()
