from __future__ import annotations
import json

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from autolingua2.services.ai_network import AiNetworkClient
from autolingua2.services.ai_providers import ProviderRegistry
from autolingua2.services.settings_store import AiModel, AiSettings, save_ai_settings
from autolingua2.ir.translation import LowModelRange, ModelSelection
from autolingua2.ui.components.ai_model_row import ModelRowWidget
from autolingua2.ui.components.ai_model_list import ModelListController
from autolingua2.ui.i18n import tr
from autolingua2.ui.icons import IconManager
from .base import require_child


class AiSettingsPageController(QObject):
    """AI設定の編集状態と接続・保存前検証を管理する。"""

    save_ready = Signal()
    save_aborted = Signal()
    show_requested = Signal()

    def __init__(
        self, dialog: QDialog, registry: ProviderRegistry, icon_manager: IconManager,
        provider_id: str, models: dict[str, list[AiModel]],
        selected_models: dict[str, str], api_keys: dict[str, str], concurrency: int,
        high_model: ModelSelection | None = None, low_model: ModelSelection | None = None,
        low_model_range: LowModelRange = LowModelRange.STANDARD,
    ) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.icon_manager = icon_manager
        self.ai_client = AiNetworkClient(self)
        self.ai_client.model_validated.connect(self._on_model_validated)
        self.ai_client.all_validated.connect(self._on_all_models_validated)
        self._testing_for_save = False
        self._validation_cancelled = False
        self._unvalidated_models_for_save: list[ModelRowWidget] = []
        self._test_results: dict[str, tuple[bool, str]] = {}
        self._setup_ai(registry, provider_id, models, selected_models, api_keys, concurrency)
        self.combo_high = require_child(dialog, QComboBox, "comboHighModel")
        self.combo_low = require_child(dialog, QComboBox, "comboLowModel")
        self.slider_low_range = require_child(dialog, QSlider, "sliderLowModelRange")
        self.label_low_range = require_child(dialog, QLabel, "labelLowModelDescription")
        self._refresh_translation_models(high_model, low_model)
        self.slider_low_range.setValue(list(LowModelRange).index(low_model_range))
        self.slider_low_range.valueChanged.connect(self._update_low_description)
        self._update_low_description()
        self._translation_refresh_pending = False
        self.model_list.changed.connect(self._queue_translation_models_refresh)

    def settings(self) -> AiSettings:
        self._save_current_ai_fields()
        return AiSettings(
            provider_id=self.selected_provider_id, models=self.ai_models,
            selected_models=self.ai_selected_models, api_keys=self.ai_api_keys,
            concurrency=self.spin_concurrency.value(),
            high_model=self._assignment(self.combo_high), low_model=self._assignment(self.combo_low),
            low_model_range=list(LowModelRange)[self.slider_low_range.value()],
        )

    @staticmethod
    def _assignment(combo: QComboBox) -> ModelSelection | None:
        value = combo.currentData()
        if not isinstance(value, str) or not value:
            return None
        provider_id, model_id = json.loads(value)
        if not isinstance(provider_id, str) or not isinstance(model_id, str):
            raise ValueError("翻訳モデルの選択が不正です。")
        return ModelSelection(provider_id, model_id)

    def _refresh_translation_models(self, high: ModelSelection | None, low: ModelSelection | None) -> None:
        for combo, selected in ((self.combo_high, high), (self.combo_low, low)):
            combo.clear()
            combo.addItem(tr("SettingsDialog", "未設定"), "")
            for provider_id, models in self.ai_models.items():
                provider = self.registry.get(provider_id)
                if provider is None:
                    continue
                for model in models:
                    if model.enabled and model.model.strip():
                        combo.addItem(f"{provider.display_name} / {model.name}", json.dumps([provider_id, model.model]))
            if selected is not None:
                data = json.dumps([selected.provider_id, selected.model_id])
                index = combo.findData(data)
                if index < 0:
                    combo.addItem(tr("SettingsDialog", "利用不可：{provider} / {model}").format(
                        provider=selected.provider_id, model=selected.model_id), data)
                    index = combo.count() - 1
                combo.setCurrentIndex(index)

    def _translation_models_changed(self) -> None:
        self._translation_refresh_pending = False
        high, low = self._assignment(self.combo_high), self._assignment(self.combo_low)
        self._save_current_ai_fields()
        self._refresh_translation_models(high, low)

    def _queue_translation_models_refresh(self) -> None:
        if not self._translation_refresh_pending:
            self._translation_refresh_pending = True
            QTimer.singleShot(0, self._translation_models_changed)

    def _update_low_description(self, _value: int = 0) -> None:
        a, b, similarity = list(LowModelRange)[self.slider_low_range.value()].bounds
        self.label_low_range.setText(tr("SettingsDialog", "{a}文字以下の変更、または{b}文字以下かつ類似度{s}%以上を低へ").format(
            a=a, b=b, s=round(similarity * 100)))

    def save(self) -> None:
        save_ai_settings(self.settings())

    def cancel(self) -> None:
        testing_for_save = self._testing_for_save
        self._testing_for_save = False
        self._validation_cancelled = True
        self.ai_client.cancel_all()
        if testing_for_save:
            self.save_aborted.emit()

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
        self.model_list = ModelListController(self.scroll_area_models, self.layout_model_list, self.icon_manager)

        self.combo_provider.clear()
        for plugin in self.registry.providers.values():
            self.combo_provider.addItem(plugin.display_name, plugin.id)
        if self.combo_provider.findData(provider_id) < 0:
            self.combo_provider.addItem(f"{provider_id} (利用不可)", provider_id)
        self.combo_provider.setCurrentIndex(self.combo_provider.findData(provider_id))
        self._current_provider_id = provider_id
        self._ensure_provider_api_key(provider_id)

        self.edit_api_key.setText(self.ai_api_keys.get(provider_id, ""))
        self._populate_models()

        self.error_label = require_child(self.dialog, QLabel, "labelProviderErrors")
        self._refresh_provider_errors()
        self.label_api_key = self.dialog.findChild(QLabel, "labelApiKey")
        self.stack_auth = self.dialog.findChild(QStackedWidget, "stackAuth")
        self.page_default_auth = self.dialog.findChild(QWidget, "pageDefaultAuth")
        self._custom_auth_widgets: dict[str, QWidget] = {}

        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        self._update_auth_ui()
        self.button_add_model.clicked.connect(self._add_model)
        self.button_reset_models.clicked.connect(self._reset_models)
        self.button_test_connection = self.dialog.findChild(QPushButton, "buttonTestConnection")
        if self.button_test_connection is not None:
            self.button_test_connection.setEnabled(True)
            self.button_test_connection.clicked.connect(self._on_test_connection)

    def _on_test_connection(self) -> None:
        api_key = self.ai_api_keys.get(self._current_provider_id, "").strip() or self.edit_api_key.text().strip()
        if not api_key:
            QMessageBox.warning(
                self.dialog,
                tr("SettingsDialog", "接続テスト"),
                tr("SettingsDialog", "認証情報（APIキーまたはトークン）が設定されていません。"),
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
        if self._validation_cancelled:
            return
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

        test_results = self._test_results
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

    def validate_for_save(self) -> None:
        self._validation_cancelled = False
        self._save_current_ai_fields()
        api_key = self.ai_api_keys.get(self._current_provider_id, "").strip() or self.edit_api_key.text().strip()
        provider = self.registry.get(self._current_provider_id)

        # 未検証の有効モデルがあるかチェック（有効かつモデル名あり、かつ status != "valid"）
        untested_rows = [
            r for r in self._row_widgets
            if r.check_enabled.isChecked() and r.field_model.text().strip() and r._status != "valid"
        ]

        # 検証が不要な場合は保存処理へ進む。
        if not untested_rows or not api_key or provider is None:
            self.save_ready.emit()
            return

        # 未検証モデルがある場合：保存前に非同期自動テストを実行
        self._testing_for_save = True
        self._unvalidated_models_for_save = untested_rows

        for r in untested_rows:
            r.set_status(None, tr("SettingsDialog", "保存前チェック中..."))

        models = [r.field_model.text().strip() for r in untested_rows]
        self.ai_client.validate_models(provider, api_key, models, timeout_sec=8.0)

    def _handle_save_validation_result(self, success_count: int, error_count: int) -> None:
        # エラーがあった場合
        if error_count > 0:
            # 1. 自動でAI設定ページへ画面切り替え
            self.show_requested.emit()

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
                self.save_ready.emit()
            else:
                self.save_aborted.emit()
            return

        # すべて有効だった場合は保存処理へ進む。
        self.save_ready.emit()

    def _populate_models(self) -> None:
        self.model_list.populate(self.ai_models.get(self._current_provider_id, []))

    @property
    def _row_widgets(self) -> list[ModelRowWidget]:
        return self.model_list.rows

    def _read_model_list(self) -> list[AiModel]:
        return self.model_list.read()

    def _add_model(self) -> None:
        self.model_list.add_empty()

    def _refresh_provider_errors(self) -> None:
        messages = list(self.registry.errors)
        if self._current_provider_id not in self.registry.providers:
            messages.insert(0, f"選択中の Provider は利用できません: {self._current_provider_id}")
        self.error_label.setText("\n".join(messages))

    def _save_current_ai_fields(self) -> None:
        self.ai_models[self._current_provider_id] = self._read_model_list()
        if self._current_provider_id not in self._custom_auth_widgets:
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
        self._update_auth_ui()
        self._refresh_provider_errors()

    def _update_auth_ui(self) -> None:
        provider = self.registry.get(self._current_provider_id)
        if provider is None or self.stack_auth is None:
            return

        if self._current_provider_id not in self._custom_auth_widgets:
            custom_widget = provider.create_settings_widget(
                self.stack_auth,
                current_api_key=self.ai_api_keys.get(self._current_provider_id, ""),
                on_api_key_changed=lambda key: self._on_plugin_api_key_changed(self._current_provider_id, key),
            )
            if custom_widget is not None:
                self.stack_auth.addWidget(custom_widget)
                self._custom_auth_widgets[self._current_provider_id] = custom_widget

        custom_widget = self._custom_auth_widgets.get(self._current_provider_id)
        if custom_widget is not None:
            self.stack_auth.setCurrentWidget(custom_widget)
            if self.label_api_key is not None:
                self.label_api_key.setText(getattr(provider, "auth_label", tr("SettingsDialog", "アカウント")))
        else:
            if self.page_default_auth is not None:
                self.stack_auth.setCurrentWidget(self.page_default_auth)
            if self.label_api_key is not None:
                self.label_api_key.setText(tr("SettingsDialog", "APIキー"))

    def _on_plugin_api_key_changed(self, provider_id: str, new_key: str) -> None:
        self.ai_api_keys[provider_id] = new_key

    @property
    def selected_provider_id(self) -> str:
        return self._current_provider_id
