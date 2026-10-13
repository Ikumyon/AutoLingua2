from __future__ import annotations

from copy import deepcopy
from typing import Callable

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QLabel, QLineEdit, QPushButton, QRadioButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from autolingua2.extensions import ExtensionEntrance
from autolingua2.plugins.api import AiSetupCallbacks, AiSetupOption, AiSetupPanel
from autolingua2.services.ai_network import AiNetworkClient
from autolingua2.services.ai_providers.registry import ProviderRegistry
from autolingua2.services.settings_store import (
    DEFAULT_UI_LANGUAGE, AiSetupValues, load_ai_settings, load_ui_language,
    mark_initial_setup_seen, save_initial_setup, save_ui_language,
)
from autolingua2.ui.components.ai_model_list import ModelListController
from autolingua2.ui.i18n import normalize_language, tr
from autolingua2.ui.icons import IconManager
from .base import load_ui, require_child
from .self_translation import SelfTranslationController


def create_plugin_panel(
    option: AiSetupOption, parent: QWidget, initial: AiSetupValues, callbacks: AiSetupCallbacks,
) -> AiSetupPanel:
    factory = option.create_panel
    if factory is None:
        raise ValueError("設定画面が登録されていません。")
    panel = factory(parent, deepcopy(initial), callbacks)
    if (not isinstance(panel, AiSetupPanel) or not isinstance(panel.widget, QWidget)
            or not isinstance(panel.ready, bool)):
        raise TypeError("設定画面の公開契約が不正です。")
    panel.widget.setParent(parent)
    return panel


class CommonSetupPanel(QObject):
    def __init__(
        self, option: AiSetupOption, registry: ProviderRegistry, icons: IconManager,
        parent: QWidget, initial: AiSetupValues, ready_changed: Callable[[bool], None],
    ) -> None:
        super().__init__(parent)
        self.widget = load_ui("dialogs/setup/AiSetupPage.ui", parent)
        self.option = option
        self.registry = registry
        self._notify_ready = ready_changed
        self._ready = False
        self._client: AiNetworkClient | None = None
        self._auth: AiSetupPanel | None = None
        self._api_key = initial.api_key
        self.edit_key = require_child(self.widget, QLineEdit, "editApiKey")
        self.status = require_child(self.widget, QLabel, "labelStatus")
        self.test_button = require_child(self.widget, QPushButton, "buttonTestConnection")
        self.models = ModelListController(
            require_child(self.widget, QWidget, "modelContainer"),
            require_child(self.widget, QVBoxLayout, "layoutModelList"), icons,
        )
        self.models.populate(list(initial.models))
        self.models.changed.connect(self._models_changed)
        self.edit_key.setText(initial.api_key)
        self.edit_key.textChanged.connect(self._key_changed)
        require_child(self.widget, QPushButton, "buttonAddModel").clicked.connect(self.models.add_empty)
        require_child(self.widget, QPushButton, "buttonResetModels").clicked.connect(self._reset_models)
        self.test_button.clicked.connect(self._test)
        if option.mode == "auth":
            self.edit_key.hide()
            require_child(self.widget, QLabel, "labelApiKey").hide()
            container = require_child(self.widget, QWidget, "authContainer")
            self._auth = create_plugin_panel(
                option, container, initial, AiSetupCallbacks(self._auth_changed, lambda ready: None),
            )
            require_child(self.widget, QVBoxLayout, "layoutAuth").addWidget(self._auth.widget)
            self._auth_changed()
        self._refresh_ready()

    @property
    def ready(self) -> bool:
        return self._ready

    def _refresh_ready(self) -> None:
        rows = [row for row in self.models.rows if row.check_enabled.isChecked()]
        identifiers = [row.field_model.text().strip() for row in rows]
        self._ready = bool(
            self._api_key.strip() and rows and all(identifiers)
            and len(set(identifiers)) == len(identifiers)
            and self._client is None and all(row._status == "valid" for row in rows)
        )
        self._notify_ready(self._ready)

    def _stop_test(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            client.cancel_all()
            client.deleteLater()
        for row in self.models.rows:
            if row._status == "testing":
                row.set_status(None)
        self.test_button.setEnabled(True)

    def _key_changed(self, key: str) -> None:
        self._api_key = key.strip()
        self._stop_test()
        self.models.invalidate()
        self.status.setText(tr("InitialSetupDialog", "未確認"))
        self._refresh_ready()

    def _auth_changed(self) -> None:
        if self._auth is None:
            return
        try:
            values = self._auth.read_settings()
            if not isinstance(values, AiSetupValues):
                raise TypeError("認証情報の公開契約が不正です。")
            if values.api_key != self._api_key:
                self._key_changed(values.api_key)
            self.models.populate(list(values.models))
        except Exception as error:
            self._key_changed("")
            self.status.setText(str(error))

    def _models_changed(self) -> None:
        self._stop_test()
        self.status.setText(tr("InitialSetupDialog", "未確認"))
        self._refresh_ready()

    def _reset_models(self) -> None:
        self._stop_test()
        self.models.populate(self.registry.get_default_models(self.option.provider_id))

    def _test(self) -> None:
        self._stop_test()
        provider = self.registry.get(self.option.provider_id)
        rows = [row for row in self.models.rows if row.check_enabled.isChecked()]
        models = [row.field_model.text().strip() for row in rows]
        if (provider is None or not self._api_key.strip() or not models or not all(models)
                or len(set(models)) != len(models)):
            self.status.setText(tr("InitialSetupDialog", "認証情報と重複のない有効なモデルを設定してください。"))
            self._refresh_ready()
            return
        client = AiNetworkClient(self)
        self._client = client
        for row in rows:
            row.set_status("testing", tr("InitialSetupDialog", "検証中..."))
        client.model_validated.connect(
            lambda model, valid, message: self._result(client, model, valid, message),
        )
        client.all_validated.connect(lambda success, errors: self._tested(client, success, errors))
        self.test_button.setEnabled(False)
        self.status.setText(tr("InitialSetupDialog", "検証中..."))
        self._refresh_ready()
        client.validate_models(provider, self._api_key, models)

    def _result(self, client: AiNetworkClient, model: str, valid: bool, message: str) -> None:
        if self._client is not client:
            return
        for row in self.models.rows:
            if row.field_model.text().strip() == model:
                row.set_status("valid" if valid else "invalid", message)

    def _tested(self, client: AiNetworkClient, success: int, errors: int) -> None:
        if self._client is not client:
            return
        self._client = None
        client.deleteLater()
        self.test_button.setEnabled(True)
        self.status.setText(tr("InitialSetupDialog", "利用可能: {success} 件 / エラー: {errors} 件").format(
            success=success, errors=errors,
        ))
        self._refresh_ready()

    def read_settings(self) -> AiSetupValues:
        return AiSetupValues(self._api_key, tuple(self.models.read()))

    def save_settings(self) -> None:
        if self._auth is not None:
            self._auth.save_settings()

    def cancel(self) -> None:
        self._stop_test()
        if self._auth is not None:
            self._auth.cancel()
        self._refresh_ready()


class InitialSetupController(QObject):
    """Host navigation and persistence; providers contribute only through the entrance."""

    def __init__(self, entrance: ExtensionEntrance, parent: QWidget) -> None:
        super().__init__(parent)
        loaded = load_ui("dialogs/setup/InitialSetupDialog.ui", parent)
        if not isinstance(loaded, QDialog):
            raise TypeError("初期設定のUIはQDialogである必要があります。")
        self.dialog = loaded
        self.dialog.setWindowTitle(f"{QCoreApplication.applicationName()} {tr('InitialSetupDialog', '初期設定')}")
        self.dialog.setModal(True)
        self.entrance = entrance
        self.registry = entrance.plugins.providers
        self.stack = require_child(loaded, QStackedWidget, "stackPages")
        self.language_page = load_ui("dialogs/setup/LanguagePage.ui", self.stack)
        self.stack.insertWidget(0, self.language_page)
        self.stack.setCurrentWidget(self.language_page)
        self.combo_language = require_child(self.language_page, QComboBox, "comboLanguage")
        self.choose_page = require_child(loaded, QWidget, "pageChooseAi")
        self.configure_page = require_child(loaded, QWidget, "pageConfigureAi")
        self.container = require_child(loaded, QWidget, "setupContainer")
        self.error = require_child(loaded, QLabel, "labelError")
        self.back = require_child(loaded, QPushButton, "buttonBack")
        self.next = require_child(loaded, QPushButton, "buttonNext")
        self.finish = require_child(loaded, QPushButton, "buttonFinish")
        self._option: AiSetupOption | None = None
        self._session: AiSetupPanel | None = None
        self._epoch = 0
        self._allow_close = False
        self.saved = False
        self.self_translation = SelfTranslationController(entrance, self.stack)
        self.stack.addWidget(self.self_translation.widget)
        self.check_self_translation = require_child(self.language_page, QCheckBox, "checkSelfTranslation")
        self.check_self_translation.setChecked(self.self_translation.needs_os_translation())
        self.check_self_translation.toggled.connect(self._navigation)
        self.self_translation.running_changed.connect(self._navigation)
        self.self_translation.applied.connect(self._language_created)
        self._group = QButtonGroup(loaded)
        self._setup_language()
        self.combo_language.currentIndexChanged.connect(self._navigation)
        self.back.clicked.connect(self._back)
        self.next.clicked.connect(self._next)
        self.finish.clicked.connect(self._finish)
        require_child(loaded, QPushButton, "buttonSkip").clicked.connect(self._skip)
        loaded.installEventFilter(self)
        settings = load_ai_settings(self.registry)
        options = entrance.plugins.ai_setup_options
        require_child(loaded, QLabel, "labelNoOptions").setVisible(not options)
        layout = require_child(loaded, QVBoxLayout, "layoutOptions")
        for option in options:
            radio = QRadioButton(option.title, loaded)
            self._group.addButton(radio)
            layout.addWidget(radio)
            if option.description:
                description = QLabel(option.description, loaded)
                description.setWordWrap(True)
                layout.addWidget(description)
            radio.toggled.connect(lambda checked, item=option: self._choose(item) if checked else None)
            if option.provider_id == settings.provider_id:
                radio.setChecked(True)
        layout.addStretch()
        self.stack.currentChanged.connect(self._navigation)
        self._navigation()

    def _setup_language(self) -> None:
        self.combo_language.blockSignals(True)
        self.combo_language.clear()
        raw_language = load_ui_language()
        is_system = not raw_language or raw_language.lower() == DEFAULT_UI_LANGUAGE
        current_language = DEFAULT_UI_LANGUAGE if is_system else normalize_language(raw_language)
        self.combo_language.addItem(tr("SettingsDialog", "システム規定"), DEFAULT_UI_LANGUAGE)
        languages = self.entrance.localization.available_languages
        if not is_system and current_language not in languages:
            current_language = self.entrance.localization.resolve_language(current_language)
        for code, info in languages.items():
            if info.flag_path is not None and info.flag_path.is_file():
                icon = self.entrance.icons.load_icon(info.flag_path, fixed_modes=True)
                self.combo_language.addItem(icon, info.name, code)
            else:
                self.combo_language.addItem(info.name, code)
        self.combo_language.setCurrentIndex(max(0, self.combo_language.findData(current_language)))
        self.combo_language.blockSignals(False)

    def _language_created(self, tag: str) -> None:
        self._setup_language()
        self._navigation()

    def _wants_self_translation(self) -> bool:
        return self.check_self_translation.isChecked()

    def _save_language(self) -> None:
        language = self.combo_language.currentData()
        if not isinstance(language, str) or not language:
            raise ValueError("表示言語を選択してください。")
        app = QCoreApplication.instance()
        if app is None:
            raise RuntimeError("QCoreApplication インスタンスが存在しません")
        if language != load_ui_language():
            save_ui_language(language)
            self.entrance.localization.apply_language(app, language)

    def _navigation(self) -> None:
        choosing_language = self.stack.currentWidget() is self.language_page
        configuring = self.stack.currentWidget() is self.configure_page
        translating = self.stack.currentWidget() is self.self_translation.widget
        ready = self._session is not None and self._session.ready
        busy = self.self_translation.busy
        self.back.setVisible(not choosing_language)
        self.back.setEnabled(not busy)
        self.next.setVisible(not translating and (not configuring or self._wants_self_translation()))
        self.next.setEnabled(not busy and (self.combo_language.currentIndex() >= 0 if choosing_language
                                          else ready if configuring else self._option is not None))
        self.finish.setVisible(translating or configuring and not self._wants_self_translation())
        self.finish.setEnabled(not busy and (translating or configuring and ready))
        self.dialog.setWindowTitle(f"{QCoreApplication.applicationName()} {tr('InitialSetupDialog', '初期設定')}")
        self.combo_language.setItemText(0, tr("SettingsDialog", "システム規定"))
        # Derive labels from the page list so earlier/later pages can be inserted.
        titles = [self.stack.widget(index) for index in range(self.stack.count())
                  if self._wants_self_translation() or self.stack.widget(index) is not self.self_translation.widget]
        require_child(self.dialog, QLabel, "labelSteps").setText(" → ".join(
            page.accessibleName() for page in titles if page is not None
        ))

    def _choose(self, option: AiSetupOption) -> None:
        if self._option is not option:
            self._dispose()
            self._option = option
        self.error.clear()
        self._navigation()

    def _dispose(self) -> None:
        self._epoch += 1
        session = self._session
        self._session = None
        if session is not None:
            try:
                session.cancel()
            finally:
                require_child(self.container, QVBoxLayout, "layoutSetupPanel").removeWidget(session.widget)
                session.widget.deleteLater()
                if isinstance(session, QObject):
                    session.deleteLater()

    def _ready_changed(self, epoch: int) -> None:
        if epoch == self._epoch and not self._allow_close:
            self._navigation()

    def _next(self) -> None:
        if self.stack.currentWidget() is self.configure_page:
            try:
                self._save_ai()
                self.self_translation.refresh_ai()
                self.stack.setCurrentWidget(self.self_translation.widget)
                self.error.clear()
            except Exception as error:
                self.error.setText(str(error))
            return
        if self.stack.currentWidget() is self.language_page:
            try:
                self._save_language()
                self.error.clear()
                self.stack.setCurrentWidget(self.choose_page)
            except Exception as error:
                self.error.setText(str(error))
            return
        option = self._option
        if option is None:
            return
        try:
            if self._session is None:
                settings = load_ai_settings(self.registry)
                models = settings.models.get(option.provider_id)
                if models is None:
                    models = self.registry.get_default_models(option.provider_id)
                initial = AiSetupValues(
                    settings.api_keys.get(option.provider_id, "") or self.registry.get_env_api_key(option.provider_id),
                    tuple(deepcopy(models)),
                )
                epoch = self._epoch
                callbacks = AiSetupCallbacks(
                    lambda: self._ready_changed(epoch), lambda ready: self._ready_changed(epoch),
                )
                if option.mode == "custom":
                    session = create_plugin_panel(option, self.container, initial, callbacks)
                else:
                    session = CommonSetupPanel(
                        option, self.registry, self.entrance.icons, self.container, initial,
                        callbacks.ready_changed,
                    )
                self._session = session
                require_child(self.container, QVBoxLayout, "layoutSetupPanel").addWidget(session.widget)
            require_child(self.dialog, QLabel, "labelProviderTitle").setText(option.title)
            self.error.clear()
            self.stack.setCurrentWidget(self.configure_page)
            self._navigation()
        except Exception as error:
            self.error.setText(str(error))

    def _back(self) -> None:
        try:
            if self.stack.currentWidget() is self.self_translation.widget:
                self.self_translation.cancel()
                self.stack.setCurrentWidget(self.choose_page)
            elif self.stack.currentWidget() is self.configure_page:
                if self._session is not None:
                    self._session.cancel()
                self.stack.setCurrentWidget(self.choose_page)
            else:
                self.stack.setCurrentWidget(self.language_page)
            self.error.clear()
            self._navigation()
        except Exception as error:
            self.error.setText(str(error))

    def _save_ai(self) -> None:
        session, option = self._session, self._option
        if session is None or option is None or not session.ready:
            raise ValueError("AI設定の接続検証を完了してください。")
        values = session.read_settings()
        if not isinstance(values, AiSetupValues):
            raise TypeError("設定値の公開契約が不正です。")
        session.save_settings()
        save_initial_setup(self.registry, option.provider_id, values)
        self.saved = True
        self._dispose()

    def _finish(self) -> None:
        if self.self_translation.busy:
            return
        try:
            if self.stack.currentWidget() is self.configure_page:
                self._save_ai()
            mark_initial_setup_seen()
            self._allow_close = True
            self._dispose()
            self.dialog.accept()
        except Exception as error:
            self.error.setText(str(error))

    def _skip(self) -> None:
        try:
            self.self_translation.cancel()
            if self._session is not None:
                self._session.cancel()
            self._save_language()
            mark_initial_setup_seen()
            self._allow_close = True
            self._dispose()
            self.dialog.reject()
        except Exception as error:
            self.error.setText(str(error))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.dialog and not self._allow_close:
            if event.type() == QEvent.Type.Close or (
                isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self._skip()
                return True
        return super().eventFilter(watched, event)

    def exec(self) -> int:
        return self.dialog.exec()
