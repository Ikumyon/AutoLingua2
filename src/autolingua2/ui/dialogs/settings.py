from __future__ import annotations

import uuid



from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _InlineLineEdit(QLineEdit):
    escapePressed = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            self.clearFocus()
            return
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self.escapePressed.emit()
            return
        super().keyPressEvent(event)


class InlineEditableField(QWidget):
    valueChanged = Signal(str)

    def __init__(
        self,
        text: str = "",
        placeholder: str = "",
        *,
        icon_manager: IconAPI,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._placeholder = placeholder
        self.icon_manager = icon_manager

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)

        self.label = QLabel(text or placeholder, self)
        if not text:
            self.label.setStyleSheet("color: #888;")
        self.icon_pencil = QLabel(self)
        pencil_icon = self.icon_manager.get_icon("pencil")
        if not pencil_icon.isNull():
            self.icon_pencil.setPixmap(pencil_icon.pixmap(QSize(13, 13)))
        else:
            self.icon_pencil.setText("✏")
        self.icon_pencil.setVisible(False)

        self.line_edit = _InlineLineEdit(text, self)
        self.line_edit.setPlaceholderText(placeholder)
        self.line_edit.setVisible(False)

        layout.addWidget(self.label, 1)
        layout.addWidget(self.icon_pencil)
        layout.addWidget(self.line_edit, 1)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.line_edit.editingFinished.connect(self._on_editing_finished)
        self.line_edit.escapePressed.connect(self._on_escape_pressed)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.label.setText(text or self._placeholder)
        if not text:
            self.label.setStyleSheet("color: #888;")
        else:
            self.label.setStyleSheet("")
        self.line_edit.setText(text)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if not self.line_edit.isVisible():
            self.icon_pencil.setVisible(True)
            self.setStyleSheet(
                "InlineEditableField { border: 1px dashed rgba(160, 160, 160, 0.6); border-radius: 4px; background: rgba(255, 255, 255, 0.05); }"
            )

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if not self.line_edit.isVisible():
            self.icon_pencil.setVisible(False)
            self.setStyleSheet("InlineEditableField { border: 1px solid transparent; background: transparent; }")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.line_edit.isVisible():
            self.start_edit()
            return
        super().mousePressEvent(event)

    def start_edit(self) -> None:
        self.label.setVisible(False)
        self.icon_pencil.setVisible(False)
        self.setStyleSheet("InlineEditableField { border: none; background: transparent; }")
        self.line_edit.setVisible(True)
        self.line_edit.setText(self._text)
        self.line_edit.setFocus()
        self.line_edit.selectAll()

    def _on_escape_pressed(self) -> None:
        self.line_edit.setText(self._text)
        self.line_edit.setVisible(False)
        self.label.setVisible(True)
        self.icon_pencil.setVisible(False)
        self.setStyleSheet("InlineEditableField { border: 1px solid transparent; background: transparent; }")

    def _on_editing_finished(self) -> None:
        if not self.line_edit.isVisible():
            return
        new_text = self.line_edit.text().strip()
        changed = (new_text != self._text)
        self._text = new_text
        self.label.setText(new_text or self._placeholder)
        if not new_text:
            self.label.setStyleSheet("color: #888;")
        else:
            self.label.setStyleSheet("")
        self.line_edit.setVisible(False)
        self.label.setVisible(True)
        if self.underMouse():
            self.icon_pencil.setVisible(True)
            self.setStyleSheet(
                "InlineEditableField { border: 1px dashed rgba(160, 160, 160, 0.6); border-radius: 4px; background: rgba(255, 255, 255, 0.05); }"
            )
        else:
            self.icon_pencil.setVisible(False)
            self.setStyleSheet("InlineEditableField { border: 1px solid transparent; background: transparent; }")
        if changed:
            self.valueChanged.emit(self._text)


class ModelRowWidget(QFrame):
    deleted = Signal(object)
    modelCommitted = Signal(object)

    def __init__(
        self,
        entry: AiModel,
        icon_manager: IconAPI,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.icon_manager = icon_manager
        self.setStyleSheet("ModelRowWidget { border-radius: 6px; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self.check_enabled = QCheckBox(self)
        self.check_enabled.setChecked(entry.enabled)
        self.check_enabled.setToolTip("有効/無効")

        self.field_name = InlineEditableField(entry.name, placeholder="表示名", icon_manager=self.icon_manager, parent=self)
        self.field_model = InlineEditableField(entry.model, placeholder="モデル名 (例: gpt-6.1-sol)", icon_manager=self.icon_manager, parent=self)

        self.button_delete = QToolButton(self)
        trash_icon = self.icon_manager.get_icon("trash")
        if not trash_icon.isNull():
            self.button_delete.setIcon(trash_icon)
            self.button_delete.setIconSize(QSize(15, 15))
        else:
            self.button_delete.setText("✕")
        self.button_delete.setToolTip("このモデルを削除")
        self.button_delete.setFixedSize(26, 26)
        self.button_delete.setStyleSheet(
            "QToolButton { border: none; border-radius: 4px; padding: 2px; }"
            "QToolButton:hover { background-color: #e81123; }"
        )

        layout.addWidget(self.check_enabled)
        layout.addWidget(self.field_name, 1)
        layout.addWidget(self.field_model, 1)
        layout.addWidget(self.button_delete)

        self.button_delete.clicked.connect(lambda: self.deleted.emit(self))
        self.field_model.valueChanged.connect(lambda _: self.modelCommitted.emit(self))

        self._status: str | None = None
        self._status_tooltip: str = ""
        self.check_enabled.toggled.connect(self._on_enabled_toggled)
        if not entry.enabled:
            self.set_status("disabled", "無効化されています")

    def _on_enabled_toggled(self, checked: bool) -> None:
        if not checked:
            self.set_status("disabled", "無効化されています")
        else:
            self.set_status(
                self._status if self._status != "disabled" else None,
                self._status_tooltip if self._status != "disabled" else "",
            )

    def set_status(self, status: str | None, tooltip: str = "") -> None:
        if status != "disabled":
            self._status = status
            self._status_tooltip = tooltip
        self.setProperty("status", status or "")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setToolTip(tooltip)

    def to_ai_model(self) -> AiModel:
        name = self.field_name.text().strip()
        model = self.field_model.text().strip()
        return AiModel(
            name=name or model,
            model=model,
            enabled=self.check_enabled.isChecked(),
        )

from autolingua2.extensions import ExtensionEntrance
from autolingua2.ir.filter_rules import AdapterFilterConfig, FilterRule
from autolingua2.plugins.api import SettingsPageProvider
from autolingua2.services.ai_network import AiNetworkClient
from autolingua2.services.ai_providers import ProviderRegistry
from autolingua2.services.filter_rules import get_default_filter_config
from autolingua2.services.settings_store import (
    AiModel,
    AiSettings,
    DEFAULT_UI_LANGUAGE,
    load_adapter_filter_rules,
    load_theme_settings,
    load_ui_language,
    load_voice_input_provider,
    save_ai_settings,
    save_adapter_filter_rules,
    save_theme_settings,
    save_ui_language,
    save_voice_input_provider,
)
from autolingua2.services.voice_input import voice_input_available
from autolingua2.ui.i18n import (
    normalize_language,
    system_language,
    tr,
)
from autolingua2.ui.resource_api import IconAPI
from .base import SimpleDialogController, load_ui, require_child
from .glossary import GlossaryPageController
from .source_watch import WatchPageController


class SettingsDialogController(SimpleDialogController):
    def __init__(
        self, entrance: ExtensionEntrance, parent: QWidget | None = None,
        provider_id: str = "openai", models: dict[str, list[AiModel]] | None = None,
        selected_models: dict[str, str] | None = None,
        api_keys: dict[str, str] | None = None,
        concurrency: int = 4,
        *, glossary_languages: dict[str, str] | None = None,
        glossary_adapter_id: str = "", glossary_game_id: str = "",
        glossary_id: str = "", glossary_source_language: str = "",
        glossary_target_language: str = "",
    ) -> None:
        super().__init__("dialogs/settings/SettingsDialog.ui", parent)
        self.plugins = entrance.plugins
        self.localization = entrance.localization
        self.theme_manager = entrance.themes
        self.icon_manager = entrance.icons
        self._filter_configs: dict[str, AdapterFilterConfig] = {}
        self._current_adapter_id: str = ""
        self._plugin_settings_widgets: list[tuple[SettingsPageProvider, QWidget]] = []

        self.ai_client = AiNetworkClient(self.dialog)
        self.ai_client.model_validated.connect(self._on_model_validated)
        self.ai_client.all_validated.connect(self._on_all_models_validated)
        self._testing_for_save = False
        self._unvalidated_models_for_save: list[ModelRowWidget] = []

        self._mount_pages()
        self.watch_page = WatchPageController(self.dialog, self.plugins.parsers, self.icon_manager)
        self.glossary_page = GlossaryPageController(
            require_child(self.dialog, QWidget, "SettingsGlossaryPage"), entrance,
            glossary_languages or {}, glossary_adapter_id, glossary_game_id,
            glossary_id, glossary_source_language, glossary_target_language,
        )
        settings_splitter = require_child(self.dialog, QSplitter, "splitterSettings")
        settings_splitter.setSizes([160, 760])
        settings_splitter.setStretchFactor(0, 0)
        settings_splitter.setStretchFactor(1, 1)
        self._mount_plugin_settings_pages()
        self._connect_category_stack()

        self.button_box = require_child(self.dialog, QDialogButtonBox, "buttonBox")
        self.button_box.accepted.disconnect()
        self.button_box.accepted.connect(self._on_save_attempt)
        self.button_box.rejected.connect(self.ai_client.cancel_all)
        self._setup_ui_language()
        self._setup_voice_input()
        self._setup_themes_and_icons()
        self._setup_ai(self.plugins.providers, provider_id, models or {}, selected_models or {}, api_keys or {}, concurrency)
        self._setup_filter_rules()
        self._setup_dialog_buttons()

    def _mount_pages(self) -> None:
        pages = [
            ("pageGeneral", "dialogs/settings/GeneralPage.ui"),
            ("pageAI", "dialogs/settings/AiPage.ui"),
            ("pageFile", "dialogs/settings/FilePage.ui"),
            ("pageDisplay", "dialogs/settings/DisplayPage.ui"),
            ("pageFilterRules", "dialogs/settings/FilterRulesPage.ui"),
            ("pageGlossary", "dialogs/settings/GlossaryPage.ui"),
        ]
        for page_name, ui_name in pages:
            container = require_child(self.dialog, QWidget, page_name)
            layout = container.layout()
            sub_widget = load_ui(ui_name, container)
            if layout is not None:
                layout.addWidget(sub_widget)

    def _mount_plugin_settings_pages(self) -> None:
        categories = require_child(self.dialog, QListWidget, "listCategories")
        stack = require_child(self.dialog, QStackedWidget, "stackSettings")

        for provider in self.plugins.all_settings_pages:
            item = QListWidgetItem(provider.title)
            item.setData(Qt.ItemDataRole.UserRole, provider.id)
            categories.addItem(item)

            widget = provider.create_widget(stack)
            stack.addWidget(widget)
            self._plugin_settings_widgets.append((provider, widget))

    def select_category(self, target: str) -> bool:
        """公開された設定ページIDに一致するカテゴリを選択。"""
        categories = require_child(self.dialog, QListWidget, "listCategories")
        if target == "glossary":
            categories.setCurrentRow(5)
            return True
        if target == "file":
            categories.setCurrentRow(2)
            return True
        for row in range(categories.count()):
            item = categories.item(row)
            if item is not None:
                if item.data(Qt.ItemDataRole.UserRole) == target:
                    categories.setCurrentRow(row)
                    return True
        return False

    def _setup_dialog_buttons(self) -> None:
        button_box = self.dialog.findChild(QDialogButtonBox, "buttonBox")
        if button_box is not None:
            for btn in button_box.buttons():
                if isinstance(btn, QPushButton):
                    btn.setAutoDefault(False)
                    btn.setDefault(False)
            save_btn = button_box.button(QDialogButtonBox.StandardButton.Save)
            if save_btn is not None:
                save_btn.setText(tr("SettingsDialog", "保存"))
            cancel_btn = button_box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel_btn is not None:
                cancel_btn.setText(tr("SettingsDialog", "キャンセル"))

    def _setup_ai(
        self, registry: ProviderRegistry, provider_id: str,
        models: dict[str, list[AiModel]], selected_models: dict[str, str],
        api_keys: dict[str, str], concurrency: int,
    ) -> None:
        self.registry = registry
        self.ai_models = {key: [AiModel(item.name, item.model, item.enabled) for item in values]
                          for key, values in models.items()}
        self.ai_selected_models = dict(selected_models)
        self.ai_api_keys = dict(api_keys)
        self.combo_provider = require_child(self.dialog, QComboBox, "comboProvider")
        self.edit_api_key = require_child(self.dialog, QLineEdit, "editApiKey")
        self.scroll_area_models = require_child(self.dialog, QScrollArea, "scrollAreaModels")
        self.layout_model_list = require_child(self.dialog, QVBoxLayout, "layoutModelList")
        self.button_add_model = require_child(self.dialog, QPushButton, "buttonAddModel")
        self.button_reset_models = require_child(self.dialog, QPushButton, "buttonResetModels")
        self.spin_concurrency = require_child(self.dialog, QSpinBox, "spinConcurrency")
        self.spin_concurrency.setValue(concurrency)
        self._row_widgets: list[ModelRowWidget] = []

        self.combo_provider.clear()
        for plugin in self.registry.providers.values():
            self.combo_provider.addItem(plugin.display_name, plugin.id)
        if self.combo_provider.findData(provider_id) < 0:
            self.combo_provider.addItem(f"{provider_id} (利用不可)", provider_id)
        self.combo_provider.setCurrentIndex(self.combo_provider.findData(provider_id))
        self._initial_provider_id = provider_id
        self._current_provider_id = provider_id
        self._ensure_provider_api_key(provider_id)

        self.edit_api_key.setText(self.ai_api_keys.get(provider_id, ""))
        self._populate_models()

        self.error_label = require_child(self.dialog, QLabel, "labelProviderErrors")
        self._refresh_provider_errors()
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        self.button_add_model.clicked.connect(self._add_model)
        self.button_reset_models.clicked.connect(self._reset_models)
        self.button_test_connection = self.dialog.findChild(QPushButton, "buttonTestConnection")
        if self.button_test_connection is not None:
            self.button_test_connection.setEnabled(True)
            self.button_test_connection.clicked.connect(self._on_test_connection)

    def _on_test_connection(self) -> None:
        api_key = self.edit_api_key.text().strip()
        if not api_key:
            QMessageBox.warning(
                self.dialog,
                tr("SettingsDialog", "接続テスト"),
                tr("SettingsDialog", "APIキーが入力されていません。APIキーを入力してください。"),
            )
            return

        provider = self.registry.get(self._current_provider_id)
        if provider is None:
            QMessageBox.warning(
                self.dialog,
                tr("SettingsDialog", "接続テスト"),
                tr("SettingsDialog", f"選択中の Provider '{self._current_provider_id}' は利用できません。"),
            )
            return

        targets = [
            r for r in self._row_widgets
            if r.field_model.text().strip() and r.check_enabled.isChecked()
        ]
        if not targets:
            QMessageBox.information(
                self.dialog,
                tr("SettingsDialog", "接続テスト"),
                tr("SettingsDialog", "有効なテスト対象モデルが登録されていません。"),
            )
            return

        if self.button_test_connection is not None:
            self.button_test_connection.setEnabled(False)
            self.button_test_connection.setText(tr("SettingsDialog", "テスト中..."))

        for r in targets:
            r.set_status(None, tr("SettingsDialog", "検証中..."))

        self._test_results: dict[str, tuple[bool, str]] = {}
        self._testing_for_save = False
        models = [r.field_model.text().strip() for r in targets]
        self.ai_client.validate_models(provider, api_key, models, timeout_sec=8.0)

    def _on_model_validated(self, model: str, is_valid: bool, message: str) -> None:
        self._test_results[model] = (is_valid, message)
        for r in self._row_widgets:
            if r.field_model.text().strip() == model:
                r.set_status("valid" if is_valid else "invalid", message)

    def _on_all_models_validated(self, success_count: int, error_count: int) -> None:
        if self.button_test_connection is not None:
            self.button_test_connection.setEnabled(True)
            self.button_test_connection.setText(tr("SettingsDialog", "接続テスト"))

        if self._testing_for_save:
            self._testing_for_save = False
            self._handle_save_validation_result(success_count, error_count)
            return

        if error_count == 0:
            QMessageBox.information(
                self.dialog,
                tr("SettingsDialog", "接続テスト"),
                tr(
                    "SettingsDialog",
                    f"接続テストに成功しました。\n\nAPIキーおよび対象モデル（{success_count} 件）のすべてが正常に利用可能です。",
                ),
            )
            return

        test_results = getattr(self, "_test_results", {})
        error_items = [(m, msg) for m, (is_valid, msg) in test_results.items() if not is_valid]
        all_auth_errors = (
            len(error_items) > 0
            and all("APIキーが無効" in msg or "401" in msg for _, msg in error_items)
            and success_count == 0
        )

        if all_auth_errors:
            first_msg = error_items[0][1]
            QMessageBox.critical(
                self.dialog,
                tr("SettingsDialog", "接続テスト"),
                tr(
                    "SettingsDialog",
                    f"【APIキーが無効です】\n\n"
                    f"入力されたAPIキーがプロバイダに認証されませんでした。\n"
                    f"正しいAPIキーを入力してください。\n\n"
                    f"詳細: {first_msg}",
                ),
            )
        else:
            missing_models = [
                m for m, msg in error_items
                if "見つかりません" in msg or "404" in msg or "not found" in msg.lower()
            ]
            other_errors = [
                f"・{m}: {msg}" for m, msg in error_items
                if m not in missing_models
            ]

            lines = ["接続テストが完了しました。\n"]
            if missing_models:
                lines.append("【以下のモデルが見つかりませんでした】")
                for m in missing_models:
                    lines.append(f"・{m}")
                lines.append("")
            if other_errors:
                lines.append("【その他のエラー】")
                lines.extend(other_errors)
                lines.append("")

            lines.append(f"利用可能: {success_count} 件 / エラー・無効: {error_count} 件")
            lines.append("※各モデル行にマウスを合わせると詳細な理由を確認できます。")

            QMessageBox.warning(
                self.dialog,
                tr("SettingsDialog", "接続テスト"),
                tr("SettingsDialog", "\n".join(lines)),
            )

    def _switch_to_ai_category(self) -> None:
        categories = require_child(self.dialog, QListWidget, "listCategories")
        for idx in range(categories.count()):
            item = categories.item(idx)
            if item is not None and "AI" in item.text():
                categories.setCurrentRow(idx)
                break

    def _on_save_attempt(self) -> None:
        self._save_current_ai_fields()
        api_key = self.edit_api_key.text().strip()
        provider = self.registry.get(self._current_provider_id)

        # 未検証の有効モデルがあるかチェック（有効かつモデル名あり、かつ status != "valid"）
        untested_rows = [
            r for r in self._row_widgets
            if r.check_enabled.isChecked() and r.field_model.text().strip() and r._status != "valid"
        ]

        # APIキーがない、またはプロバイダがない、または未検証モデルがない場合はそのまま閉じる
        if not untested_rows or not api_key or provider is None:
            self.watch_page.save(self.dialog.accept)
            return

        # 未検証モデルがある場合：保存前に非同期自動テストを実行
        self._testing_for_save = True
        self._unvalidated_models_for_save = untested_rows

        save_btn = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setEnabled(False)
            save_btn.setText(tr("SettingsDialog", "検証中..."))

        for r in untested_rows:
            r.set_status(None, tr("SettingsDialog", "保存前チェック中..."))

        models = [r.field_model.text().strip() for r in untested_rows]
        self.ai_client.validate_models(provider, api_key, models, timeout_sec=8.0)

    def _handle_save_validation_result(self, success_count: int, error_count: int) -> None:
        save_btn = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setEnabled(True)
            save_btn.setText(tr("SettingsDialog", "保存"))

        # エラーがあった場合
        if error_count > 0:
            # 1. 自動でAI設定ページへ画面切り替え
            self._switch_to_ai_category()

            # 無効なモデルの一覧を取得
            invalid_rows = [r for r in self._unvalidated_models_for_save if r._status == "invalid"]
            invalid_names = ", ".join(f"'{r.field_model.text().strip()}'" for r in invalid_rows) or "一部のモデル"

            reply = QMessageBox.warning(
                self.dialog,
                tr("SettingsDialog", "モデル確認"),
                tr(
                    "SettingsDialog",
                    f"モデル {invalid_names} は利用できませんでした。\n\n該当モデルを無効化して保存しますか？",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                for r in invalid_rows:
                    r.check_enabled.setChecked(False)
                self._save_current_ai_fields()
                self.watch_page.save(self.dialog.accept)
            return

        # すべて有効だった場合はそのまま保存・終了
        self.watch_page.save(self.dialog.accept)

    def _populate_models(self) -> None:
        if self.layout_model_list is not None:
            while self.layout_model_list.count():
                item = self.layout_model_list.takeAt(0)
                if item is None:
                    continue
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        self._row_widgets = []
        for entry in self.ai_models.get(self._current_provider_id, []):
            self._add_row_widget(entry)
        if self.layout_model_list is not None:
            self.layout_model_list.addStretch()

    def _add_row_widget(self, entry: AiModel) -> ModelRowWidget:
        row = ModelRowWidget(entry, icon_manager=self.icon_manager, parent=self.scroll_area_models)
        row.deleted.connect(self._on_row_deleted)
        # 入力確定時の同期通信を全廃（ステータスのみクリア）
        row.modelCommitted.connect(lambda r: r.set_status(None))
        if self.layout_model_list is not None:
            insert_idx = max(0, self.layout_model_list.count() - 1) if self._row_widgets else 0
            self.layout_model_list.insertWidget(insert_idx, row)
        self._row_widgets.append(row)
        return row

    def _on_row_deleted(self, row: ModelRowWidget) -> None:
        if row in self._row_widgets:
            self._row_widgets.remove(row)
        if self.layout_model_list is not None:
            self.layout_model_list.removeWidget(row)
        row.deleteLater()

    def _read_model_list(self) -> list[AiModel]:
        entries: list[AiModel] = []
        seen: set[str] = set()
        for row in self._row_widgets:
            item = row.to_ai_model()
            if not item.model or item.model in seen:
                continue
            entries.append(item)
            seen.add(item.model)
        return entries

    def _add_model(self) -> None:
        entry = AiModel("新規モデル", "", True)
        row = self._add_row_widget(entry)
        row.field_model.start_edit()

    def _refresh_provider_errors(self) -> None:
        messages = list(self.registry.errors)
        if self._current_provider_id not in self.registry.providers:
            messages.insert(0, f"選択中の Provider は利用できません: {self._current_provider_id}")
        self.error_label.setText("\n".join(messages))

    def _save_current_ai_fields(self) -> None:
        self.ai_models[self._current_provider_id] = self._read_model_list()
        self.ai_api_keys[self._current_provider_id] = self.edit_api_key.text().strip()

    def _ensure_provider_api_key(self, p_id: str) -> None:
        if not self.ai_api_keys.get(p_id):
            env_key = self.registry.get_env_api_key(p_id)
            if env_key:
                self.ai_api_keys[p_id] = env_key

    def _reset_models(self) -> None:
        self.ai_models[self._current_provider_id] = self.registry.get_default_models(self._current_provider_id)
        self.ai_selected_models.pop(self._current_provider_id, None)
        self._populate_models()

    def _on_provider_changed(self, index: int) -> None:
        self._save_current_ai_fields()
        self._current_provider_id = str(self.combo_provider.itemData(index) or "")
        self._ensure_provider_api_key(self._current_provider_id)
        self._populate_models()
        self.edit_api_key.setText(self.ai_api_keys.get(self._current_provider_id, ""))
        self._refresh_provider_errors()

    @property
    def selected_provider_id(self) -> str:
        return self._current_provider_id

    def _connect_category_stack(self) -> None:
        categories = require_child(self.dialog, QListWidget, "listCategories")
        stack = require_child(self.dialog, QStackedWidget, "stackSettings")
        categories.currentRowChanged.connect(stack.setCurrentIndex)
        if categories.currentRow() < 0 and categories.count() > 0:
            categories.setCurrentRow(stack.currentIndex())

    def _setup_ui_language(self) -> None:
        self.combo_ui_language = require_child(self.dialog, QComboBox, "comboUiLanguage")

        raw_language = load_ui_language()
        is_system = not raw_language or raw_language.lower() == DEFAULT_UI_LANGUAGE
        current_language = DEFAULT_UI_LANGUAGE if is_system else normalize_language(raw_language)

        self.combo_ui_language.clear()

        # 先頭に「システム規定」を追加
        self.combo_ui_language.addItem(tr("SettingsDialog", "システム規定"), DEFAULT_UI_LANGUAGE)

        available_languages = self.localization.available_languages
        if not is_system and current_language not in available_languages:
            self.combo_ui_language.addItem(current_language, current_language)

        for code, info in available_languages.items():
            if info.flag_path is not None and info.flag_path.is_file():
                path_str = str(info.flag_path)
                icon = QIcon()
                icon.addFile(path_str, mode=QIcon.Mode.Normal)
                icon.addFile(path_str, mode=QIcon.Mode.Selected)
                icon.addFile(path_str, mode=QIcon.Mode.Active)
                self.combo_ui_language.addItem(icon, info.name, code)
            else:
                self.combo_ui_language.addItem(info.name, code)

        current_index = self.combo_ui_language.findData(current_language)
        self.combo_ui_language.setCurrentIndex(max(current_index, 0))

    def _setup_voice_input(self) -> None:
        self.combo_voice_input = require_child(self.dialog, QComboBox, "comboVoiceInput")
        selected = load_voice_input_provider()
        self.combo_voice_input.addItem(tr("SettingsDialog", "使用しない"), "")
        for provider in self.plugins.voice_inputs.values():
            label = provider.display_name
            if not voice_input_available(provider):
                label = tr("SettingsDialog", "{name}（利用不可）").format(name=label)
            self.combo_voice_input.addItem(label, provider.id)
        if selected and self.combo_voice_input.findData(selected) < 0:
            self.combo_voice_input.addItem(
                tr("SettingsDialog", "{name}（未登録・利用不可）").format(name=selected), selected,
            )
        self.combo_voice_input.setCurrentIndex(max(0, self.combo_voice_input.findData(selected)))

    def _setup_themes_and_icons(self) -> None:
        self.list_themes = require_child(self.dialog, QListWidget, "listThemes")
        self.list_icon_themes = require_child(self.dialog, QListWidget, "listIconThemes")

        current_theme, current_icon_theme = load_theme_settings()
        raw_language = load_ui_language()
        if not raw_language or raw_language.lower() == DEFAULT_UI_LANGUAGE:
            ui_language = system_language()
        else:
            ui_language = normalize_language(raw_language)

        # テーマタイルの生成
        self.list_themes.clear()
        themes = self.theme_manager.available_themes(ui_language)
        selected_theme_row = 0
        for row, (theme_id, info) in enumerate(themes.items()):
            item = QListWidgetItem(info.name)
            item.setData(Qt.ItemDataRole.UserRole, theme_id)
            if info.preview_path and info.preview_path.is_file():
                item.setIcon(QIcon(str(info.preview_path)))
            item.setToolTip(f"{info.name}\n{info.description}" if info.description else info.name)
            self.list_themes.addItem(item)
            if theme_id == current_theme:
                selected_theme_row = row

        if self.list_themes.count() > 0:
            self.list_themes.setCurrentRow(selected_theme_row)

        # アイコンセットタイルの生成
        self.list_icon_themes.clear()
        iconsets = self.icon_manager.available_iconsets(ui_language)
        selected_icon_row = 0
        for row, (icon_id, info) in enumerate(iconsets.items()):
            item = QListWidgetItem(info.name)
            item.setData(Qt.ItemDataRole.UserRole, icon_id)
            if info.preview_path and info.preview_path.is_file():
                item.setIcon(QIcon(str(info.preview_path)))
            item.setToolTip(f"{info.name}\n{info.description}" if info.description else info.name)
            self.list_icon_themes.addItem(item)
            if icon_id == current_icon_theme:
                selected_icon_row = row

        if self.list_icon_themes.count() > 0:
            self.list_icon_themes.setCurrentRow(selected_icon_row)

    def _setup_filter_rules(self) -> None:
        self.combo_rule_adapter = require_child(self.dialog, QComboBox, "comboRuleAdapter")
        self.check_disable_all_builtin = require_child(self.dialog, QCheckBox, "checkDisableAllBuiltin")
        self.table_filter_rules = require_child(self.dialog, QTableWidget, "tableFilterRules")
        self.button_add_rule = require_child(self.dialog, QPushButton, "buttonAddRule")
        self.button_remove_rule = require_child(self.dialog, QPushButton, "buttonRemoveRule")

        # テーブルの列構成（有効、番号、類型、正規表現、例）
        self.table_filter_rules.setColumnCount(5)
        headers = [
            tr("SettingsDialog", "有効"),
            tr("SettingsDialog", "番号"),
            tr("SettingsDialog", "類型"),
            tr("SettingsDialog", "正規表現"),
            tr("SettingsDialog", "例"),
        ]
        self.table_filter_rules.setHorizontalHeaderLabels(headers)
        header = self.table_filter_rules.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        # アダプター選択肢の登録（全登録済みプラグイン）
        self.combo_rule_adapter.clear()
        for adapter in self.plugins.parsers.values():
            adapter_id = adapter.id
            display_name = f"{adapter.name} ({', '.join(sorted(adapter.suffixes))})"
            self.combo_rule_adapter.addItem(display_name, adapter_id)

        self._current_adapter_id = str(self.combo_rule_adapter.currentData() or "")
        if self._current_adapter_id:
            self._load_config_for_adapter(self._current_adapter_id)
        else:
            for widget in (self.check_disable_all_builtin, self.table_filter_rules,
                           self.button_add_rule, self.button_remove_rule):
                widget.setEnabled(False)
        self._populate_rules_table()

        self.combo_rule_adapter.currentIndexChanged.connect(self._on_adapter_changed)
        self.check_disable_all_builtin.toggled.connect(self._on_disable_all_builtin_toggled)
        self.button_add_rule.clicked.connect(self._on_add_rule)
        self.button_remove_rule.clicked.connect(self._on_remove_rule)

    def _load_config_for_adapter(self, adapter_id: str) -> None:
        if adapter_id not in self._filter_configs:
            saved_data = load_adapter_filter_rules(adapter_id)
            default_config = get_default_filter_config(adapter_id, self.plugins.parsers.values())
            config = AdapterFilterConfig.from_dict(saved_data, default_config.rules)
            self._filter_configs[adapter_id] = config

    def _save_current_table_to_config(self) -> None:
        config = self._filter_configs.get(self._current_adapter_id)
        if config is None:
            return

        config.disable_all_builtin = self.check_disable_all_builtin.isChecked()
        updated_rules: list[FilterRule] = []

        for row in range(self.table_filter_rules.rowCount()):
            item_check = self.table_filter_rules.item(row, 0)
            item_type = self.table_filter_rules.item(row, 2)
            item_pattern = self.table_filter_rules.item(row, 3)
            item_example = self.table_filter_rules.item(row, 4)

            rule_id = str(item_check.data(Qt.ItemDataRole.UserRole) or f"rule_{row}") if item_check else f"rule_{row}"
            is_builtin = bool(item_type.data(Qt.ItemDataRole.UserRole)) if item_type else False
            enabled = (item_check.checkState() == Qt.CheckState.Checked) if item_check else True
            rule_type = item_type.text() if item_type else "カスタム"
            pattern = item_pattern.text() if item_pattern else ""
            example = item_example.text() if item_example else ""

            updated_rules.append(
                FilterRule(
                    id=rule_id,
                    enabled=enabled,
                    rule_type=rule_type,
                    pattern=pattern,
                    example=example,
                    is_builtin=is_builtin,
                )
            )

        config.rules = updated_rules

    def _populate_rules_table(self) -> None:
        config = self._filter_configs.get(self._current_adapter_id)
        if config is None:
            return

        self.check_disable_all_builtin.blockSignals(True)
        self.check_disable_all_builtin.setChecked(config.disable_all_builtin)
        self.check_disable_all_builtin.blockSignals(False)

        self.table_filter_rules.setRowCount(len(config.rules))
        for row, rule in enumerate(config.rules):
            # 0: 有効（チェックボックス）
            item_check = QTableWidgetItem()
            item_check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            item_check.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            item_check.setData(Qt.ItemDataRole.UserRole, rule.id)
            self.table_filter_rules.setItem(row, 0, item_check)

            # 1: 番号
            item_num = QTableWidgetItem(str(row + 1))
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_num.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_filter_rules.setItem(row, 1, item_num)

            # 2: 類型
            item_type = QTableWidgetItem(rule.rule_type)
            item_type.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_type.setData(Qt.ItemDataRole.UserRole, rule.is_builtin)
            if rule.is_builtin:
                item_type.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            else:
                item_type.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
            self.table_filter_rules.setItem(row, 2, item_type)

            # 3: 正規表現
            item_pattern = QTableWidgetItem(rule.pattern)
            item_pattern.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
            self.table_filter_rules.setItem(row, 3, item_pattern)

            # 4: 例
            item_example = QTableWidgetItem(rule.example)
            item_example.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
            self.table_filter_rules.setItem(row, 4, item_example)

    def _on_adapter_changed(self, index: int) -> None:
        self._save_current_table_to_config()
        self._current_adapter_id = str(self.combo_rule_adapter.itemData(index))
        self._load_config_for_adapter(self._current_adapter_id)
        self._populate_rules_table()

    def _on_disable_all_builtin_toggled(self, checked: bool) -> None:
        config = self._filter_configs.get(self._current_adapter_id)
        if config is not None:
            config.disable_all_builtin = checked

    def _on_add_rule(self) -> None:
        self._save_current_table_to_config()
        config = self._filter_configs.get(self._current_adapter_id)
        if config is None:
            return

        new_rule = FilterRule(
            id=f"custom_{uuid.uuid4().hex[:8]}",
            enabled=True,
            rule_type="カスタム",
            pattern="",
            example="",
            is_builtin=False,
        )
        config.rules.append(new_rule)
        self._populate_rules_table()

        # 追加した行を選択して正規表現セルを編集状態に
        new_row = len(config.rules) - 1
        self.table_filter_rules.selectRow(new_row)
        pattern_item = self.table_filter_rules.item(new_row, 3)
        if pattern_item is not None:
            self.table_filter_rules.editItem(pattern_item)

    def _on_remove_rule(self) -> None:
        selected_rows = self.table_filter_rules.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        item_type = self.table_filter_rules.item(row, 2)
        is_builtin = bool(item_type.data(Qt.ItemDataRole.UserRole)) if item_type else False

        if is_builtin:
            QMessageBox.information(
                self.dialog,
                tr("SettingsDialog", "ルール削除"),
                tr("SettingsDialog", "事前定義されたルールは削除できません。チェックボックスを外して無効化してください。"),
            )
            return

        self._save_current_table_to_config()
        config = self._filter_configs.get(self._current_adapter_id)
        if config is not None and 0 <= row < len(config.rules):
            config.rules.pop(row)
            self._populate_rules_table()

    def exec(self) -> int:
        old_language = load_ui_language()
        result = super().exec()
        if result != QDialog.DialogCode.Accepted:
            return result

        # UI言語の保存
        new_language = str(self.combo_ui_language.currentData() or "")
        save_ui_language(new_language)
        voice_provider = self.combo_voice_input.currentData()
        if not isinstance(voice_provider, str):
            raise TypeError("Voice input provider ID must be a string")
        save_voice_input_provider(voice_provider)

        # テーマ・アイコンの保存と即時適用
        current_theme_item = self.list_themes.currentItem()
        chosen_theme = str(current_theme_item.data(Qt.ItemDataRole.UserRole)) if current_theme_item else "system"
        current_icon_item = self.list_icon_themes.currentItem()
        chosen_icon = str(current_icon_item.data(Qt.ItemDataRole.UserRole)) if current_icon_item else "default"
        save_theme_settings(chosen_theme, chosen_icon)
        self.theme_manager.apply_theme(chosen_theme)
        self.icon_manager.set_current_iconset(chosen_icon)

        self._save_current_ai_fields()
        save_ai_settings(AiSettings(
            provider_id=self._current_provider_id,
            models=self.ai_models,
            selected_models=self.ai_selected_models,
            api_keys=self.ai_api_keys,
            concurrency=self.spin_concurrency.value(),
        ))
        if new_language != old_language:
            from PySide6.QtCore import QCoreApplication
            app = QCoreApplication.instance()
            if app is None:
                raise RuntimeError("QCoreApplication インスタンスが存在しません")
            self.localization.apply_language(app, new_language)

        # 非表示ルールの保存
        self._save_current_table_to_config()
        for adapter_id, config in self._filter_configs.items():
            save_adapter_filter_rules(adapter_id, config.to_dict())

        # プラグイン提供の設定ページの保存
        for provider, widget in self._plugin_settings_widgets:
            provider.save_settings(widget)

        return result
