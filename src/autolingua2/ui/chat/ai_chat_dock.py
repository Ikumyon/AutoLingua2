from __future__ import annotations

from autolingua2.ui.resources.i18n import translation_source

from collections.abc import Callable, Mapping
import json
from base64 import b64decode
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDockWidget, QFileDialog, QFormLayout, QLabel, QMainWindow, QMenu,
    QPushButton, QVBoxLayout, QWidget, QWidgetAction,
)

from autolingua2.services.ai.ai_chat import AiChatSession, ChatFile, ChatReference
from autolingua2.services.operations.application_operations import ApplicationOperations
from autolingua2.services.ai.chat_references import ChatAttachment
from autolingua2.ui.components.chat_composer import ChatComposer
from autolingua2.ui.components.chat_web_view import ChatWebView
from autolingua2.services.ai_providers.base import BaseHttpTranslator
from autolingua2.services.ai_providers.registry import ProviderRegistry
from autolingua2.services.settings.settings_store import AiSettings, load_voice_input_provider
from autolingua2.services.ai.voice_input import VoiceInputService
from autolingua2.services.ai.voice_input_contract import VoiceInputProvider
from autolingua2.ui.components.combo_menu_button import ComboMenuButton
from autolingua2.ui.dialogs.base import require_child
from autolingua2.ui.resources.i18n import tr
from autolingua2.ui.main.operation_panel import show_details


class AiChatDockController(QObject):
    def __init__(
        self, window: QMainWindow, registry: ProviderRegistry, settings: Callable[[], AiSettings],
        current_file: Callable[[], ChatFile | None],
        selected_references: Callable[[], tuple[ChatReference, ...]],
        selection_origin: Callable[[], str],
        *, voice_input_providers: Mapping[str, VoiceInputProvider],
        operations: ApplicationOperations,
        get_icon: Callable[[str], QIcon],
        chat_icon: Callable[[str], QIcon],
    ) -> None:
        super().__init__(window)
        self.window = window
        self.registry = registry
        self.settings = settings
        self.selected_references = selected_references
        self.selection_origin = selection_origin
        self._get_icon = get_icon
        self._chat_icon = chat_icon
        self._clear_on_completion = False
        self.operations = operations
        self.current_file = current_file
        self.session = AiChatSession(operations, self)
        self.voice_input = VoiceInputService(voice_input_providers, self)
        self.dock = require_child(window, QDockWidget, "dockAiChat")
        self.action = require_child(window, QAction, "actionToggleAiChat")
        self.history = require_child(window, ChatWebView, "scrollChatHistory")
        self.history.markdown_icon = self._icon_data(self._get_icon("markdown"))
        self.input = require_child(window, ChatComposer, "editChatMessage")
        self.input.send_requested.connect(self._send)
        self.input.reference_requested.connect(self._view_reference)
        self.input.reference_error.connect(lambda error: self._append("error", error))
        self.history.ready.connect(self._web_ready)
        self.history.action_requested.connect(self._web_action)
        self.model_button = require_child(window, ComboMenuButton, "buttonChatModel")
        control_height = require_child(window, QComboBox, "comboTargetLanguage").sizeHint().height()
        self.attach_button = require_child(window, QPushButton, "buttonChatAttach")
        self.attach_button.setFixedSize(control_height, control_height)
        self.attach_button.clicked.connect(self._attach_files)
        self.model_button.setFixedHeight(control_height)
        self.send_button = require_child(window, QPushButton, "buttonChatSend")
        self.send_button.setFixedSize(control_height, control_height)
        send_icon_size = max(1, control_height - 8)
        self.send_button.setIconSize(QSize(send_icon_size, send_icon_size))
        self.voice_button = require_child(window, QPushButton, "buttonChatVoice")
        self.voice_button.setFixedSize(control_height, control_height)
        self.voice_button.setIconSize(QSize(send_icon_size, send_icon_size))
        self.new_button = require_child(window, QPushButton, "buttonChatNew")
        self.status = require_child(window, QLabel, "labelChatStatus")
        self.scope_combo = QComboBox(window)
        self.scope_combo.setToolTip(tr("AiChat", "操作の対象範囲"))
        for label, value in ((translation_source('AiChat', "プロジェクト全体"), "project"), (translation_source('AiChat', "現在のファイル"), "file"), (translation_source('AiChat', "選択行"), "selection")):
            self.scope_combo.addItem(tr("AiChat", label), value)
        self.execution_combo = QComboBox(window)
        self.execution_combo.addItem(tr("AiChat", "提案を確認"), True)
        self.execution_combo.addItem(tr("AiChat", "依頼どおり実行"), False)
        self.execution_combo.currentIndexChanged.connect(self._execution_changed)
        options = require_child(window, QPushButton, "buttonChatOptions")
        menu = QMenu(options)
        form = QWidget(menu)
        form_layout = QFormLayout(form)
        self._scope_label = QLabel(tr("AiChat", "操作の対象範囲"), form)
        self._execution_label = QLabel(tr("AiChat", "実行方法"), form)
        form_layout.addRow(self._scope_label, self.scope_combo)
        form_layout.addRow(self._execution_label, self.execution_combo)
        form_action = QWidgetAction(menu)
        form_action.setDefaultWidget(form)
        menu.addAction(form_action)
        options.setMenu(menu)
        operations.operation_changed.connect(self._operation_changed)
        operations.job_changed.connect(self._job_changed)
        self._visible = True
        self._changing_visibility = False
        self._choice: tuple[str, str] | None = None
        self._choices: dict[tuple[str, str], tuple[str, str]] = {}
        self._model_actions: dict[tuple[str, str], QAction] = {}
        self._refresh_pending = False
        self.refresh_choices()
        self.model_button.installEventFilter(self)
        self.send_button.clicked.connect(lambda: self._send())
        self.voice_button.clicked.connect(self._toggle_voice_input)
        self.new_button.clicked.connect(self.reset)
        self.action.triggered.connect(self._toggle)
        self.dock.toggleViewAction().toggled.connect(self._dock_toggled)
        self.session.message.connect(self._append)
        self.session.busy_changed.connect(self._busy_changed)
        self.session.completed.connect(self._completed)
        self.voice_input.changed.connect(self._update_input_controls)
        self.voice_input.text_recognized.connect(self._insert_voice_text)
        self.voice_input.error.connect(self._voice_error)
        self.dock.installEventFilter(self)
        application = QCoreApplication.instance()
        if application is None:
            raise RuntimeError("AI chat requires an application instance")
        application.aboutToQuit.connect(self.close)
        self.refresh_voice_input()

    def refresh_voice_input(self) -> None:
        self.voice_input.select_provider(load_voice_input_provider())

    def _toggle_voice_input(self) -> None:
        if self.voice_input.state == "recording":
            self.voice_input.stop()
        elif not self.session.busy and not self.voice_input.active and self.voice_input.available:
            self.input.setFocus(Qt.FocusReason.OtherFocusReason)
            QTimer.singleShot(0, self._start_voice_input)

    def _start_voice_input(self) -> None:
        if self.dock.isVisible() and not self.session.busy:
            self.voice_input.start()

    @Slot(str)
    def _insert_voice_text(self, text: str) -> None:
        cursor = self.input.textCursor()
        cursor.insertText(text)
        self.input.setTextCursor(cursor)
        self.input.ensureCursorVisible()

    @Slot(str)
    def _voice_error(self, error: str) -> None:
        self._append("error", tr("AiChat", "音声入力エラー：{error}").format(error=error))

    @Slot()
    def _update_input_controls(self) -> None:
        ai_busy = self.session.busy
        voice_busy = self.voice_input.active
        self.input.setReadOnly(ai_busy or voice_busy)
        self.attach_button.setEnabled(not ai_busy and not voice_busy)
        attach_label = tr("AiChat", "画像・ファイルを添付")
        self.attach_button.setToolTip(attach_label)
        self.attach_button.setAccessibleName(attach_label)
        self.send_button.setEnabled(not voice_busy and self.history.is_ready)
        self.send_button.setIcon(self._get_icon("stop" if ai_busy else "send-24"))
        send_label = tr("AiChat", "停止") if ai_busy else tr("AiChat", "送信")
        self.send_button.setToolTip(send_label)
        self.send_button.setAccessibleName(send_label)
        self.model_button.setEnabled(not ai_busy and not voice_busy and bool(self._choices))
        self.voice_button.setVisible(self.voice_input.available)
        self.voice_button.setEnabled(not ai_busy and self.voice_input.state != "processing")
        if self.voice_input.state == "recording":
            voice_label = tr("AiChat", "音声入力を停止して認識")
            status = tr("AiChat", "音声を入力しています…")
        elif self.voice_input.state == "processing":
            voice_label = tr("AiChat", "音声を認識中")
            status = tr("AiChat", "音声を認識しています…")
        else:
            voice_label = tr("AiChat", "音声入力を開く")
            status = (tr("AiChat", "AIが応答しています…") if ai_busy else
                      "" if self.history.is_ready else tr("AiChat", "Web表示の準備を待っています…"))
        self.voice_button.setToolTip(voice_label)
        self.voice_button.setAccessibleName(voice_label)
        self.status.setText(status)

    def refresh_choices(self) -> None:
        if self.session.busy:
            self._refresh_pending = True
            return
        self._refresh_pending = False
        settings = self.settings()
        previous_menu = self.model_button.menu()
        menu = QMenu(self.model_button)
        group = QActionGroup(menu)
        group.setExclusive(True)
        self._choices.clear()
        self._model_actions.clear()
        for provider in self.registry.providers.values():
            submenu = menu.addMenu(provider.display_name)
            for model in settings.models.get(provider.id, []):
                if not model.enabled or not model.model.strip():
                    continue
                choice = (provider.id, model.model)
                if choice in self._choices:
                    continue
                self._choices[choice] = (provider.display_name, model.name or model.model)
                action = submenu.addAction(model.name or model.model)
                action.setCheckable(True)
                action.setToolTip(model.model)
                group.addAction(action)
                action.triggered.connect(lambda _checked=False, selected=choice: self._choose_model(selected))
                self._model_actions[choice] = action
            submenu.setEnabled(bool(submenu.actions()))
        self.model_button.setMenu(menu)
        if previous_menu is not None:
            previous_menu.deleteLater()
        preferred = (settings.provider_id, settings.selected_models.get(settings.provider_id, ""))
        choice = self._choice if self._choice in self._choices else preferred
        if choice not in self._choices:
            choice = next((key for key in self._choices if key[0] == settings.provider_id),
                          next(iter(self._choices), None))
        self._choose_model(choice)

    def _choose_model(self, choice: tuple[str, str] | None) -> None:
        if self.session.busy:
            return
        previous = self._choice
        self._choice = choice
        self._update_model_label()
        self._update_input_controls()
        if choice is not None:
            self._model_actions[choice].setChecked(True)
        if previous is not None and choice != previous and self.session.history:
            provider_name, model_name = self._choices.get(choice, ("", "")) if choice is not None else ("", "")
            self._append("operation", tr("AiChat", "使用するAIを変更しました：{provider} / {model}").format(
                provider=provider_name, model=model_name))
            if choice is not None and choice[0] != previous[0]:
                self._append("operation", tr("AiChat", "次の送信で、過去の会話と参照も変更先のプロバイダへ送信されます。"))

    def _update_model_label(self) -> None:
        names = self._choices.get(self._choice) if self._choice is not None else None
        if names is None:
            self.model_button.setText(tr("AiChat", "モデルを選択"))
            self.model_button.setToolTip(tr("AiChat", "設定画面で有効なモデルを登録してください。"))
            return
        provider_name, model_name = names
        self.model_button.setText(self.model_button.fontMetrics().elidedText(
            model_name, Qt.TextElideMode.ElideRight, max(0, self.model_button.text_rect().width())))
        self.model_button.setToolTip(f"{provider_name} / {model_name}\n" +
                                    tr("AiChat", "切り替え後の送信では過去の会話と参照も送信されます。"))

    def _send(self, submitted_text: str | None = None) -> None:
        if self.voice_input.active:
            return
        if self.session.busy:
            self.session.stop()
            return
        if not self.history.is_ready:
            return
        text, attachments = self.input.message() if submitted_text is None else (submitted_text, ())
        if not text:
            return
        if self._choice is None:
            self._append("error", tr("AiChat", "設定画面で有効なモデルを登録してください。"))
            return
        provider_id, model = self._choice
        provider = self.registry.get(provider_id)
        if provider is None:
            self._append("error", tr("AiChat", "プロバイダを選択してください。"))
            return
        try:
            key = self.settings().api_keys.get(provider_id, "").strip() or self.registry.get_env_api_key(provider_id)
            translator = provider.create(key, model)
            if not isinstance(translator, BaseHttpTranslator):
                raise ValueError(tr("AiChat", "このプロバイダはチャットに対応していません。"))
            current = self.current_file()
            scope = self.scope_combo.currentData()
            references = self.selected_references()
            if scope == "file" and current is None:
                raise ValueError(tr("AiChat", "対象ファイルを選択してください。"))
            if scope == "selection" and not references:
                raise ValueError(tr("AiChat", "参照に追加する文章を選択してください。"))
            self.operations.scope_language = current.identity[1] if current is not None and scope != "project" else ""
            self.operations.scope_file = (current.identity[2] if current is not None
                                          and self.scope_combo.currentData() == "file" else "")
            self.operations.scope_selection = ([reference.id for reference in self.selected_references()]
                if self.scope_combo.currentData() == "selection" else [])
            self._clear_on_completion = submitted_text is None
            self.session.send(text, translator, attachments)
        except (ValueError, RuntimeError) as exc:
            self._append("error", str(exc))

    def _completed(self) -> None:
        if self._clear_on_completion:
            self.input.clear()

    def _busy_changed(self, busy: bool) -> None:
        if busy:
            self.voice_input.cancel()
        if not busy and self._refresh_pending:
            self.refresh_choices()
        self.model_button.setEnabled(not busy and bool(self._choices))
        self.new_button.setEnabled(not busy)
        self.scope_combo.setEnabled(not busy)
        self.execution_combo.setEnabled(not busy)
        self.history.busy = busy
        self.history.publish()
        self._update_input_controls()

    def _append(self, role: str, text: str) -> None:
        model = self._choices[self._choice][1] if role == "assistant" and self._choice is not None else ""
        provider = self._choice[0] if role == "assistant" and self._choice is not None else ""
        self.history.append(role, text, model, provider, self._icon_data(self._chat_icon(provider)) if provider else "")

    @staticmethod
    def _icon_data(icon: QIcon) -> str:
        from base64 import b64encode
        from PySide6.QtCore import QBuffer, QByteArray, QIODeviceBase
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODeviceBase.OpenModeFlag.WriteOnly):
            raise RuntimeError("Cannot encode chat icon")
        if not icon.pixmap(QSize(20, 20)).save(buffer, "PNG"):
            raise RuntimeError("Cannot save chat icon")
        buffer.close()
        return "data:image/png;base64," + b64encode(bytes(data.data())).decode("ascii")

    def refresh_icons(self, provider_id: str | None = None) -> None:
        for item in self.history.items.values():
            provider = item.get("provider")
            if isinstance(provider, str) and provider and (provider_id is None or provider == provider_id):
                item["icon"] = self._icon_data(self._chat_icon(provider))
        self.history.markdown_icon = self._icon_data(self._get_icon("markdown"))
        self.history.publish()
        self.voice_button.setIcon(self._get_icon("microphone"))
        self._update_input_controls()

    def selected_attachment(self) -> ChatAttachment | None:
        references = self.selected_references()
        if not references:
            return None
        origin = self.selection_origin()
        name = tr("AiChat", "選択した{count}行").format(count=len(references))
        return ChatAttachment(uuid4().hex, name, origin,
                              json.dumps([reference.document() for reference in references], ensure_ascii=False, indent=2))

    def insert_selected_reference(self) -> None:
        if self.session.busy or self.voice_input.active:
            return
        attachment = self.selected_attachment()
        if attachment is not None:
            self._toggle(True)
            self.input.insert_reference(attachment)

    @Slot(object)
    def _view_reference(self, value: object) -> None:
        if not isinstance(value, ChatAttachment):
            raise TypeError("Invalid chat reference")
        if value.image is not None:
            pixmap = QPixmap()
            if not pixmap.loadFromData(b64decode(value.image.data)):
                self._append("error", tr("AiChat", "画像を表示できません。"))
                return
            dialog = QDialog(self.window)
            dialog.setWindowTitle(value.name)
            layout = QVBoxLayout(dialog)
            label = QLabel(dialog)
            label.setPixmap(pixmap.scaled(QSize(800, 600), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(label)
            dialog.exec()
            dialog.deleteLater()
            return
        show_details(self.window, value.name, value.origin + "\n\n" + value.content)

    @Slot()
    def _attach_files(self) -> None:
        if self.input.isReadOnly():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self.window, tr("AiChat", "画像・ファイルを添付"), "",
            tr("AiChat", "画像 (*.png *.jpg *.jpeg *.webp *.gif);;テキスト・その他のファイル (*)"),
        )
        self.input.insert_files([Path(path) for path in paths])

    @Slot(str)
    def _web_ready(self, instructions: str) -> None:
        self.session.rendering_instructions = instructions
        self._update_input_controls()

    @Slot(str)
    def _web_action(self, payload: str) -> None:
        try:
            value = json.loads(payload)
            if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                raise ValueError("Invalid UI action")
            action = value["type"]
            if action == "copy":
                text = value.get("text")
                if not isinstance(text, str):
                    raise ValueError("Invalid clipboard text")
                clipboard = QApplication.clipboard()
                if clipboard is None:
                    raise RuntimeError("Clipboard is unavailable")
                clipboard.setText(text)
            elif action == "open_link":
                url_text = value.get("url")
                if not isinstance(url_text, str):
                    raise ValueError("Invalid link")
                url = QUrl(url_text)
                if url.scheme() not in {"https", "http"}:
                    raise ValueError("Unsupported link")
                QDesktopServices.openUrl(url)
            elif action == "submit":
                source = self.history.items.get(value.get("itemId", ""))
                text = value.get("text")
                if source is None or source.get("role") != "assistant" or not isinstance(text, str):
                    raise ValueError("Invalid UI submission")
                if not self.session.busy:
                    self._send(text)
            elif action in {"apply_operation", "discard_operation", "undo_operation", "view_operation"}:
                key = value.get("id")
                if not isinstance(key, str):
                    raise ValueError("Invalid operation id")
                proposal = self.operations.proposals.get(key)
                if proposal is None or proposal.project_id != self.operations.project_id:
                    raise ValueError("操作の対象が終了しました")
                document = proposal.document()
                if action == "view_operation":
                    rows = [row for row in document["changes"] if row.get("language")]
                    if rows:
                        self.operations.selection_requested.emit(rows[0]["language"], [row["id"] for row in rows])
                else:
                    arguments: dict[str, Any] = {"operation_id": key}
                    if action == "apply_operation":
                        ids = value.get("ids")
                        available = {row["id"] for row in document["changes"]}
                        if not isinstance(ids, list) or not all(isinstance(item, str) and item in available for item in ids):
                            raise ValueError("Invalid selected changes")
                        arguments["ids"] = ids
                    self._operation_changed(self.operations.execute(action, arguments, trusted_ui=True))
            elif action == "cancel_job":
                key = value.get("id")
                if not isinstance(key, str):
                    raise ValueError("Invalid job id")
                job = self.operations.jobs.get(key)
                if job is None or job.project_id != self.operations.project_id:
                    raise ValueError("処理の対象が終了しました")
                self.operations.execute(action, {"job_id": key}, trusted_ui=True)
            else:
                raise ValueError("Unsupported UI action")
        except (ValueError, RuntimeError, TypeError) as exc:
            self._append("error", str(exc))

    def _execution_changed(self, _index: int) -> None:
        self.operations.confirm_changes = bool(self.execution_combo.currentData())

    def _operation_changed(self, value: object) -> None:
        if not isinstance(value, dict):
            raise TypeError("Invalid operation document")
        document: dict[str, Any] = value
        self.history.update_document("operation", document)

    def _job_changed(self, value: object) -> None:
        if not isinstance(value, dict):
            raise TypeError("Invalid job document")
        document: dict[str, Any] = value
        self.history.update_document("job", document)

    def reset(self) -> None:
        self.voice_input.cancel()
        self.session.reset()
        self.history.reset()
        self.input.clear()
        for proposal in self.operations.proposals.values():
            if proposal.project_id == self.operations.project_id and proposal.status == "awaiting_confirmation":
                self._operation_changed(proposal.document())
        for job in self.operations.jobs.values():
            if job.project_id == self.operations.project_id:
                from dataclasses import asdict
                self._job_changed(asdict(job))

    def context_changed(self) -> None:
        self.voice_input.cancel()
        self.session.stop()

    def _toggle(self, visible: bool) -> None:
        if not visible:
            self.voice_input.cancel()
        self._visible = visible
        self.dock.setVisible(visible)
        if visible:
            self.dock.raise_()

    def _dock_toggled(self, visible: bool) -> None:
        if not visible:
            self.voice_input.cancel()
        if self._changing_visibility:
            return
        self._visible = visible
        self.action.setChecked(visible)

    def restore_visibility(self) -> None:
        self._visible = not self.dock.isHidden()

    def set_workspace_page(self, enabled: bool) -> None:
        if not enabled:
            self.voice_input.cancel()
        self.action.setEnabled(enabled)
        self.action.setChecked(self._visible)
        self._changing_visibility = True
        try:
            self.dock.setVisible(enabled and self._visible)
        finally:
            self._changing_visibility = False

    def close(self) -> None:
        self.voice_input.close()
        self.session.stop()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.dock and event.type() == QEvent.Type.LanguageChange:
            for index, label in enumerate((translation_source('AiChat', "プロジェクト全体"), translation_source('AiChat', "現在のファイル"), translation_source('AiChat', "選択行"))):
                self.scope_combo.setItemText(index, tr("AiChat", label))
            for index, label in enumerate(("提案を確認", "依頼どおり実行")):
                self.execution_combo.setItemText(index, tr("AiChat", label))
            self.scope_combo.setToolTip(tr("AiChat", "操作の対象範囲"))
            self._scope_label.setText(tr("AiChat", "操作の対象範囲"))
            self._execution_label.setText(tr("AiChat", "実行方法"))
            self.history.publish()
        if watched is self.dock and event.type() == QEvent.Type.Close:
            self.voice_input.cancel()
        if watched is self.model_button and event.type() == QEvent.Type.Resize:
            self._update_model_label()
        return super().eventFilter(watched, event)
