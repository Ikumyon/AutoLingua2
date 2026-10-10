from __future__ import annotations

from collections import Counter, deque
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout

from autolingua2.ir import UnitState
from autolingua2.ir.workspace import UnitView as TranslationUnit, Workspace
from autolingua2.services.translation import TranslationOptions, TranslationService
from autolingua2.services.translation_memory import TranslationMemoryError
from autolingua2.ui.i18n import tr
from autolingua2.ui.language_names import workspace_language_name

if TYPE_CHECKING:
    from autolingua2.ui.main_window import MainWindowController


class MainWindowTranslationController(QObject):
    """翻訳対象の確認と、翻訳サービスの進捗・結果表示を担当する。"""

    def __init__(self, host: MainWindowController) -> None:
        super().__init__(host)
        self.host = host
        self._confirmed_values: dict[tuple[str, str], tuple[Workspace, str, UnitState]] = {}
        self._share_queue: deque[tuple[Workspace, TranslationUnit, bool, str, UnitState]] = deque()
        self._sharing = False
        self.service = TranslationService(
            host.ai_client, host._workspace_is_alive, self._options, self,
        )
        self.service.unit_translated.connect(self._unit_translated)
        self.service.translation_failed.connect(self._translation_failed)
        self.service.progress_changed.connect(self._progress_changed)
        self.service.batch_unit_started.connect(self._batch_unit_started)
        self.service.batch_finished.connect(self._batch_finished)
        self.service.batch_stopped.connect(self._batch_stopped)

    def _options(self, warn: bool = False) -> TranslationOptions | None:
        host = self.host

        def invalid(message: str) -> None:
            if warn:
                QMessageBox.warning(host.window, tr("MainWindow", "AI設定"), tr("MainWindow", message))

        if not host.ai_provider_id:
            invalid("AIプロバイダーが選択されていません。")
            return None
        provider = host.plugins.providers.get(host.ai_provider_id)
        if provider is None:
            invalid("選択中のAIプロバイダーが見つかりません。")
            return None
        api_key = host.ai_api_keys.get(host.ai_provider_id, "")
        if not api_key:
            invalid("APIキーが設定されていません。設定画面で設定してください。")
            return None
        model = host.combo_ai_model.currentText().strip()
        if not model:
            invalid("AIモデルが選択されていません。")
            return None
        source = host.project.source_language or "en"
        target = host.project.target_language
        return TranslationOptions(
            provider, api_key, model, source, target,
            workspace_language_name(host.workspace_service, source)
                if source in host.workspace_service.languages else "",
            workspace_language_name(host.workspace_service, target),
        )

    def _start_batch_translation(self, targets: list[TranslationUnit]) -> None:
        host = self.host
        workspace = host.active_workspace
        if workspace is None or self._options(warn=True) is None:
            return
        valid_targets = [unit for unit in targets if unit.source_text.strip()]
        if not valid_targets:
            QMessageBox.information(host.window, tr("MainWindow", "翻訳"), tr("MainWindow", "翻訳対象の項目がありません。"))
            return
        self.service.start_batch(workspace, valid_targets, host.imported.classification)

    def _stop_batch_translation(self) -> None:
        self.service.stop()

    def _translate_single_unit(self, unit: TranslationUnit) -> None:
        host = self.host
        workspace = host.active_workspace
        if workspace is None:
            return
        options = self._options(warn=True)
        if options is None or not unit.source_text.strip():
            return
        host.window.statusBar().showMessage(tr("MainWindow", f"[{unit.label}] を翻訳中..."), 3000)
        self.service.translate_single(workspace, unit, options)

    def _unit_translated(self, workspace: Workspace, unit: TranslationUnit, batch: bool) -> None:
        host = self.host
        memory_error = self._record_translations(workspace, (unit,))
        if host.active_workspace is not workspace:
            self._show_memory_error(memory_error)
            return
        row = host.filtered_units.index(unit) if unit in host.filtered_units else -1
        if row >= 0:
            host.table_controller._sync_unit_row_content(row, unit)
        elif not batch:
            host.table_controller.refresh_table()
        current_unit = host.focus_controller.current_unit
        if current_unit is not None and current_unit.id == unit.id:
            host.focus_controller.refresh_focus(sync_list=False)
        if not batch:
            host.focus_controller.refresh_focus_unit_list()
            host.window.statusBar().showMessage(tr("MainWindow", f"[{unit.label}] の翻訳が完了しました。"), 4000)
        self._offer_shared_translation(workspace, unit, manual=False)
        self._show_memory_error(memory_error)

    def reset_confirmations(self) -> None:
        self._confirmed_values.clear()
        self._share_queue.clear()

    def remember_confirmation(self, unit: TranslationUnit) -> None:
        workspace = self.host.active_workspace
        if workspace is None:
            return
        key = (workspace.language_code, unit.id)
        previous = self._confirmed_values.get(key)
        if previous is None or previous[0] is not workspace:
            self._confirmed_values[key] = (workspace, unit.target_text, unit.state)

    def confirm_manual_translation(self, unit: TranslationUnit, *, deferred: bool = False) -> None:
        workspace = self.host.active_workspace
        if workspace is None:
            return
        memory_error = self._record_translations(workspace, (unit,))
        self._offer_shared_translation(workspace, unit, manual=True, deferred=deferred)
        self._show_memory_error(memory_error)

    def _record_translations(self, workspace: Workspace, units: Sequence[TranslationUnit]) -> str | None:
        try:
            self.host.workspace_service.record_translations(workspace, units)
        except TranslationMemoryError as exc:
            return str(exc)
        return None

    def _show_memory_error(self, error: str | None) -> None:
        if error is not None:
            self.host.window.statusBar().showMessage(
                tr("MainWindow", "翻訳メモリの保存に失敗しました: {error}").format(error=error), 6000,
            )

    def _offer_shared_translation(
        self, workspace: Workspace, unit: TranslationUnit, *, manual: bool, deferred: bool = False,
    ) -> None:
        key = (workspace.language_code, unit.id)
        confirmed = (workspace, unit.target_text, unit.state)
        previous = self._confirmed_values.get(key)
        self._confirmed_values[key] = confirmed
        if manual and previous is not None and previous[0] is workspace and previous[1:] == confirmed[1:]:
            return
        self._share_queue.append((workspace, unit, manual, unit.target_text, unit.state))
        if deferred:
            # Let the table delegate finish closing its editor before showing a modal dialog.
            QTimer.singleShot(0, self._drain_shared_translations)
        else:
            self._drain_shared_translations()

    def _drain_shared_translations(self) -> None:
        if self._sharing:
            return
        self._sharing = True
        try:
            while self._share_queue:
                workspace, unit, manual, text, state = self._share_queue.popleft()
                if (not self.host._workspace_is_alive(workspace)
                        or unit.target_text != text or unit.state != state):
                    continue
                self._show_shared_translation_dialog(workspace, unit, manual=manual)
        finally:
            self._sharing = False

    def _show_shared_translation_dialog(
        self, workspace: Workspace, unit: TranslationUnit, *, manual: bool,
    ) -> None:
        host = self.host
        peers = host.workspace_service.exact_peers(workspace, unit.id)
        if not peers:
            return
        counts = Counter(peer.state for peer in peers)
        original_text, original_state = unit.target_text, unit.state
        dialog = QDialog(host.window)
        dialog.setWindowTitle(tr("MainWindow", "完全一致する項目への適用"))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(tr("MainWindow", "この訳文を適用する対象を選んでください。"), dialog))
        checkboxes: dict[UnitState, QCheckBox] = {}
        for state, label in (
            (UnitState.UNTRANSLATED, "未翻訳"),
            (UnitState.AI_TRANSLATED, "AIによる翻訳"),
            (UnitState.HUMAN_TRANSLATED, "人間による翻訳"),
            (UnitState.AI_REVIEWED, "AIによる校閲"),
            (UnitState.HUMAN_REVIEWED, "人間による校閲"),
            (UnitState.DOUBTFUL, "疑問あり"),
            (UnitState.LOCKED, "ロック"),
            (UnitState.HIDDEN, "非表示"),
        ):
            checkbox = QCheckBox(tr("MainWindow", "{label}（{count}件）").format(
                label=tr("MainWindow", label), count=counts[state]), dialog)
            checkbox.setEnabled(counts[state] > 0)
            checkbox.setChecked(state == UnitState.UNTRANSLATED and counts[state] > 0)
            checkboxes[state] = checkbox
            layout.addWidget(checkbox)
        buttons = QDialogButtonBox(dialog)
        apply_button = buttons.addButton(tr("MainWindow", "適用する"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("MainWindow", "適用しない"), QDialogButtonBox.ButtonRole.RejectRole)

        def update_apply_button() -> None:
            apply_button.setEnabled(any(checkbox.isChecked() for checkbox in checkboxes.values()))

        for checkbox in checkboxes.values():
            checkbox.toggled.connect(update_apply_button)
        update_apply_button()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        states = {state for state, checkbox in checkboxes.items() if checkbox.isChecked()}
        dialog.deleteLater()
        if (not accepted or not host._workspace_is_alive(workspace)
                or unit.target_text != original_text or unit.state != original_state):
            return
        changed = host.workspace_service.share_translation(workspace, unit.id, states, manual=manual)
        memory_error = self._record_translations(workspace, changed)
        for peer in changed:
            self._confirmed_values[(workspace.language_code, peer.id)] = (workspace, peer.target_text, peer.state)
        if host.active_workspace is workspace:
            changed_ids = {peer.id for peer in changed}
            for row, visible_unit in enumerate(host.filtered_units):
                if visible_unit.id in changed_ids:
                    host.table_controller._sync_unit_row_content(row, visible_unit)
            host.focus_controller.refresh_focus(sync_list=False)
            host.focus_controller.refresh_focus_unit_list()
            host._update_status_bar_counts()
        self._show_memory_error(memory_error)

    def _translation_failed(self, unit: TranslationUnit, error: str, batch: bool) -> None:
        text = f"[{unit.label}] 翻訳失敗: {error}" if batch else f"翻訳エラー: {error}"
        self.host.window.statusBar().showMessage(tr("MainWindow", text), 3000 if batch else 6000)

    def _progress_changed(self, completed: int, total: int) -> None:
        self.host.progress.setMaximum(total)
        self.host.progress.setValue(completed)
        self.host.progress.setVisible(True)
        self._update_translation_button_state()

    def _batch_unit_started(self, unit: TranslationUnit, position: int, total: int) -> None:
        self.host.window.statusBar().showMessage(
            tr("MainWindow", f"[{unit.label}] を翻訳中... ({position}/{total})")
        )

    def _batch_finished(self, completed: int, total: int) -> None:
        self.host.progress.setVisible(False)
        self.host.focus_controller.refresh_focus_unit_list()
        self.host._update_status_bar_counts()
        self._update_translation_button_state()
        self.host.window.statusBar().showMessage(
            tr("MainWindow", f"翻訳が完了しました ({completed}/{total} 件)。"), 5000,
        )

    def _batch_stopped(self) -> None:
        self.host.progress.setVisible(False)
        self._update_translation_button_state()
        self.host.window.statusBar().showMessage(tr("MainWindow", "翻訳を停止しました。"), 4000)

    def _update_translation_button_state(self) -> None:
        if self.service.running:
            self.host.button_translate_all.setText(tr("MainWindow", "■ 停止"))
            self.host.button_translate_all.setEnabled(True)
            self.host.action_stop_translation.setEnabled(True)
            return

        self.host.action_stop_translation.setEnabled(False)
        is_workspace_active = self.host.active_workspace is not None
        selected_rows = self.host.table_controller._get_selected_rows()
        if selected_rows:
            count = len(selected_rows)
            self.host.button_translate_all.setText(tr("MainWindow", f"▶ 選択項目を翻訳 ({count}件)"))
        else:
            self.host.button_translate_all.setText(tr("MainWindow", "▶ 全翻訳"))
        self.host.button_translate_all.setEnabled(is_workspace_active)

    def _on_translate_button_clicked(self) -> None:
        if self.service.running:
            self._stop_batch_translation()
            return

        selected_rows = self.host.table_controller._get_selected_rows()
        if selected_rows:
            self._handle_selected_translation(selected_rows)
        else:
            untranslated = [u for u in self.host.units if u.state == UnitState.UNTRANSLATED and u.source_text.strip()]
            self._start_batch_translation(untranslated)

    def _handle_selected_translation(self, selected_rows: list[int]) -> None:
        selected_units = [self.host.filtered_units[r] for r in selected_rows if 0 <= r < len(self.host.filtered_units)]
        valid_units = [u for u in selected_units if u.source_text.strip()]
        if not valid_units:
            QMessageBox.information(self.host.window, tr("MainWindow", "翻訳"), tr("MainWindow", "選択された行に有効な原文がありません。"))
            return

        untranslated = [u for u in valid_units if u.state == UnitState.UNTRANSLATED]
        already_translated = [u for u in valid_units if u.state != UnitState.UNTRANSLATED]

        if not already_translated:
            self._start_batch_translation(valid_units)
            return

        msg_box = QMessageBox(self.host.window)
        msg_box.setWindowTitle(tr("MainWindow", "翻訳対象の確認"))
        msg_box.setIcon(QMessageBox.Icon.Question)

        if not untranslated:
            msg_box.setText(
                tr("MainWindow", f"選択されたすべての項目（{len(valid_units)} 件）はすでに翻訳済みです。\n上書きして再翻訳を実行しますか？")
            )
            btn_overwrite = msg_box.addButton(tr("MainWindow", "再翻訳 (上書き)"), QMessageBox.ButtonRole.AcceptRole)
            btn_cancel = msg_box.addButton(tr("MainWindow", "キャンセル"), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_overwrite)
            msg_box.exec()

            if msg_box.clickedButton() == btn_overwrite:
                self._start_batch_translation(valid_units)
        else:
            msg_box.setText(
                tr(
                    "MainWindow",
                    f"選択された {len(valid_units)} 件のうち、すでに翻訳済みの項目が {len(already_translated)} 件あります。\nどのように翻訳を実行しますか？"
                )
            )
            btn_overwrite = msg_box.addButton(tr("MainWindow", "すべて再翻訳 (上書き)"), QMessageBox.ButtonRole.AcceptRole)
            btn_untranslated_only = msg_box.addButton(
                tr("MainWindow", f"未翻訳のみ翻訳 ({len(untranslated)}件)"), QMessageBox.ButtonRole.ActionRole
            )
            btn_cancel = msg_box.addButton(tr("MainWindow", "キャンセル"), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_untranslated_only)
            msg_box.exec()

            if msg_box.clickedButton() == btn_overwrite:
                self._start_batch_translation(valid_units)
            elif msg_box.clickedButton() == btn_untranslated_only:
                self._start_batch_translation(untranslated)

    def _start_batch_translation_all(self) -> None:
        untranslated = [u for u in self.host.units if u.state == UnitState.UNTRANSLATED and u.source_text.strip()]
        self._start_batch_translation(untranslated)

    def _start_batch_translation_selected(self) -> None:
        selected_rows = self.host.table_controller._get_selected_rows()
        if not selected_rows:
            QMessageBox.information(self.host.window, tr("MainWindow", "翻訳"), tr("MainWindow", "行が選択されていません。"))
            return
        self._handle_selected_translation(selected_rows)

    def _start_batch_translation_untranslated(self) -> None:
        untranslated = [u for u in self.host.units if u.state == UnitState.UNTRANSLATED and u.source_text.strip()]
        self._start_batch_translation(untranslated)
