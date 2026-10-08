from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QActionGroup, QIcon, QInputMethodEvent, QKeyEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QMenu, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from autolingua2.services.ai_chat import AiChatSession, ChatFile, ChatReference
from autolingua2.services.ai_providers.base import BaseHttpTranslator
from autolingua2.services.ai_providers.registry import ProviderRegistry
from autolingua2.services.settings_store import AiSettings, load_voice_input_provider
from autolingua2.services.voice_input import VoiceInputService
from autolingua2.services.voice_input_contract import VoiceInputProvider
from autolingua2.ui.components.combo_menu_button import ComboMenuButton
from autolingua2.ui.dialogs.base import SimpleDialogController, require_child
from autolingua2.ui.i18n import tr


class ChatUserMessage(QWidget):
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().brush(QPalette.ColorRole.AlternateBase))
        painter.drawRoundedRect(self.rect(), 14, 14)


class AiChatDockController(QObject):
    def __init__(
        self, window: QMainWindow, registry: ProviderRegistry, settings: Callable[[], AiSettings],
        current_file: Callable[[], ChatFile | None],
        selected_references: Callable[[], tuple[ChatReference, ...]],
        select_units: Callable[[list[str]], None],
        *, voice_input_providers: Mapping[str, VoiceInputProvider],
        get_icon: Callable[[str], QIcon],
        chat_icon: Callable[[str], QIcon],
    ) -> None:
        super().__init__(window)
        self.window = window
        self.registry = registry
        self.settings = settings
        self.selected_references = selected_references
        self.select_units = select_units
        self._get_icon = get_icon
        self._chat_icon = chat_icon
        self._answer_icons: list[tuple[str, QLabel, QPushButton]] = []
        self.session = AiChatSession(current_file, self)
        self.voice_input = VoiceInputService(voice_input_providers, self)
        self.dock = require_child(window, QDockWidget, "dockAiChat")
        self.action = require_child(window, QAction, "actionToggleAiChat")
        self.history = require_child(window, QScrollArea, "scrollChatHistory")
        self.history_content = QWidget()
        self.history_content.setAutoFillBackground(True)
        self.history_content.setBackgroundRole(QPalette.ColorRole.Base)
        self.history_layout = QVBoxLayout(self.history_content)
        self.history_layout.setContentsMargins(8, 8, 8, 8)
        self.history_layout.setSpacing(24)
        self.history_layout.addStretch()
        self.history.setWidget(self.history_content)
        self.history.verticalScrollBar().rangeChanged.connect(self._scroll_to_end)
        self.input = require_child(window, QPlainTextEdit, "editChatMessage")
        self._ime_placeholder: str | None = None
        self.model_button = require_child(window, ComboMenuButton, "buttonChatModel")
        combo_height = require_child(window, QComboBox, "comboAiModel").sizeHint().height()
        self.model_button.setFixedHeight(combo_height)
        self.send_button = require_child(window, QPushButton, "buttonChatSend")
        self.send_button.setFixedSize(combo_height, combo_height)
        send_icon_size = max(1, combo_height - 8)
        self.send_button.setIconSize(QSize(send_icon_size, send_icon_size))
        self.voice_button = require_child(window, QPushButton, "buttonChatVoice")
        self.voice_button.setFixedSize(combo_height, combo_height)
        self.voice_button.setIconSize(QSize(send_icon_size, send_icon_size))
        self.new_button = require_child(window, QPushButton, "buttonChatNew")
        self.add_button = require_child(window, QPushButton, "buttonChatAddReferences")
        self.clear_button = require_child(window, QPushButton, "buttonChatClearReferences")
        self.view_button = require_child(window, QPushButton, "buttonChatViewReferences")
        self.reference_label = require_child(window, QLabel, "labelChatReferences")
        self.status = require_child(window, QLabel, "labelChatStatus")
        self._visible = True
        self._changing_visibility = False
        self._choice: tuple[str, str] | None = None
        self._choices: dict[tuple[str, str], tuple[str, str]] = {}
        self._model_actions: dict[tuple[str, str], QAction] = {}
        self._refresh_pending = False
        self.refresh_choices()
        self.model_button.installEventFilter(self)
        self.send_button.clicked.connect(self._send)
        self.voice_button.clicked.connect(self._toggle_voice_input)
        self.new_button.clicked.connect(self.reset)
        self.add_button.clicked.connect(self._add_references)
        self.clear_button.clicked.connect(lambda: self.session.set_references(()))
        self.view_button.clicked.connect(self._view_references)
        self.action.triggered.connect(self._toggle)
        self.dock.toggleViewAction().toggled.connect(self._dock_toggled)
        self.session.message.connect(self._append)
        self.session.busy_changed.connect(self._busy_changed)
        self.session.references_changed.connect(self._references_changed)
        self.session.selection_requested.connect(self._select)
        self.session.completed.connect(self._completed)
        self.voice_input.changed.connect(self._update_input_controls)
        self.voice_input.text_recognized.connect(self._insert_voice_text)
        self.voice_input.error.connect(self._voice_error)
        self.input.installEventFilter(self)
        self.dock.installEventFilter(self)
        application = QCoreApplication.instance()
        if application is None:
            raise RuntimeError("AI chat requires an application instance")
        application.aboutToQuit.connect(self.close)
        self._references_changed()
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
        self.send_button.setEnabled(not voice_busy)
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
                      tr("AiChat", "操作対象：現在のファイル（検索・選択のみ）"))
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

    def _send(self) -> None:
        if self.voice_input.active:
            return
        if self.session.busy:
            self.session.stop()
            return
        text = self.input.toPlainText().strip()
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
            self.session.send(text, translator)
        except (ValueError, RuntimeError) as exc:
            self._append("error", str(exc))

    def _completed(self) -> None:
        self.input.clear()

    def _busy_changed(self, busy: bool) -> None:
        if busy:
            self.voice_input.cancel()
        if not busy and self._refresh_pending:
            self.refresh_choices()
        self.model_button.setEnabled(not busy and bool(self._choices))
        self.new_button.setEnabled(not busy)
        self.add_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy and bool(self.session.references))
        send_label = tr("AiChat", "停止") if busy else tr("AiChat", "送信")
        self.send_button.setToolTip(send_label)
        self.send_button.setAccessibleName(send_label)
        self._update_input_controls()

    def _append(self, role: str, text: str) -> None:
        message = ChatUserMessage() if role == "user" else QWidget()
        layout = QVBoxLayout(message)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)
        provider_id: str | None = None
        icon_label: QLabel | None = None
        if role == "assistant":
            if self._choice is not None:
                provider_id = self._choice[0]
                _, model_name = self._choices[self._choice]
                header = QHBoxLayout()
                icon_label = QLabel(message)
                icon_label.setFixedSize(20, 20)
                icon_label.setPixmap(self._chat_icon(provider_id).pixmap(QSize(20, 20)))
                header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
                model = self._text_label(model_name, message)
                font = model.font()
                font.setPointSizeF(max(1.0, font.pointSizeF() - 1.0))
                model.setFont(font)
                header.addWidget(model, 1)
                layout.addLayout(header)
        elif role != "user":
            label = tr("AiChat", "エラー") if role == "error" else tr("AiChat", "操作")
            layout.addWidget(self._text_label(label, message))
        layout.addWidget(self._text_label(text, message))
        if role == "assistant":
            actions = QHBoxLayout()
            actions.addStretch()
            copy_button = QPushButton(message)
            copy_button.setFlat(True)
            copy_button.setFixedSize(28, 28)
            copy_button.setIcon(self._get_icon("copy"))
            copy_label = tr("AiChat", "回答をコピー")
            copy_button.setToolTip(copy_label)
            copy_button.setAccessibleName(copy_label)
            copy_timer = QTimer(copy_button)
            copy_timer.setSingleShot(True)
            copy_timer.setInterval(1500)
            copy_timer.timeout.connect(lambda: self._reset_copy_button(copy_button))
            copy_button.clicked.connect(lambda: self._copy_answer(text, copy_button, copy_timer))
            actions.addWidget(copy_button)
            layout.addLayout(actions)
            if provider_id is not None and icon_label is not None:
                self._answer_icons.append((provider_id, icon_label, copy_button))
        self.history_layout.insertWidget(self.history_layout.count() - 1, message)

    @staticmethod
    def _text_label(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _copy_answer(self, text: str, button: QPushButton, timer: QTimer) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            raise RuntimeError("Clipboard is unavailable")
        clipboard.setText(text)
        button.setProperty("answerCopied", True)
        button.setIcon(self._get_icon("check"))
        timer.start()

    def _reset_copy_button(self, button: QPushButton) -> None:
        button.setProperty("answerCopied", False)
        button.setIcon(self._get_icon("copy"))

    def _scroll_to_end(self, minimum: int, maximum: int) -> None:
        self.history.verticalScrollBar().setValue(maximum)

    def refresh_icons(self, provider_id: str | None = None) -> None:
        for answer_provider, label, button in self._answer_icons:
            if provider_id is None or provider_id == answer_provider:
                label.setPixmap(self._chat_icon(answer_provider).pixmap(QSize(20, 20)))
            button.setIcon(self._get_icon("check" if button.property("answerCopied") is True else "copy"))
        self.send_button.setIcon(self._get_icon("send-24"))
        self.voice_button.setIcon(self._get_icon("microphone"))

    def _add_references(self) -> None:
        references = self.selected_references()
        if not references:
            self._append("operation", tr("AiChat", "参照に追加する文章を選択してください。"))
            return
        self.session.set_references(references)

    def _references_changed(self) -> None:
        count = len(self.session.references)
        self.reference_label.setText(tr("AiChat", "参照：選択した文章 {count}件").format(count=count)
                                     if count else tr("AiChat", "参照：なし"))
        self.view_button.setEnabled(count > 0)
        self.clear_button.setEnabled(count > 0 and not self.session.busy)

    def _view_references(self) -> None:
        dialog = SimpleDialogController("ChatReferencesDialog.ui", self.window)
        editor = require_child(dialog.dialog, QPlainTextEdit, "editReferences")
        editor.setPlainText("\n\n".join(f"{r.key}\n原文：{r.source}\n訳文：{r.translation}"
                                       for r in self.session.references))
        dialog.exec()

    def _select(self, value: object) -> None:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise TypeError("選択IDの形式が不正です。")
        self.select_units([str(item) for item in value])

    def reset(self) -> None:
        self.voice_input.cancel()
        self.session.reset()
        self._answer_icons.clear()
        while self.history_layout.count() > 1:
            item = self.history_layout.takeAt(0)
            if item is None:
                raise RuntimeError("Missing chat layout item")
            widget = item.widget()
            if widget is None:
                raise RuntimeError("Missing chat message widget")
            widget.hide()
            widget.deleteLater()
        self.input.clear()

    def context_changed(self) -> None:
        self.voice_input.cancel()
        self.session.stop()
        self.session.set_references(())

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
        if watched is self.dock and event.type() == QEvent.Type.Close:
            self.voice_input.cancel()
        if watched is self.input and isinstance(event, QInputMethodEvent):
            if event.preeditString():
                if self._ime_placeholder is None:
                    self._ime_placeholder = self.input.placeholderText()
                    self.input.setPlaceholderText("")
            elif self._ime_placeholder is not None:
                self.input.setPlaceholderText(self._ime_placeholder)
                self._ime_placeholder = None
        if watched is self.model_button and event.type() == QEvent.Type.Resize:
            self._update_model_label()
        if watched is self.input and isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if not self.session.busy:
                    self._send()
                return True
        return super().eventFilter(watched, event)
