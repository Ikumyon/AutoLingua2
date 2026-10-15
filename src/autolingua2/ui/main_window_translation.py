from __future__ import annotations

from autolingua2.ui.i18n import translation_source

from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout

from autolingua2.ir import UnitState
from autolingua2.ir.workspace import UnitView as TranslationUnit, Workspace, WorkspaceUnit, is_pending_translation
from autolingua2.services.translation import TranslationOptions, TranslationService, tone_context
from autolingua2.services.translation import TranslationTextContext
from autolingua2.services.translation_execution import TranslationModel
from autolingua2.ir.filter_rules import TagRules
from autolingua2.ir.translation import ModelSelection, TranslationTextRules
from autolingua2.plugins.contracts import TranslationTextAdapter
from autolingua2.services.filter_rules import get_filter_config
from autolingua2.ir.tone import ToneItem
from autolingua2.services.translation_memory import TranslationMemoryError
from autolingua2.ui.i18n import tr
from autolingua2.ui.language_names import workspace_language_name
from autolingua2.ui.dialogs.translation_tone import TranslationToneDialog

if TYPE_CHECKING:
    from autolingua2.ui.main_window import MainWindowController


class MainWindowTranslationController(QObject):
    """翻訳対象の確認と、翻訳サービスの進捗・結果表示を担当する。"""

    def __init__(self, host: MainWindowController) -> None:
        super().__init__(host)
        self.host = host
        self._confirmed_values: dict[tuple[str, str], tuple[Workspace, str, UnitState, ToneItem | None]] = {}
        self._share_queue: deque[tuple[Workspace, TranslationUnit, bool, str, UnitState, TranslationOptions | None, ToneItem | None, set[str] | None, bool]] = deque()
        self._sharing = False
        self._deferred_confirmations: dict[tuple[str, str], tuple[Workspace, TranslationUnit, str, UnitState | None]] = {}
        self._confirming_units: set[tuple[str, str]] = set()
        self.service = TranslationService(
            host.ai_client, host._workspace_is_alive, self._options, self,
            get_tone_context=lambda unit: tone_context(host.imported, unit),
        )
        self.service.unit_translated.connect(self._unit_translated)
        self.service.translation_failed.connect(self._translation_failed)
        self.service.progress_changed.connect(self._progress_changed)
        self.service.batch_unit_started.connect(self._batch_unit_started)
        self.service.activity_changed.connect(self._activity_changed)
        self.service.memory_failed.connect(self._show_memory_error)
        self.service.batch_finished.connect(self._batch_finished)
        self.service.batch_stopped.connect(self._batch_stopped)

    def _options(self, warn: bool = False) -> TranslationOptions | None:
        host = self.host

        def invalid(message: str) -> None:
            if warn:
                QMessageBox.warning(host.window, tr("MainWindow", "AI設定"), tr("MainWindow", message))

        def selected_model(selection: ModelSelection | None, label: str) -> TranslationModel | None:
            if selection is None:
                invalid(f"{label}モデルが未設定です。設定 → 翻訳で選択してください。")
                return None
            provider = host.plugins.providers.get(selection.provider_id)
            if provider is None or not any(item.enabled and item.model == selection.model_id
                                          for item in host.ai_settings.models.get(selection.provider_id, [])):
                invalid(f"{label}モデルが利用できません。設定 → 翻訳を確認してください。")
                return None
            api_key = host.ai_settings.api_keys.get(selection.provider_id, "")
            if not api_key:
                invalid(f"{label}モデルのAPIキーが未設定です。設定 → AIで設定してください。")
                return None
            return TranslationModel(provider, api_key, selection.model_id)

        high, low = selected_model(host.ai_settings.high_model, "高"), selected_model(host.ai_settings.low_model, "低")
        if high is None or low is None:
            return None
        source = host.project.source_language
        target = host.project.target_language
        try:
            context = self._text_context()
        except ValueError as exc:
            invalid(str(exc))
            return None
        return TranslationOptions(
            high, low, source, target, context,
            workspace_language_name(host.workspace_service, source)
                if source in host.workspace_service.languages else "",
            workspace_language_name(host.workspace_service, target),
            tone=next((tone for tone in host.tone_choices if tone.id == host.selected_tone_id), None),
            tone_items=tuple(tone for tone in host.tone_choices if isinstance(tone, ToneItem)),
            low_model_range=host.ai_settings.low_model_range, concurrency=host.ai_settings.concurrency,
        )

    def _text_context(self) -> TranslationTextContext:
        host = self.host
        adapter = host.plugins.parsers.get(host.project.adapter_id)
        if adapter is None or not host.project.game_id:
            raise ValueError("翻訳対象のゲーム情報がありません。")
        terms = tuple(host.glossary_store.effective_terms(
            host.glossary_choices, host.selected_glossary_id, host.project.source_language, host.project.target_language,
        )) if host.selected_glossary_id else ()
        sentences = adapter.translation_text_rules if isinstance(adapter, TranslationTextAdapter) else TranslationTextRules()
        return TranslationTextContext(host.project.adapter_id, host.project.game_id,
                                      TagRules(get_filter_config(adapter, host.project.game_id)), sentences, terms)

    def _activity_changed(self, workspace: Workspace, unit: TranslationUnit, active: bool) -> None:
        host = self.host
        if host.active_workspace is workspace:
            if active:
                host.target_text_delegate.cancel_edit(unit)
            host.focus_controller.refresh_unit_status(unit)
            if unit in host.filtered_units:
                host.table_controller._sync_unit_row_content(host.filtered_units.index(unit), unit)
            self._update_translation_button_state()

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
        host.window.statusBar().showMessage(tr("MainWindow", "[{label}] を翻訳中...").format(label=unit.label), 3000)
        self.service.translate_single(workspace, unit, options)

    def _unit_translated(self, workspace: Workspace, unit: TranslationUnit, batch: bool,
                         *, eligible_ids: set[str] | None = None) -> None:
        host = self.host
        host.overview_controller.invalidate()
        if host.active_workspace is not workspace:
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
            host.window.statusBar().showMessage(tr("MainWindow", "[{label}] の翻訳が完了しました。").format(label=unit.label), 4000)
            self._offer_shared_translation(workspace, unit, manual=False,
                                           options=self.service.completed_options if eligible_ids is None else None,
                                           eligible_ids=eligible_ids,
                                           offer_similar=eligible_ids is not None or not self.service.completed_with_reference)
        else:
            self._confirmed_values[(workspace.language_code, unit.id)] = (
                workspace, unit.target_text, unit.state, workspace.records[unit.id].tone,
            )

    def reset_confirmations(self) -> None:
        self.service.stop()
        self._deferred_confirmations.clear()
        self._confirmed_values.clear()
        self._share_queue.clear()

    def remember_confirmation(self, unit: TranslationUnit) -> None:
        workspace = self.host.active_workspace
        if workspace is None:
            return
        key = (workspace.language_code, unit.id)
        previous = self._confirmed_values.get(key)
        if previous is None or previous[0] is not workspace:
            record = workspace.records[unit.id]
            pending = record.pending_confirmation
            target, tone = ((pending.target_text, pending.tone) if pending is not None
                            else (record.target_text, record.tone))
            self._confirmed_values[key] = (workspace, target, record.state, tone)

    def _workspace_for_unit(self, unit: TranslationUnit) -> Workspace | None:
        workspace = self.host.active_workspace
        if (workspace is None or not isinstance(unit, WorkspaceUnit)
                or unit.record.translating or workspace.records.get(unit.id) is not unit.record
                or not self.host._workspace_is_alive(workspace)):
            return None
        return workspace

    def update_draft(self, unit: TranslationUnit, display_text: str, *, sync_target: bool = True) -> bool:
        workspace = self._workspace_for_unit(unit)
        if workspace is None or display_text == self.host._expand_display_text(unit.target_text):
            return False
        target = self.host._collapse_display_text(display_text)
        if not self.host.workspace_service.update_translation_draft(workspace, unit.id, target):
            return False
        self.remember_confirmation(unit)
        if unit in self.host.filtered_units:
            row = self.host.filtered_units.index(unit)
            self.host.table_controller._sync_unit_row_content(row, unit, sync_target=sync_target)
        self.host.focus_controller.refresh_unit_status(unit)
        self.host._update_status_bar_counts()
        return True

    def cancel_deferred_confirmation(self, unit: TranslationUnit) -> None:
        workspace = self._workspace_for_unit(unit)
        if workspace is not None:
            self._deferred_confirmations.pop((workspace.language_code, unit.id), None)

    def refresh_after_edit(self, workspace: Workspace) -> None:
        self.host.overview_controller.invalidate()
        if (self.host.active_workspace is workspace and self.host._workspace_is_alive(workspace)
                and not self._deferred_confirmations and not self._confirming_units
                and not self.host.target_text_delegate.has_editor and not self.host.status_delegate.has_editor
                and not self.host.table_controller.row_menu_open):
            self.host.apply_filters()

    def discard_draft(self, unit: TranslationUnit) -> None:
        workspace = self._workspace_for_unit(unit)
        if workspace is None:
            return
        self.cancel_deferred_confirmation(unit)
        self.host.target_text_delegate.cancel_edit(unit)
        if self.host.workspace_service.discard_translation_draft(workspace, unit.id):
            self._confirmed_values.pop((workspace.language_code, unit.id), None)
            self.remember_confirmation(unit)
            self.host.apply_filters()

    def confirm_manual_translation(self, unit: TranslationUnit, *, target_text: str,
                                   state: UnitState | None = None, deferred: bool = False) -> bool:
        workspace = self._workspace_for_unit(unit)
        if workspace is None:
            return False
        key = (workspace.language_code, unit.id)
        self.cancel_deferred_confirmation(unit)
        if deferred:
            request = (workspace, unit, target_text, state)
            self._deferred_confirmations[key] = request

            def confirm() -> None:
                if self._deferred_confirmations.get(key) is not request:
                    return
                del self._deferred_confirmations[key]
                try:
                    self._confirm_manual_translation(workspace, unit, target_text, state)
                finally:
                    self.refresh_after_edit(workspace)

            QTimer.singleShot(0, confirm)
            return False
        return self._confirm_manual_translation(workspace, unit, target_text, state)

    def _confirm_manual_translation(self, workspace: Workspace, unit: TranslationUnit,
                                    target_text: str, state: UnitState | None) -> bool:
        key = (workspace.language_code, unit.id)
        if self._workspace_for_unit(unit) is not workspace or key in self._confirming_units:
            return False
        self._confirming_units.add(key)
        try:
            return self._run_manual_confirmation(workspace, unit, target_text, state)
        finally:
            self._confirming_units.discard(key)

    def _run_manual_confirmation(self, workspace: Workspace, unit: TranslationUnit,
                                 target_text: str, state: UnitState | None) -> bool:
        host = self.host
        record = workspace.records[unit.id]
        if record.target_text != target_text:
            return False
        desired = state if state is not None else UnitState.HUMAN_TRANSLATED if target_text.strip() else UnitState.UNTRANSLATED
        tones = [tone for tone in host.tone_choices if isinstance(tone, ToneItem)]
        if not tones:
            QMessageBox.warning(host.window, tr("MainWindow", "口調"),
                                tr("MainWindow", "個別口調を登録してから確定してください。"))
            return False
        before = (record.target_text, record.state, record.tone, record.pending_confirmation)
        dialog = TranslationToneDialog(unit.source_text, target_text, tones, host.window)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        tone = dialog.selected_tone()
        dialog.deleteLater()
        if not accepted or tone is None:
            return False
        if (self._workspace_for_unit(unit) is not workspace
                or (record.target_text, record.state, record.tone, record.pending_confirmation) != before):
            return False
        pending = record.pending_confirmation
        if pending is not None:
            self._confirmed_values[(workspace.language_code, unit.id)] = (
                workspace, pending.target_text, record.state, pending.tone,
            )
        else:
            self.remember_confirmation(unit)
        host.workspace_service.confirm_translation(workspace, unit.id, target_text, desired, tone)
        if host.active_workspace is workspace:
            row = host.filtered_units.index(unit) if unit in host.filtered_units else -1
            if row >= 0:
                host.table_controller._sync_unit_row_content(row, unit)
            if host.focus_controller.current_unit is unit:
                host.focus_controller.refresh_focus(sync_list=False)
        self._offer_shared_translation(workspace, unit, manual=True)
        host.focus_controller.refresh_unit_status(unit)
        host._update_status_bar_counts()
        return True

    def _show_memory_error(self, error: str | None) -> None:
        if error is not None:
            self.host.window.statusBar().showMessage(
                tr("MainWindow", "翻訳メモリの保存に失敗しました: {error}").format(error=error), 6000,
            )

    def _offer_shared_translation(
        self, workspace: Workspace, unit: TranslationUnit, *, manual: bool,
        options: TranslationOptions | None = None,
        eligible_ids: set[str] | None = None,
        offer_similar: bool = True,
    ) -> None:
        key = (workspace.language_code, unit.id)
        tone = workspace.records[unit.id].tone
        confirmed = (workspace, unit.target_text, unit.state, tone)
        previous = self._confirmed_values.get(key)
        self._confirmed_values[key] = confirmed
        if manual and previous is not None and previous[0] is workspace and previous[1:] == confirmed[1:]:
            return
        self._share_queue.append((workspace, unit, manual, unit.target_text, unit.state, options, tone,
                                  eligible_ids, offer_similar))
        self._drain_shared_translations()

    def _drain_shared_translations(self) -> None:
        if self._sharing:
            return
        self._sharing = True
        try:
            while self._share_queue:
                workspace, unit, manual, text, state, options, tone, eligible_ids, offer_similar = self._share_queue.popleft()
                if (not self.host._workspace_is_alive(workspace)
                        or unit.target_text != text or unit.state != state or workspace.records[unit.id].tone != tone):
                    continue
                self._show_shared_translation_dialog(
                    workspace, unit, manual=manual, options=options, eligible_ids=eligible_ids,
                )
                if offer_similar:
                    self._show_similar_translation_dialog(
                        workspace, unit, manual=manual, options=options, eligible_ids=eligible_ids,
                    )
        finally:
            self._sharing = False

    def _show_shared_translation_dialog(
        self, workspace: Workspace, unit: TranslationUnit, *, manual: bool,
        options: TranslationOptions | None = None,
        eligible_ids: set[str] | None = None,
    ) -> None:
        host = self.host
        peers = [peer for peer in host.workspace_service.exact_peers(workspace, unit.id)
                 if not peer.locked and not peer.hidden and not is_pending_translation(peer)
                 and not self.service.is_translating(workspace, peer.id)]
        if eligible_ids is not None:
            peers = [peer for peer in peers if peer.id in eligible_ids]
        if not manual and options is not None:
            peers = self.service.matching_tone_peers(peers, workspace.records[unit.id].tone,
                                                   options.tone, options.tone_items)
        if not peers or not unit.target_text.strip():
            return
        original_text, original_state, original_tone = unit.target_text, unit.state, workspace.records[unit.id].tone
        states = self._select_peer_states(peers, similar=False, manual=manual, reference_text=original_text)
        if (states is None or not host._workspace_is_alive(workspace)
                or unit.target_text != original_text or unit.state != original_state
                or workspace.records[unit.id].tone != original_tone):
            return
        try:
            context = self._text_context()
            changed = host.workspace_service.share_translation(
                workspace, unit.id, states, manual=manual, rules=context.tags, eligible_ids={
                    peer.id for peer in peers if not self.service.is_translating(workspace, peer.id)
                },
            )
        except ValueError as exc:
            host.window.statusBar().showMessage(str(exc), 6000)
            return
        memory_error = None
        if changed:
            try:
                self.service.record_shared(workspace, unit, host.project.source_language, context)
            except TranslationMemoryError as exc:
                memory_error = str(exc)
        for peer in changed:
            self._confirmed_values[(workspace.language_code, peer.id)] = (
                workspace, peer.target_text, peer.state, workspace.records[peer.id].tone)
        if host.active_workspace is workspace:
            changed_ids = {peer.id for peer in changed}
            for row, visible_unit in enumerate(host.filtered_units):
                if visible_unit.id in changed_ids:
                    host.table_controller._sync_unit_row_content(row, visible_unit)
            host.focus_controller.refresh_focus(sync_list=False)
            host.focus_controller.refresh_focus_unit_list()
            host._update_status_bar_counts()
        self._show_memory_error(memory_error)

    def _select_peer_states(
        self, peers: Sequence[TranslationUnit], *, similar: bool, manual: bool, reference_text: str,
    ) -> set[UnitState] | None:
        dialog = QDialog(self.host.window)
        dialog.setWindowTitle(tr("MainWindow", translation_source('MainWindow', '類似する項目のAI翻訳') if similar else translation_source('MainWindow', '完全一致する項目への適用')))
        layout = QVBoxLayout(dialog)
        message = (
            translation_source('MainWindow', "この訳文を参考に、類似する項目をAIが個別に翻訳します。\n結果の状態は「AIによる翻訳」になります。")
            if similar else
            translation_source('MainWindow', "この訳文を適用する対象を選んでください。\n適用した項目の状態は「人間による翻訳」になります。")
            if manual else
            translation_source('MainWindow', "この訳文を適用する対象を選んでください。\n適用した項目の状態は「AIによる翻訳」になります。")
        )
        layout.addWidget(QLabel(tr("MainWindow", message), dialog))
        if similar:
            reference_label = QLabel(tr("MainWindow", "参考訳：{text}").format(text=reference_text), dialog)
            reference_label.setWordWrap(True)
            reference_label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(reference_label)
        counts = Counter(peer.state for peer in peers)
        checkboxes: dict[UnitState, QCheckBox] = {}
        for state, label in (
            (UnitState.UNTRANSLATED, translation_source('MainWindow', "未翻訳")),
            (UnitState.AI_TRANSLATED, translation_source('MainWindow', "AIによる翻訳")),
            (UnitState.HUMAN_TRANSLATED, translation_source('MainWindow', "人間による翻訳")),
            (UnitState.AI_REVIEWED, translation_source('MainWindow', "AIによる校閲")),
            (UnitState.HUMAN_REVIEWED, translation_source('MainWindow', "人間による校閲")),
            (UnitState.DOUBTFUL, translation_source('MainWindow', "疑問あり")),
        ):
            checkbox = QCheckBox(tr("MainWindow", "{label}（{count}件）").format(
                label=tr("MainWindow", label), count=counts[state]), dialog)
            checkbox.setEnabled(counts[state] > 0)
            checkbox.setChecked(state == UnitState.UNTRANSLATED and counts[state] > 0)
            checkboxes[state] = checkbox
            layout.addWidget(checkbox)
        layout.addWidget(QLabel(tr("MainWindow", "ロック・非表示・処理中・編集中の項目は除外"), dialog))
        buttons = QDialogButtonBox(dialog)
        apply_button = buttons.addButton(tr("MainWindow", translation_source('MainWindow', 'AI翻訳する') if similar else translation_source('MainWindow', '適用する')),
                                         QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("MainWindow", translation_source('MainWindow', '翻訳しない') if similar else translation_source('MainWindow', '適用しない')),
                          QDialogButtonBox.ButtonRole.RejectRole)

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
        return states if accepted else None

    def _show_similar_translation_dialog(
        self, workspace: Workspace, unit: TranslationUnit, *, manual: bool,
        options: TranslationOptions | None, eligible_ids: set[str] | None,
    ) -> None:
        host = self.host
        if not host._workspace_is_alive(workspace) or not unit.target_text.strip():
            return
        original_text, original_state, original_tone = unit.target_text, unit.state, workspace.records[unit.id].tone
        peers = [peer for peer in host.workspace_service.similar_peers(workspace, unit.id)
                 if not peer.locked and not peer.hidden and not is_pending_translation(peer)
                 and not self.service.is_translating(workspace, peer.id)
                 and (eligible_ids is None or peer.id in eligible_ids)]
        options = options if options is not None else self._options()
        if options is not None:
            if manual:
                options = replace(options, tone=original_tone)
            peers = self.service.matching_tone_peers(peers, original_tone, options.tone, options.tone_items)
        if not peers:
            return
        states = self._select_peer_states(peers, similar=True, manual=manual, reference_text=original_text)
        if (states is None or not host._workspace_is_alive(workspace)
                or unit.target_text != original_text or unit.state != original_state
                or workspace.records[unit.id].tone != original_tone):
            return
        if options is None:
            self._options(warn=True)
            return
        targets = [peer for peer in peers if peer.state in states and not is_pending_translation(peer)]
        self.service.translate_similar(workspace, unit, targets, options)

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
            tr("MainWindow", "[{label}] を翻訳中... ({position}/{total})").format(label=unit.label, position=position, total=total)
        )

    def _batch_finished(self, succeeded: int, failed: int, total: int) -> None:
        self.host.progress.setVisible(False)
        self.host.focus_controller.refresh_focus_unit_list()
        self.host._update_status_bar_counts()
        self._update_translation_button_state()
        self.host.window.statusBar().showMessage(
            tr("MainWindow", "翻訳が完了しました（成功 {succeeded}件／失敗 {failed}件／全 {total}件）。").format(
                succeeded=succeeded, failed=failed, total=total,
            ), 5000,
        )

    def _batch_stopped(self) -> None:
        self.host.progress.setVisible(False)
        self._update_translation_button_state()
        self.host.window.statusBar().showMessage(tr("MainWindow", "翻訳を停止しました。"), 4000)

    def _update_translation_button_state(self) -> None:
        if self.service.busy:
            self.host.button_translate_all.setText(tr("MainWindow", "■ 停止"))
            self.host.button_translate_all.setEnabled(True)
            self.host.action_stop_translation.setEnabled(True)
            return

        self.host.action_stop_translation.setEnabled(False)
        is_workspace_active = self.host.active_workspace is not None
        selected_rows = self.host.table_controller._get_selected_rows()
        if selected_rows:
            count = len(selected_rows)
            self.host.button_translate_all.setText(tr("MainWindow", "▶ 選択項目を翻訳 ({count}件)").format(count=count))
        else:
            self.host.button_translate_all.setText(tr("MainWindow", "▶ 全翻訳"))
        self.host.button_translate_all.setEnabled(is_workspace_active)

    def _on_translate_button_clicked(self) -> None:
        if self.service.busy:
            self._stop_batch_translation()
            return

        selected_rows = self.host.table_controller._get_selected_rows()
        if selected_rows:
            self._handle_selected_translation(selected_rows)
        else:
            untranslated = [u for u in self.host.units if not is_pending_translation(u)
                            and u.state == UnitState.UNTRANSLATED and u.source_text.strip()]
            self._start_batch_translation(untranslated)

    def _handle_selected_translation(self, selected_rows: list[int]) -> None:
        selected_units = [self.host.filtered_units[r] for r in selected_rows if 0 <= r < len(self.host.filtered_units)]
        valid_units = [u for u in selected_units if u.source_text.strip()]
        if not valid_units:
            QMessageBox.information(self.host.window, tr("MainWindow", "翻訳"), tr("MainWindow", "選択された行に有効な原文がありません。"))
            return

        untranslated = [u for u in valid_units if not is_pending_translation(u) and u.state == UnitState.UNTRANSLATED]
        already_translated = [u for u in valid_units if is_pending_translation(u) or u.state != UnitState.UNTRANSLATED]

        if not already_translated:
            self._start_batch_translation(valid_units)
            return

        msg_box = QMessageBox(self.host.window)
        msg_box.setWindowTitle(tr("MainWindow", "翻訳対象の確認"))
        msg_box.setIcon(QMessageBox.Icon.Question)

        if not untranslated:
            msg_box.setText(
                tr("MainWindow", "選択されたすべての項目（{count} 件）はすでに翻訳済みです。\n上書きして再翻訳を実行しますか？").format(count=len(valid_units))
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
                tr("MainWindow", "未翻訳のみ翻訳 ({count}件)").format(count=len(untranslated)), QMessageBox.ButtonRole.ActionRole
            )
            btn_cancel = msg_box.addButton(tr("MainWindow", "キャンセル"), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(btn_untranslated_only)
            msg_box.exec()

            if msg_box.clickedButton() == btn_overwrite:
                self._start_batch_translation(valid_units)
            elif msg_box.clickedButton() == btn_untranslated_only:
                self._start_batch_translation(untranslated)

    def _start_batch_translation_all(self) -> None:
        untranslated = [u for u in self.host.units if not is_pending_translation(u)
                        and u.state == UnitState.UNTRANSLATED and u.source_text.strip()]
        self._start_batch_translation(untranslated)

    def _start_batch_translation_selected(self) -> None:
        selected_rows = self.host.table_controller._get_selected_rows()
        if not selected_rows:
            QMessageBox.information(self.host.window, tr("MainWindow", "翻訳"), tr("MainWindow", "行が選択されていません。"))
            return
        self._handle_selected_translation(selected_rows)

    def _start_batch_translation_untranslated(self) -> None:
        untranslated = [u for u in self.host.units if not is_pending_translation(u)
                        and u.state == UnitState.UNTRANSLATED and u.source_text.strip()]
        self._start_batch_translation(untranslated)
