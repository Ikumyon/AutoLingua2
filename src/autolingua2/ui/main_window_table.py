from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QAction, QIcon, QMouseEvent
from PySide6.QtWidgets import QHeaderView, QMenu, QTableWidgetItem

from autolingua2.ir import UnitState
from autolingua2.ir.workspace import UnitView as TranslationUnit
from autolingua2.services.settings_store import (
    ColumnLayout, load_translation_table_columns, save_translation_table_columns,
)
from autolingua2.ui.i18n import tr
from autolingua2.ui.models.translation_table_model import (
    TranslationTableColumn, default_translation_table_columns,
)

if TYPE_CHECKING:
    from autolingua2.ui.main_window import MainWindowController


class TranslationTableController(QObject):
    """翻訳一覧の描画、編集イベント、列配置とドラッグ状態を管理する。"""

    def __init__(self, host: MainWindowController) -> None:
        super().__init__(host)
        self.host = host
        self.refresh_columns()
        self.column_layout = load_translation_table_columns(
            [column.id for column in self.columns],
            {column.id for column in self.columns if not column.default_visible},
        )
        self._syncing_header_order = False
        self._is_header_dragging = False
        self._drag_start_global_pos: QPoint | None = None

    def refresh_columns(self) -> None:
        self.columns = default_translation_table_columns(self.host.status_text)
        self.columns_by_id = {column.id: column for column in self.columns}

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QMouseEvent):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._is_header_dragging = True
                self._drag_start_global_pos = event.globalPosition().toPoint()
            elif event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                start = self._drag_start_global_pos
                if self._is_header_dragging and start is not None:
                    current = event.globalPosition().toPoint()
                    if (current - start).manhattanLength() >= 4:
                        header = self.host.table.horizontalHeader()
                        viewport = header.viewport()
                        reference = viewport if viewport is not None else header
                        self.show_header_drop_indicator(reference.mapFromGlobal(current))
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.hide_header_drop_indicator()
        elif event.type() == QEvent.Type.Leave and not self._is_header_dragging:
            self.hide_header_drop_indicator()
        return False

    def visible_columns(self) -> list[TranslationTableColumn]:
        return [
            self.columns_by_id[column_id]
            for column_id in self.column_layout.order
            if column_id in self.columns_by_id and column_id not in self.column_layout.hidden
        ]

    def open_table_header_menu(self, position: QPoint) -> None:
        header = self.host.table.horizontalHeader()
        logical_index = header.logicalIndexAt(position)
        visible_columns = self.visible_columns()
        clicked_column = visible_columns[logical_index].id if 0 <= logical_index < len(visible_columns) else None

        menu = QMenu(self.host.window)
        visible_count = len(visible_columns)

        for column_id in self.column_layout.order:
            column = self.columns_by_id.get(column_id)
            if column is None:
                continue
            action = QAction(column.label, menu)
            action.setCheckable(True)
            action.setChecked(column_id not in self.column_layout.hidden)
            action.setEnabled(not action.isChecked() or visible_count > 1)
            action.toggled.connect(lambda checked, selected_id=column_id: self.set_column_visible(selected_id, checked))
            menu.addAction(action)

        menu.addSeparator()
        move_left = menu.addAction(tr("MainWindow", "左へ移動"))
        move_left.setEnabled(clicked_column is not None and self.can_move_visible_column(clicked_column, -1))
        move_left.triggered.connect(lambda: self.move_visible_column(clicked_column, -1))

        move_right = menu.addAction(tr("MainWindow", "右へ移動"))
        move_right.setEnabled(clicked_column is not None and self.can_move_visible_column(clicked_column, 1))
        move_right.triggered.connect(lambda: self.move_visible_column(clicked_column, 1))

        menu.addSeparator()
        reset = menu.addAction(tr("MainWindow", "初期状態に戻す"))
        reset.triggered.connect(self.reset_column_layout)

        menu.exec(header.mapToGlobal(position))

    def set_column_visible(self, column_id: str, visible: bool) -> None:
        if visible:
            self.column_layout.hidden.discard(column_id)
        else:
            if len(self.visible_columns()) <= 1:
                return
            self.column_layout.hidden.add(column_id)
        self.save_and_refresh_column_layout()

    def can_move_visible_column(self, column_id: str | None, direction: int) -> bool:
        if column_id is None:
            return False
        visible_ids = [column.id for column in self.visible_columns()]
        if column_id not in visible_ids:
            return False
        new_index = visible_ids.index(column_id) + direction
        return 0 <= new_index < len(visible_ids)

    def move_visible_column(self, column_id: str | None, direction: int) -> None:
        if not self.can_move_visible_column(column_id, direction) or column_id is None:
            return
        visible_ids = [column.id for column in self.visible_columns()]
        old_visible_index = visible_ids.index(column_id)
        other_column_id = visible_ids[old_visible_index + direction]
        old_index = self.column_layout.order.index(column_id)
        other_index = self.column_layout.order.index(other_column_id)
        self.column_layout.order[old_index], self.column_layout.order[other_index] = (
            self.column_layout.order[other_index],
            self.column_layout.order[old_index],
        )
        self.save_and_refresh_column_layout()

    def reset_column_layout(self) -> None:
        self.column_layout = ColumnLayout(
            order=[column.id for column in self.columns],
            hidden={column.id for column in self.columns if not column.default_visible},
        )
        self.save_and_refresh_column_layout()

    def handle_table_section_moved(self, logical_index: int, old_visual_index: int, new_visual_index: int) -> None:
        self.hide_header_drop_indicator()
        if self._syncing_header_order or old_visual_index == new_visual_index:
            return
        visible_ids = [column.id for column in self.visible_columns()]
        if logical_index < 0 or logical_index >= len(visible_ids):
            return
        moved_column_id = visible_ids[logical_index]
        remaining_visible = [column_id for column_id in visible_ids if column_id != moved_column_id]
        bounded_index = max(0, min(new_visual_index, len(remaining_visible)))
        remaining_visible.insert(bounded_index, moved_column_id)
        self.reorder_layout_by_visible_ids(remaining_visible)
        save_translation_table_columns(self.column_layout)

    def reorder_layout_by_visible_ids(self, visible_ids: list[str]) -> None:
        visible_set = set(visible_ids)
        reordered: list[str] = []
        visible_iter = iter(visible_ids)
        for column_id in self.column_layout.order:
            if column_id in visible_set:
                reordered.append(next(visible_iter))
            else:
                reordered.append(column_id)
        self.column_layout.order = reordered

    def apply_header_visual_order(self) -> None:
        header = self.host.table.horizontalHeader()
        self._syncing_header_order = True
        try:
            for target_visual_index, logical_index in enumerate(range(self.host.table.columnCount())):
                current_visual_index = header.visualIndex(logical_index)
                if current_visual_index != target_visual_index:
                    header.moveSection(current_visual_index, target_visual_index)
        finally:
            self._syncing_header_order = False

    def save_and_refresh_column_layout(self) -> None:
        save_translation_table_columns(self.column_layout)
        self.refresh_table()

    def show_header_drop_indicator(self, position: QPoint) -> None:
        header = self.host.table.horizontalHeader()
        if self.host.table.columnCount() == 0 or header.count() == 0:
            self.hide_header_drop_indicator()
            return

        x = self.header_drop_indicator_x(position)
        h_vp = header.viewport()
        h_height = h_vp.height() if h_vp is not None else header.height()
        self.host.header_drop_indicator.setGeometry(x - 1, 0, 3, h_height)
        self.host.header_drop_indicator.raise_()
        self.host.header_drop_indicator.show()

        t_vp = self.host.table.viewport()
        if t_vp is not None:
            self.host.table_drop_indicator.setGeometry(x - 1, 0, 3, t_vp.height())
            self.host.table_drop_indicator.raise_()
            self.host.table_drop_indicator.show()

    def hide_header_drop_indicator(self) -> None:
        self._is_header_dragging = False
        self._drag_start_global_pos = None
        if hasattr(self.host, "header_drop_indicator"):
            self.host.header_drop_indicator.hide()
        if hasattr(self.host, "table_drop_indicator"):
            self.host.table_drop_indicator.hide()

    def header_drop_indicator_x(self, position: QPoint) -> int:
        header = self.host.table.horizontalHeader()
        x = position.x()
        logical_index = header.logicalIndexAt(x)

        if logical_index < 0:
            if x <= 0:
                first_logical = header.logicalIndex(0)
                return header.sectionViewportPosition(first_logical)
            last_logical = header.logicalIndex(header.count() - 1)
            return header.sectionViewportPosition(last_logical) + header.sectionSize(last_logical)

        section_left = header.sectionViewportPosition(logical_index)
        section_width = header.sectionSize(logical_index)
        section_center = section_left + section_width // 2
        if x < section_center:
            return section_left
        return section_left + section_width

    def refresh_table(self) -> None:
        visible_columns = self.visible_columns()
        self.host.table.clear()
        self.host.table.setColumnCount(len(visible_columns))
        self.host.table.setHorizontalHeaderLabels([column.label for column in visible_columns])
        self.host.table.setRowCount(len(self.host.filtered_units))
        self.host.table.verticalHeader().setDefaultSectionSize(60)

        # カラムIDに基づいてDelegateを動的バインド（列番号のハードコードなし）
        default_delegate = self.host.table.itemDelegate()
        for col_idx, col in enumerate(visible_columns):
            if col.id == "status":
                self.host.table.setItemDelegateForColumn(col_idx, self.host.status_delegate)
            elif col.id == "actions":
                self.host.table.setItemDelegateForColumn(col_idx, self.host.action_delegate)
            elif col.id == "target_text":
                self.host.table.setItemDelegateForColumn(col_idx, self.host.target_text_delegate)
            else:
                self.host.table.setItemDelegateForColumn(col_idx, default_delegate)

        for row, unit in enumerate(self.host.filtered_units):
            for column_index, column in enumerate(visible_columns):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, unit)

                if column.id == "target_text":
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                  (Qt.ItemFlag.ItemIsEditable if self.host.active_workspace is not None else Qt.ItemFlag.NoItemFlags))
                    display_text = unit.target_text
                    if self.host.render_literal_newlines:
                        display_text = self.host._expand_display_text(display_text)
                    item.setText(display_text)
                elif column.id == "actions":
                    item.setFlags(Qt.ItemFlag.ItemIsSelectable |
                                  (Qt.ItemFlag.ItemIsEnabled if self.host.active_workspace is not None else Qt.ItemFlag.NoItemFlags))
                    item.setText("")
                elif column.id == "status":
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                  (Qt.ItemFlag.ItemIsEditable if self.host.active_workspace is not None else Qt.ItemFlag.NoItemFlags))
                    item.setText(self.host.status_text(unit))
                    item.setIcon(self.status_icon(unit))
                else:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    value = column.value_for(unit, self.host.source_name_for_unit)
                    if self.host.render_literal_newlines and column.id == "source_text":
                        value = self.host._expand_display_text(value)
                    item.setText(value)

                self.host.table.setItem(row, column_index, item)

        self.apply_header_visual_order()
        self.host.table.resizeColumnsToContents()
        h_header = self.host.table.horizontalHeader()
        for col_idx, col in enumerate(visible_columns):
            h_header.setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Interactive)
            if col.id == "actions" and self.host.table.columnWidth(col_idx) < 70:
                self.host.table.setColumnWidth(col_idx, 70)

    def status_icon(self, unit: TranslationUnit) -> QIcon:
        icon = self._unit_status_icon(unit)
        return icon or self.host.icon_manager.get_icon("circle")

    def _on_table_status_delegate_changed(self, row: int, data: object) -> None:
        if self.host.active_workspace is None:
            return
        if not (0 <= row < len(self.host.filtered_units)):
            return
        unit = self.host.filtered_units[row]
        if data == "locked":
            unit.locked = True
            unit.hidden = False
        elif data == "hidden":
            unit.hidden = True
            unit.locked = False
        elif isinstance(data, UnitState):
            unit.locked = False
            unit.hidden = False
            unit.state = data

        self._sync_unit_row_content(row, unit)
        if self.host.focus_controller.current_unit is unit:
            self.host.focus_controller.refresh_focus(sync_list=False)
        self.host.focus_controller.refresh_focus_unit_list()

    def _on_table_action_delegate_clicked(self, row: int) -> None:
        if not (0 <= row < len(self.host.filtered_units)):
            return
        unit = self.host.filtered_units[row]
        self.host.translation_controller._translate_single_unit(unit)

    def _on_table_target_text_committed(self, row: int, new_text: str) -> None:
        if self.host.active_workspace is None:
            return
        if not (0 <= row < len(self.host.filtered_units)):
            return
        unit = self.host.filtered_units[row]
        if unit.target_text == new_text:
            return
        self.host.translation_controller.remember_confirmation(unit)
        unit.target_text = new_text
        if unit.state == UnitState.UNTRANSLATED and new_text.strip():
            unit.state = UnitState.HUMAN_TRANSLATED

        self._sync_unit_row_content(row, unit)
        if self.host.focus_controller.current_unit is unit:
            if not self.host.focus_controller._updating_focus and self.host.edit_translation.toPlainText() != new_text:
                self.host.edit_translation.setPlainText(new_text)
        self.host.translation_controller.confirm_manual_translation(unit, deferred=True)

    def _on_table_selection_changed(self) -> None:
        self.host.focus_controller.sync_focus_from_table()
        self.host._update_status_bar_counts()
        self.host.translation_controller._update_translation_button_state()

    def _get_selected_rows(self) -> list[int]:
        selection_model = self.host.table.selectionModel()
        if selection_model is None:
            return []
        return sorted({idx.row() for idx in selection_model.selectedRows()})

    def _sync_unit_row_content(self, row: int, unit: TranslationUnit) -> None:
        visible_columns = self.visible_columns()
        for col_idx, col in enumerate(visible_columns):
            item = self.host.table.item(row, col_idx)
            if item is None:
                continue
            item.setData(Qt.ItemDataRole.UserRole, unit)
            if col.id == "target_text":
                display_text = unit.target_text
                if self.host.render_literal_newlines:
                    display_text = self.host._expand_display_text(display_text)
                item.setText(display_text)
            elif col.id == "status":
                item.setText(self.host.status_text(unit))
                item.setIcon(self.status_icon(unit))

    def _on_table_cell_clicked(self, row: int, column: int) -> None:
        if 0 <= row < len(self.host.filtered_units):
            unit = self.host.filtered_units[row]
            if self.host.focus_controller.current_unit is not unit:
                self.host.focus_controller.current_unit = unit
                self.host.focus_controller.refresh_focus()

            visible_columns = self.visible_columns()
            if 0 <= column < len(visible_columns):
                col = visible_columns[column]
                if col.id in {"status", "target_text"}:
                    model_index = self.host.table.model().index(row, column)
                    self.host.table.edit(model_index)

    def _unit_status_icon(self, unit: TranslationUnit) -> QIcon | None:
        if unit.source_changed:
            return self.host.icon_manager.get_icon("triangle-alert")
        if unit.hidden or unit.state == UnitState.HIDDEN:
            return self.host.icon_manager.get_icon("eye-slash")
        if unit.locked or unit.state == UnitState.LOCKED:
            return self.host.icon_manager.get_icon("lock")
        if unit.issues:
            return self.host.icon_manager.get_icon("triangle-alert")
        if unit.state == UnitState.DOUBTFUL:
            return self.host.icon_manager.get_icon("question")
        if unit.state == UnitState.AI_REVIEWED:
            return self.host.icon_manager.get_icon("robot-check")
        if unit.state == UnitState.HUMAN_REVIEWED:
            return self.host.icon_manager.get_icon("person-check")
        if unit.state == UnitState.AI_TRANSLATED:
            return self.host.icon_manager.get_icon("robot-edit")
        if unit.state == UnitState.HUMAN_TRANSLATED:
            return self.host.icon_manager.get_icon("person-edit-32")
        return self.host.icon_manager.get_icon("circle")
