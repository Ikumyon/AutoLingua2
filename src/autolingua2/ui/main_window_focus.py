from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QListWidgetItem, QMenu

from autolingua2.ir import UnitState
from autolingua2.ir.workspace import UnitView as TranslationUnit
from autolingua2.ui.i18n import tr

if TYPE_CHECKING:
    from autolingua2.ui.main_window import MainWindowController


class FocusEditorController(QObject):
    """個別編集の選択、ページ移動、表示と保存操作を管理する。"""

    def __init__(self, host: MainWindowController) -> None:
        super().__init__(host)
        self.host = host
        self.current_unit: TranslationUnit | None = None
        self._updating_focus = False
        self._syncing_focus_list = False
        self.focus_page_size = 50
        self.focus_current_page = 1

    def refresh_focus_unit_list(self) -> None:
        self._syncing_focus_list = True
        try:
            total_pages = self.total_focus_pages()
            self.focus_current_page = max(1, min(total_pages, self.focus_current_page))
            self.host.page_scrubber.set_pages(self.focus_current_page, total_pages)
            self._ensure_focus_sidebar_minimum_width()

            self.host.button_focus_first.setEnabled(self.focus_current_page > 1)
            self.host.button_focus_prev.setEnabled(self.focus_current_page > 1)
            self.host.button_focus_next.setEnabled(self.focus_current_page < total_pages)
            self.host.button_focus_last.setEnabled(self.focus_current_page < total_pages)

            self.host.list_focus_units.clear()
            start = (self.focus_current_page - 1) * self.focus_page_size
            end = min(len(self.host.filtered_units), start + self.focus_page_size)
            page_units = self.host.filtered_units[start:end]

            for unit in page_units:
                preview = " ".join(unit.source_text.split())
                if len(preview) > 50:
                    preview = preview[:47] + "..."
                if not preview:
                    preview = f"<{unit.label}>"
                item = QListWidgetItem(preview)
                icon = self.host.table_controller._unit_status_icon(unit)
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                source_name = self.host.source_name_for_unit(unit)
                tooltip = f"キー: {unit.label}\nファイル: {source_name}\n状態: {self.host.status_text(unit)}\n\n原文:\n{unit.source_text}"
                if unit.target_text:
                    tooltip += f"\n\n訳文:\n{unit.target_text}"
                item.setToolTip(tooltip)
                self.host.list_focus_units.addItem(item)
            self._sync_focus_list_selection()
        finally:
            self._syncing_focus_list = False

    def total_focus_pages(self) -> int:
        if not self.host.filtered_units:
            return 1
        return max(1, (len(self.host.filtered_units) + self.focus_page_size - 1) // self.focus_page_size)

    def set_focus_page(self, page: int) -> None:
        total = self.total_focus_pages()
        new_page = max(1, min(total, page))
        if self.focus_current_page != new_page:
            self.focus_current_page = new_page
            start = (new_page - 1) * self.focus_page_size
            if 0 <= start < len(self.host.filtered_units):
                self.current_unit = self.host.filtered_units[start]
                self.refresh_focus(sync_list=False)
            self.refresh_focus_unit_list()

    def first_focus_page(self) -> None:
        self.set_focus_page(1)

    def prev_focus_page(self) -> None:
        self.set_focus_page(self.focus_current_page - 1)

    def next_focus_page(self) -> None:
        self.set_focus_page(self.focus_current_page + 1)

    def last_focus_page(self) -> None:
        self.set_focus_page(self.total_focus_pages())

    def on_focus_page_size_changed(self, size: int) -> None:
        if size > 0 and self.focus_page_size != size:
            self.focus_page_size = size
            if self.current_unit in self.host.filtered_units:
                idx = self.host.filtered_units.index(self.current_unit)
                self.focus_current_page = (idx // self.focus_page_size) + 1
            else:
                self.focus_current_page = 1
            self.refresh_focus_unit_list()

    def _sync_focus_list_selection(self) -> None:
        if self.current_unit is None or not self.host.filtered_units:
            self.host.list_focus_units.clearSelection()
            return
        try:
            global_idx = self.host.filtered_units.index(self.current_unit)
        except ValueError:
            global_idx = -1
        if global_idx >= 0:
            unit_page = (global_idx // self.focus_page_size) + 1
            if unit_page != self.focus_current_page:
                self.host.list_focus_units.clearSelection()
                return
            page_idx = global_idx - (self.focus_current_page - 1) * self.focus_page_size
            if self.host.list_focus_units.currentRow() != page_idx:
                self._syncing_focus_list = True
                try:
                    self.host.list_focus_units.setCurrentRow(page_idx)
                    item = self.host.list_focus_units.item(page_idx)
                    if item is not None:
                        self.host.list_focus_units.scrollToItem(item)
                finally:
                    self._syncing_focus_list = False

    def _on_focus_unit_selected(self, row: int) -> None:
        if self._syncing_focus_list or row < 0:
            return
        global_idx = (self.focus_current_page - 1) * self.focus_page_size + row
        if 0 <= global_idx < len(self.host.filtered_units):
            unit = self.host.filtered_units[global_idx]
            if unit is not self.current_unit:
                self.current_unit = unit
                self.refresh_focus(sync_list=False)

    def sync_focus_from_table(self) -> None:
        selected = self.host.table.selectedItems()
        if not selected:
            return
        unit = selected[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(unit, TranslationUnit):
            self.current_unit = unit
            self.refresh_focus()

    def refresh_focus(self, sync_list: bool = True) -> None:
        self._updating_focus = True
        try:
            unit = self.current_unit
            if unit is None:
                self.host.edit_key.clear()
                self.host.edit_file.clear()
                self.host.edit_source.clear()
                self.host.edit_translation.clear()
                self.host.label_position.setText("0 / 0")
                if sync_list:
                    self._sync_focus_list_selection()
                return

            position = self.host.filtered_units.index(unit) + 1 if unit in self.host.filtered_units else 0
            self.host.translation_controller.remember_confirmation(unit)
            self.host.label_position.setText(f"{position} / {len(self.host.filtered_units)}")
            self.host.edit_key.setText(unit.label)
            self.host.edit_file.setText(self.host.source_name_for_unit(unit))
            source_display = unit.source_text
            target_display = unit.target_text
            source_display = self.host._expand_display_text(source_display)
            target_display = self.host._expand_display_text(target_display)
            self.host.edit_source.setPlainText(source_display)
            self.host.edit_translation.setPlainText(target_display)
            if sync_list:
                unit_page = ((position - 1) // self.focus_page_size) + 1 if position > 0 else 1
                if unit_page != self.focus_current_page:
                    self.focus_current_page = unit_page
                    self.refresh_focus_unit_list()
                else:
                    self._sync_focus_list_selection()
        finally:
            self._updating_focus = False

    def mark_focus_edited(self) -> None:
        if self._updating_focus or self.current_unit is None or self.host.active_workspace is None:
            return
        new_target = self.host.edit_translation.toPlainText()
        if new_target == self.host._expand_display_text(self.current_unit.target_text):
            return  # Syntax formatting also emits textChanged without changing text.
        presentation = self.host._text_presentation
        if self.host.render_literal_newlines and presentation is not None and presentation.newline_codec is not None:
            new_target = presentation.newline_codec.collapse(new_target)
        self.host.workspace_service.begin_translation_edit(self.host.active_workspace, self.current_unit.id)
        self.current_unit.target_text = new_target
        if self.current_unit in self.host.filtered_units:
            row = self.host.filtered_units.index(self.current_unit)
            self.host.table_controller._sync_unit_row_content(row, self.current_unit)
        else:
            self.host.table_controller.refresh_table()

    def copy_source_to_translation(self) -> None:
        if self.host.active_workspace is None:
            return
        source_text = self.host.edit_source.toPlainText()
        self.host.edit_translation.setPlainText(source_text)

    def _setup_save_button_menu(self) -> None:
        menu = QMenu(self.host.window)

        action_save_next = QAction(self.host.icon_manager.get_icon("save"), tr("MainWindow", "保存して次へ (人間による翻訳)"), self.host.window)
        action_save_next.setShortcut("Ctrl+Return")
        action_save_next.triggered.connect(self.save_and_next)
        menu.addAction(action_save_next)

        action_save_stay = QAction(self.host.icon_manager.get_icon("file"), tr("MainWindow", "保存 (留まる)"), self.host.window)
        action_save_stay.setShortcut("Ctrl+S")
        action_save_stay.triggered.connect(self.save_stay)
        menu.addAction(action_save_stay)

        menu.addSeparator()

        action_human_trans = QAction(self.host.icon_manager.get_icon("person-edit-32"), tr("MainWindow", "人間による翻訳として保存"), self.host.window)
        action_human_trans.triggered.connect(lambda: self.save_with_state(UnitState.HUMAN_TRANSLATED))
        menu.addAction(action_human_trans)

        action_human_rev = QAction(self.host.icon_manager.get_icon("person-check"), tr("MainWindow", "人間による校閲として保存"), self.host.window)
        action_human_rev.triggered.connect(lambda: self.save_with_state(UnitState.HUMAN_REVIEWED))
        menu.addAction(action_human_rev)

        action_ai_trans = QAction(self.host.icon_manager.get_icon("robot-edit"), tr("MainWindow", "AIによる翻訳として保存"), self.host.window)
        action_ai_trans.triggered.connect(lambda: self.save_with_state(UnitState.AI_TRANSLATED))
        menu.addAction(action_ai_trans)

        action_ai_rev = QAction(self.host.icon_manager.get_icon("robot-check"), tr("MainWindow", "AIによる校閲として保存"), self.host.window)
        action_ai_rev.triggered.connect(lambda: self.save_with_state(UnitState.AI_REVIEWED))
        menu.addAction(action_ai_rev)

        action_doubtful = QAction(self.host.icon_manager.get_icon("question"), tr("MainWindow", "疑問ありとして保存"), self.host.window)
        action_doubtful.triggered.connect(lambda: self.save_with_state(UnitState.DOUBTFUL))
        menu.addAction(action_doubtful)

        action_locked = QAction(self.host.icon_manager.get_icon("lock"), tr("MainWindow", "ロックとして保存"), self.host.window)
        action_locked.triggered.connect(self.save_as_locked)
        menu.addAction(action_locked)

        action_hidden = QAction(self.host.icon_manager.get_icon("eye-slash"), tr("MainWindow", "非表示として保存"), self.host.window)
        action_hidden.triggered.connect(self.save_as_hidden)
        menu.addAction(action_hidden)

        menu.addSeparator()

        action_untranslated = QAction(self.host.icon_manager.get_icon("brush-cleaning"), tr("MainWindow", "未翻訳に戻す"), self.host.window)
        action_untranslated.triggered.connect(self.save_as_untranslated)
        menu.addAction(action_untranslated)

        self.host.button_save_split.setMenu(menu)

    def save_and_next(self) -> None:
        self._save_current_unit_changes(next_entry=True)

    def save_stay(self) -> None:
        self._save_current_unit_changes(next_entry=False)

    def save_with_state(self, state: UnitState) -> None:
        if self.host.active_workspace is None:
            return
        if self.current_unit is not None:
            self.current_unit.target_text = self.host.edit_translation.toPlainText()
            self.current_unit.state = state
            self._after_unit_saved(next_entry=True)

    def save_as_locked(self) -> None:
        if self.host.active_workspace is None:
            return
        if self.current_unit is not None:
            self.current_unit.target_text = self.host.edit_translation.toPlainText()
            self.current_unit.locked = True
            self.current_unit.state = UnitState.LOCKED
            self._after_unit_saved(next_entry=True)

    def save_as_hidden(self) -> None:
        if self.host.active_workspace is None:
            return
        if self.current_unit is not None:
            self.current_unit.target_text = self.host.edit_translation.toPlainText()
            self.current_unit.hidden = True
            self.current_unit.state = UnitState.HIDDEN
            self._after_unit_saved(next_entry=True)

    def save_as_untranslated(self) -> None:
        if self.host.active_workspace is None:
            return
        if self.current_unit is not None:
            self.current_unit.state = UnitState.UNTRANSLATED
            self._after_unit_saved(next_entry=True)

    def _save_current_unit_changes(self, next_entry: bool) -> None:
        if self.current_unit is None or self.host.active_workspace is None:
            return
        text = self.host.edit_translation.toPlainText()
        self.current_unit.target_text = text
        if text.strip():
            self.current_unit.state = UnitState.HUMAN_TRANSLATED
        else:
            self.current_unit.state = UnitState.UNTRANSLATED
        self._after_unit_saved(next_entry=next_entry)

    def _after_unit_saved(self, next_entry: bool) -> None:
        if self.current_unit is not None:
            self.host.translation_controller.confirm_manual_translation(self.current_unit)
        self.host.table_controller.refresh_table()
        if self.current_unit in self.host.filtered_units:
            global_idx = self.host.filtered_units.index(self.current_unit)
            start = (self.focus_current_page - 1) * self.focus_page_size
            end = start + self.focus_page_size
            if start <= global_idx < end:
                page_idx = global_idx - start
                item = self.host.list_focus_units.item(page_idx)
                if item is not None:
                    preview = " ".join(self.current_unit.source_text.split())
                    if len(preview) > 50:
                        preview = preview[:47] + "..."
                    if not preview:
                        preview = f"<{self.current_unit.label}>"
                    item.setText(preview)
                    icon = self.host.table_controller._unit_status_icon(self.current_unit)
                    if icon is not None and not icon.isNull():
                        item.setIcon(icon)
                    else:
                        item.setIcon(QIcon())
        if next_entry:
            self.next_entry()
        else:
            self.refresh_focus(sync_list=False)

    def previous_entry(self) -> None:
        self.move_focus(-1)

    def next_entry(self) -> None:
        self.move_focus(1)

    def move_focus(self, step: int) -> None:
        if not self.host.filtered_units:
            return
        if self.current_unit in self.host.filtered_units:
            index = self.host.filtered_units.index(self.current_unit)
        else:
            index = 0
        self.current_unit = self.host.filtered_units[(index + step) % len(self.host.filtered_units)]
        self.refresh_focus()

    def _ensure_focus_sidebar_minimum_width(self) -> None:
        """ページネーションの桁数に応じてサイドバーの最小幅を更新し、不足していればスプリッターを強制拡張。"""
        btn_w = (
            self.host.button_focus_first.sizeHint().width()
            + self.host.button_focus_prev.sizeHint().width()
            + self.host.button_focus_next.sizeHint().width()
            + self.host.button_focus_last.sizeHint().width()
        )
        spin_w = max(self.host.spin_focus_page_size.minimumWidth(), self.host.spin_focus_page_size.sizeHint().width())
        scrubber_w = self.host.page_scrubber.minimumWidth()

        layout = self.host.frame_files.layout()
        if layout is not None:
            margins = layout.contentsMargins()
            margin_w = margins.left() + margins.right()
        else:
            margin_w = 18
        spacing_w = 2 * 5  # layoutFocusPagination spacing=2, 5 gaps

        needed_w = btn_w + spin_w + scrubber_w + spacing_w + margin_w
        self.host.frame_files.setMinimumWidth(needed_w)

        if self.host.frame_files.isVisible() and self.host.frame_files.width() > 0 and self.host.frame_files.width() < needed_w:
            sizes = self.host.splitter_main.sizes()
            if sizes:
                diff = needed_w - self.host.frame_files.width()
                sizes[0] = needed_w
                if len(sizes) > 1:
                    sizes[1] = max(0, sizes[1] - diff)
                self.host.splitter_main.setSizes(sizes)
