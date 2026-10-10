from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPushButton, QSplitter,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QWidget,
)

from autolingua2.extensions import ExtensionEntrance
from autolingua2.plugins.api import SettingsPageProvider
from autolingua2.services.settings_store import AiModel
from autolingua2.ui.i18n import tr
from .base import SimpleDialogController, load_ui, require_child
from .glossary import GlossaryPageController
from .settings_ai import AiSettingsPageController
from .settings_filter_rules import FilterRulesPageController
from .settings_general import GeneralSettingsPageController
from .source_watch import WatchPageController


class SettingsDialogController(SimpleDialogController):
    """設定カテゴリの配置と、各ページの保存を取りまとめる。"""

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
        self.icon_manager = entrance.icons
        self._plugin_settings_widgets: list[tuple[SettingsPageProvider, QWidget]] = []
        self._categories = require_child(self.dialog, QTreeWidget, "treeCategories")
        self._stack = require_child(self.dialog, QStackedWidget, "stackSettings")
        self._category_title = require_child(self.dialog, QLabel, "labelCategoryTitle")
        self._category_items: dict[str, QTreeWidgetItem] = {}

        self._mount_pages()
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
        self.ai_page = AiSettingsPageController(
            self.dialog, self.plugins.providers, self.icon_manager, provider_id,
            models or {}, selected_models or {}, api_keys or {}, concurrency,
        )
        self.ai_page.save_ready.connect(self._finish_validation)
        self.ai_page.show_requested.connect(lambda: self.select_category("ai"))
        self.button_box.accepted.connect(self._validate_for_save)
        self.button_box.rejected.connect(self.ai_page.cancel)
        self.general_page = GeneralSettingsPageController(self.dialog, entrance)
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

    def _validate_for_save(self) -> None:
        if self.filter_rules_page.validate():
            self.ai_page.validate_for_save()
        else:
            self.select_category("filter_rules")

    def _finish_validation(self) -> None:
        if self.filter_rules_page.validate():
            self.watch_page.save(self.dialog.accept)
        else:
            self.select_category("filter_rules")

    def exec(self) -> int:
        result = super().exec()
        if result != QDialog.DialogCode.Accepted:
            return result

        self.ai_page.save()
        self.general_page.save()
        self.filter_rules_page.save()
        for provider, widget in self._plugin_settings_widgets:
            provider.save_settings(widget)
        return result
