from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialogButtonBox, QLabel, QMessageBox, QPushButton, QSplitter,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QWidget,
)

from autolingua2.extensions import ExtensionEntrance
from autolingua2.plugins.api import SettingsPageProvider
from autolingua2.services.settings_store import AiModel
from autolingua2.ir.translation import LowModelRange, ModelSelection
from autolingua2.ui.i18n import tr
from .base import SimpleDialogController, load_ui, require_child
from .glossary import GlossaryPageController
from .settings_ai import AiSettingsPageController
from .settings_filter_rules import FilterRulesPageController
from .settings_general import GeneralSettingsPageController
from .settings_tone import TonePageController
from .source_watch import WatchPageController
from .settings_mcp import McpSettingsPage
from autolingua2.services.mcp_server import McpServer


class SettingsDialogController(SimpleDialogController):
    """設定カテゴリの配置と、各ページの保存を取りまとめる。"""

    def __init__(
        self, entrance: ExtensionEntrance, parent: QWidget | None = None,
        provider_id: str = "openai", models: dict[str, list[AiModel]] | None = None,
        selected_models: dict[str, str] | None = None,
        api_keys: dict[str, str] | None = None,
        concurrency: int = 4,
        *, high_model: ModelSelection | None = None, low_model: ModelSelection | None = None,
        low_model_range: LowModelRange = LowModelRange.STANDARD, glossary_languages: dict[str, str] | None = None,
        glossary_adapter_id: str = "", glossary_game_id: str = "",
        glossary_id: str = "", glossary_source_language: str = "",
        glossary_target_language: str = "", tone_id: str = "",
        on_saved: Callable[[SettingsDialogController], None] | None = None,
        mcp_server: McpServer | None = None,
    ) -> None:
        super().__init__("dialogs/settings/SettingsDialog.ui", parent)
        self.plugins = entrance.plugins
        self.icon_manager = entrance.icons
        self._on_saved = on_saved
        self._saving = False
        self._close_after_save = False
        self._saving_category = "tone"
        self._save_category: QTreeWidgetItem | None = None
        self._plugin_settings_widgets: list[tuple[SettingsPageProvider, QWidget]] = []
        self._categories = require_child(self.dialog, QTreeWidget, "treeCategories")
        self._stack = require_child(self.dialog, QStackedWidget, "stackSettings")
        self._category_title = require_child(self.dialog, QLabel, "labelCategoryTitle")
        self._category_items: dict[str, QTreeWidgetItem] = {}

        self._mount_pages()
        self.mcp_page = McpSettingsPage(mcp_server, self._stack)
        self._stack.addWidget(self.mcp_page)
        self._add_category("mcp", tr("SettingsDialog", "MCP"), self.mcp_page, self._category_items["application"])
        self.dialog.finished.connect(lambda result: self.mcp_page.tester.close())
        self.tone_page = TonePageController(
            require_child(self.dialog, QWidget, "SettingsTonePage"), self.icon_manager, tone_id,
        )
        self.watch_page = WatchPageController(self.dialog, self.plugins.parsers, self.icon_manager)
        self.glossary_page = GlossaryPageController(
            require_child(self.dialog, QWidget, "SettingsGlossaryPage"), entrance,
            glossary_languages or {}, glossary_adapter_id, glossary_game_id,
            glossary_id, glossary_source_language, glossary_target_language,
        )
        settings_splitter = require_child(self.dialog, QSplitter, "splitterSettings")
        settings_splitter.setSizes([230, 690])
        settings_splitter.setStretchFactor(0, 0)
        settings_splitter.setStretchFactor(1, 1)
        self._mount_plugin_settings_pages()
        self._connect_category_stack()

        self.button_box = require_child(self.dialog, QDialogButtonBox, "buttonBox")
        self.button_box.accepted.disconnect()
        save_button = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        apply_button = self.button_box.button(QDialogButtonBox.StandardButton.Apply)
        if save_button is None or apply_button is None:
            raise RuntimeError("保存・適用ボタンがありません。")
        self.save_button = save_button
        self.apply_button = apply_button
        self.ai_page = AiSettingsPageController(
            self.dialog, self.plugins.providers, self.icon_manager, provider_id,
            models or {}, selected_models or {}, api_keys or {}, concurrency,
            high_model, low_model, low_model_range,
            setup_options=self.plugins.ai_setup_options,
        )
        self.dialog.finished.connect(lambda _result: self.ai_page.cancel())
        self.ai_page.save_ready.connect(self._finish_validation)
        self.ai_page.save_aborted.connect(self._save_aborted)
        self.ai_page.show_requested.connect(lambda: self.select_category("ai"))
        self.button_box.accepted.connect(self._validate_for_save)
        self.apply_button.clicked.connect(lambda: self._validate_for_save(False))
        self.dialog.rejected.connect(self._cancel_save)
        self.general_page = GeneralSettingsPageController(self.dialog, entrance)
        self.general_page.self_translation.running_changed.connect(self._self_translation_running)
        self.dialog.rejected.connect(self.general_page.self_translation.cancel)
        self.filter_rules_page = FilterRulesPageController(
            self.dialog, self.plugins.parsers, glossary_adapter_id, glossary_game_id,
        )
        self._setup_dialog_buttons()

    def _mount_pages(self) -> None:
        pages = [
            ("application", "アプリ", "pageGeneral", "GeneralPage.ui", ""),
            ("appearance", "外観", "pageDisplay", "DisplayPage.ui", "application"),
            ("input", "入力", "pageInput", "InputPage.ui", "application"),
            ("translation", "翻訳", "pageTranslation", "TranslationPage.ui", ""),
            ("ai", "AI", "pageAI", "AiPage.ui", "translation"),
            ("tone", "口調", "pageTone", "TonePage.ui", "translation"),
            ("glossary", "用語集", "pageGlossary", "GlossaryPage.ui", "translation"),
            ("filter_rules", "除外ルール", "pageFilterRules", "FilterRulesPage.ui", "translation"),
            ("file", "ファイル", "pageFile", "FilePage.ui", ""),
            ("source_watch", "翻訳元フォルダ監視", "pageSourceWatch", "SourceWatchPage.ui", "file"),
        ]
        for target, title, page_name, ui_name, parent_id in pages:
            container = require_child(self.dialog, QWidget, page_name)
            layout = container.layout()
            if layout is None:
                raise RuntimeError(f"設定ページのレイアウトがありません: {page_name}")
            sub_widget = load_ui(f"dialogs/settings/{ui_name}", container)
            layout.addWidget(sub_widget)
            parent = self._category_items[parent_id] if parent_id else None
            self._add_category(target, tr("SettingsDialog", title), container, parent)

        self._add_category(
            "plugins", tr("SettingsDialog", "プラグイン"),
            require_child(self.dialog, QWidget, "pagePlugins"),
        )

    def _add_category(
        self, target: str, title: str, page: QWidget,
        parent: QTreeWidgetItem | None = None,
    ) -> None:
        if target in self._category_items:
            raise ValueError(f"設定ページIDが重複しています: {target}")
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.ItemDataRole.UserRole, page)
        if parent is None:
            self._categories.addTopLevelItem(item)
        else:
            parent.addChild(item)
        self._category_items[target] = item

    def _mount_plugin_settings_pages(self) -> None:
        for provider in self.plugins.all_settings_pages:
            widget = provider.create_widget(self._stack)
            self._stack.addWidget(widget)
            self._add_category(provider.id, provider.title, widget, self._category_items["plugins"])
            self._plugin_settings_widgets.append((provider, widget))

    def select_category(self, target: str) -> bool:
        """公開された設定ページIDに一致するカテゴリを選択。"""
        item = self._category_items.get(target)
        if item is None:
            return False
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self._categories.setCurrentItem(item)
        self._categories.scrollToItem(item)
        return True

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
            self.apply_button.setText(tr("SettingsDialog", "適用"))

    def _connect_category_stack(self) -> None:
        self._categories.currentItemChanged.connect(self._on_category_changed)
        self._categories.expandAll()
        self.select_category("application")

    def _on_category_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        page = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(page, QWidget):
            raise TypeError("設定カテゴリにページが登録されていません")
        self._stack.setCurrentWidget(page)
        self._category_title.setText(current.text(0))

    def _set_saving(self, saving: bool) -> None:
        self._saving = saving
        self.save_button.setEnabled(not saving)
        self.apply_button.setEnabled(not saving)
        self._stack.setEnabled(not saving)
        self._categories.setEnabled(not saving)
        self.save_button.setText(tr("SettingsDialog", "保存"))
        self.apply_button.setText(tr("SettingsDialog", "適用"))
        if saving:
            button = self.save_button if self._close_after_save else self.apply_button
            button.setText(tr("SettingsDialog", "保存中..."))

    def _self_translation_running(self, running: bool) -> None:
        self.save_button.setEnabled(not running and not self._saving)
        self.apply_button.setEnabled(not running and not self._saving)
        self._categories.setEnabled(not running and not self._saving)

    def _save_aborted(self) -> None:
        self._set_saving(False)

    def _cancel_save(self) -> None:
        self._save_aborted()
        self.ai_page.cancel()

    def _save_error(self, error: Exception) -> None:
        logging.getLogger(__name__).exception("Settings save failed")
        self._save_aborted()
        self.ai_page.cancel()
        self.select_category(self._saving_category)
        QMessageBox.warning(self.dialog, tr("SettingsDialog", "保存エラー"), str(error))

    def _validate_for_save(self, close_after_save: bool = True) -> None:
        if self._saving or self.general_page.self_translation.busy:
            return
        self._close_after_save = close_after_save
        self._save_category = self._categories.currentItem()
        self._set_saving(True)
        try:
            self._saving_category = "tone"
            if not self.tone_page.validate():
                self.select_category("tone")
                self._save_aborted()
                return
            self._saving_category = "filter_rules"
            if not self.filter_rules_page.validate():
                self.select_category("filter_rules")
                self._save_aborted()
                return
            self._saving_category = "ai"
            self.ai_page.validate_for_save()
        except Exception as error:
            self._save_error(error)

    def _finish_validation(self) -> None:
        if not self._saving:
            return
        try:
            self._saving_category = "source_watch"
            self.watch_page.save(self._save_pages, self._watch_save_failed)
        except Exception as error:
            self._save_error(error)

    def _watch_save_failed(self) -> None:
        self.select_category("source_watch")
        self._save_aborted()

    def _save_pages(self) -> None:
        if not self._saving:
            return
        try:
            self._saving_category = "tone"
            if not self.tone_page.save():
                self.select_category("tone")
                self._save_aborted()
                return
            self._saving_category = "ai"
            self.ai_page.save()
            self._saving_category = "application"
            self.general_page.save()
            self._saving_category = "mcp"
            self.mcp_page.save()
            self._saving_category = "filter_rules"
            self.filter_rules_page.save()
            for provider, widget in self._plugin_settings_widgets:
                self._saving_category = provider.id
                provider.save_settings(widget)
            self._saving_category = "application"
            if self._on_saved is not None:
                self._on_saved(self)
            self.filter_rules_page.changed_keys.clear()
        except Exception as error:
            self._save_error(error)
            return
        self._save_aborted()
        if self._close_after_save:
            self.dialog.accept()
        elif self._save_category is not None:
            self._categories.setCurrentItem(self._save_category)
