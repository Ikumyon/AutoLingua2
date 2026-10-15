from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QStackedWidget, QWidget,
)

from autolingua2.extensions import ExtensionEntrance
from autolingua2.services.language_tags import normalize_language, qt_language_options, system_language
from autolingua2.services.settings_store import load_ai_settings, load_ui_language, save_ui_language
from autolingua2.services.ui_translation import UiTranslationService, coverage, export_ts
from autolingua2.ui.components.searchable_combo_box import enable_combo_search
from autolingua2.ui.i18n import tr
from .base import load_ui, require_child


class SelfTranslationController(QObject):
    applied = Signal(str)
    running_changed = Signal(bool)

    def __init__(self, entrance: ExtensionEntrance, parent: QWidget) -> None:
        super().__init__(parent)
        self.entrance = entrance
        self.widget = load_ui("dialogs/setup/SelfTranslationPage.ui", parent)
        self.service = UiTranslationService(entrance.plugins.providers, self)
        self.options = require_child(self.widget, QWidget, "optionsContainer")
        self.target = require_child(self.widget, QComboBox, "comboTargetLanguage")
        self.custom_button = require_child(self.widget, QPushButton, "buttonCustomLanguage")
        self.custom = require_child(self.widget, QWidget, "customLanguageContainer")
        self.tag_edit = require_child(self.widget, QLineEdit, "editLanguageTag")
        self.name_edit = require_child(self.widget, QLineEdit, "editLanguageName")
        self.provider = require_child(self.widget, QComboBox, "comboProvider")
        self.model = require_child(self.widget, QComboBox, "comboModel")
        self.start_button = require_child(self.widget, QPushButton, "buttonTranslate")
        self.stop_button = require_child(self.widget, QPushButton, "buttonStop")
        self.status = require_child(self.widget, QLabel, "labelStatus")
        self.progress = require_child(self.widget, QProgressBar, "progressTranslation")
        self.coverage_label = require_child(self.widget, QLabel, "labelCoverage")
        self.ai_method = require_child(self.widget, QRadioButton, "radioAi")
        self.method_stack = require_child(self.widget, QStackedWidget, "stackMethod")
        self.export_button = require_child(self.widget, QPushButton, "buttonExport")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh)
        self._choices = qt_language_options()
        for tag, name in self._choices:
            self.target.addItem(f"{name} [{tag}]", tag)
        enable_combo_search(
            self.target,
            action_text=tr("SelfTranslation", "＋一覧にない言語を指定…"),
            on_action=self._open_custom,
        )
        os_tag = system_language()
        self.custom_button.setChecked(self.target.findData(os_tag) < 0)
        self._custom_changed(self.custom_button.isChecked())
        self.target.setEnabled(not self.custom_button.isChecked())
        self.target.setCurrentIndex(max(0, self.target.findData(os_tag)))
        self.tag_edit.setText(os_tag)
        self.name_edit.setText(QLocale.system().nativeLanguageName() or os_tag)
        self.target.currentIndexChanged.connect(self._schedule)
        self.tag_edit.textChanged.connect(self._schedule)
        self.name_edit.textChanged.connect(self._schedule)
        self.custom_button.toggled.connect(self._custom_changed)
        self.provider.currentIndexChanged.connect(self._models)
        self.model.currentIndexChanged.connect(self._schedule)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self.cancel)
        self.export_button.clicked.connect(self._export)
        self.ai_method.toggled.connect(self._method_changed)
        self.service.progress.connect(self._progress)
        self.service.running_changed.connect(self._running)
        self.service.failed.connect(self.status.setText)
        self.service.completed.connect(self._committed)
        self.stop_button.setEnabled(False)
        self.refresh_ai()
        self._method_changed()

    def _method_changed(self) -> None:
        ai = self.ai_method.isChecked()
        self.method_stack.setCurrentIndex(0 if ai else 1)
        self.start_button.setVisible(ai)
        self.stop_button.setVisible(ai)
        self.progress.setVisible(ai)
        self.export_button.setVisible(not ai)
        self._refresh()

    @property
    def busy(self) -> bool:
        return self.service.busy

    def needs_os_translation(self) -> bool:
        return coverage(system_language(), self.entrance.localization.available_languages).missing > 0

    def refresh_ai(self) -> None:
        if self.busy:
            return
        settings = load_ai_settings(self.entrance.plugins.providers)
        selected = self.provider.currentData()
        self.provider.blockSignals(True)
        self.provider.clear()
        for provider in self.entrance.plugins.providers.providers.values():
            key = settings.api_keys.get(provider.id, "") or self.entrance.plugins.providers.get_env_api_key(provider.id)
            if key:
                self.provider.addItem(provider.display_name, provider.id)
        self.provider.setCurrentIndex(max(0, self.provider.findData(selected or settings.provider_id)))
        self.provider.blockSignals(False)
        self._models()

    def _models(self) -> None:
        settings = load_ai_settings(self.entrance.plugins.providers)
        identifier = self.provider.currentData()
        self.model.clear()
        if isinstance(identifier, str):
            for item in settings.models.get(identifier, []):
                if item.enabled:
                    self.model.addItem(item.name, item.model)
            self.model.setCurrentIndex(max(0, self.model.findData(settings.selected_models.get(identifier, ""))))
        self._schedule()

    def _open_custom(self) -> None:
        self.custom_button.setChecked(True)
        self.tag_edit.setFocus()
        self.tag_edit.selectAll()

    def _custom_changed(self, checked: bool) -> None:
        self.custom.setVisible(checked)
        self.target.setEnabled(not checked)
        self.custom_button.setText(
            tr("SelfTranslation", "一覧から選択に戻る") if checked
            else tr("SelfTranslation", "一覧にない言語を指定")
        )
        self._schedule()

    def _schedule(self) -> None:
        if not self.busy:
            self.start_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self._timer.start()

    def _target(self) -> tuple[str, str]:
        if self.custom_button.isChecked():
            tag = normalize_language(self.tag_edit.text())
            name = self.name_edit.text().strip()
            if not name:
                raise ValueError(tr("SelfTranslation", "言語の表示名を入力してください。"))
            return tag, name
        index = self.target.currentIndex()
        if 0 <= index < len(self._choices):
            return self._choices[index]
        raise ValueError(tr("SelfTranslation", "翻訳先を候補から選択してください。"))

    def _refresh(self) -> None:
        if self.busy:
            return
        try:
            tag, _ = self._target()
            self.export_button.setEnabled(True)
            if not self.ai_method.isChecked():
                self.start_button.setEnabled(False)
                return
            state = coverage(tag, self.entrance.localization.available_languages)
            self.coverage_label.setText(tr("SelfTranslation", "未翻訳: {missing} / {total} 件").format(
                missing=state.missing, total=state.total,
            ))
            self.start_button.setEnabled(state.missing > 0 and self.provider.currentIndex() >= 0
                                         and self.model.currentIndex() >= 0)
        except Exception as error:
            self.status.setText(str(error))
            self.start_button.setEnabled(False)
            self.export_button.setEnabled(False)

    def _export(self) -> None:
        try:
            tag, _ = self._target()
            selected = QFileDialog.getExistingDirectory(self.widget, tr("SelfTranslation", "TSの保存先を選択"))
            if not selected:
                return
            folder = Path(selected)
            try:
                count = export_ts(folder, tag)
            except FileExistsError as error:
                answer = QMessageBox.question(
                    self.widget, tr("SelfTranslation", "TSの上書き確認"),
                    tr("SelfTranslation", "次のファイルを上書きしますか？\n{files}").format(files=str(error)),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                count = export_ts(folder, tag, overwrite=True)
            self.status.setText(tr("SelfTranslation", "{count}個のTSを保存しました: {folder}").format(
                count=count, folder=folder,
            ))
        except Exception as error:
            self.status.setText(str(error))

    def _start(self) -> None:
        try:
            tag, name = self._target()
            provider_id, model = self.provider.currentData(), self.model.currentData()
            if not isinstance(provider_id, str) or not isinstance(model, str):
                raise ValueError(tr("SelfTranslation", "利用するAIとモデルを選択してください。"))
            self.service.start(tag, name, provider_id, model, self.entrance.localization.available_languages)
        except Exception as error:
            self.status.setText(str(error))

    def _running(self, running: bool) -> None:
        self.options.setEnabled(not running)
        self.export_button.setEnabled(not running)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(running)
        self.running_changed.emit(running)
        if not running:
            # Refresh only the action state; preserve completion/error text.
            try:
                tag, _ = self._target()
                self.start_button.setEnabled(coverage(tag, self.entrance.localization.available_languages).missing > 0
                                             and self.provider.currentIndex() >= 0 and self.model.currentIndex() >= 0)
            except Exception:
                self.start_button.setEnabled(False)

    def _progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(tr("SelfTranslation", "翻訳中: {done} / {total} 件").format(done=done, total=total))
        if done == total:
            self.status.setText(tr("SelfTranslation", "翻訳辞書を作成しています…"))

    def _committed(self, tag: str, folder_name: str) -> None:
        folder = Path(folder_name)
        old_language = load_ui_language()
        try:
            app = QCoreApplication.instance()
            if app is None:
                raise RuntimeError("QCoreApplication インスタンスが存在しません")
            self.entrance.register_resource("ui_translation", folder)
            save_ui_language(tag)
            self.entrance.localization.apply_language(app, tag)
            self.service.confirm()
            self.status.setText(tr("SelfTranslation", "翻訳を保存し、表示言語を切り替えました。"))
            self.applied.emit(tag)
        except Exception as error:
            self.service.reject(str(error))
            try:
                self.entrance.unregister_ui_translation(folder)
                if (folder / "metadata.json").is_file():
                    self.entrance.register_resource("ui_translation", folder)
                save_ui_language(old_language)
                app = QCoreApplication.instance()
                if app is not None:
                    self.entrance.localization.apply_language(app, old_language)
            except Exception as restore_error:
                self.status.setText(f"{error}\n{restore_error}")

    def cancel(self) -> None:
        self._timer.stop()
        self.service.cancel()
