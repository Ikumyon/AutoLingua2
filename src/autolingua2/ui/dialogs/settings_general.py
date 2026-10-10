from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QDialog, QListWidget, QListWidgetItem

from autolingua2.extensions import ExtensionEntrance
from autolingua2.services.settings_store import (
    DEFAULT_UI_LANGUAGE, load_theme_settings, load_ui_language, load_voice_input_provider,
    save_theme_settings, save_ui_language, save_voice_input_provider,
)
from autolingua2.services.voice_input import voice_input_available
from autolingua2.ui.i18n import normalize_language, system_language, tr
from .base import require_child


class GeneralSettingsPageController(QObject):
    """アプリの言語、入力、外観設定を管理する。"""

    def __init__(self, dialog: QDialog, entrance: ExtensionEntrance) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.localization = entrance.localization
        self.plugins = entrance.plugins
        self.theme_manager = entrance.themes
        self.icon_manager = entrance.icons
        self._setup_ui_language()
        self._setup_voice_input()
        self._setup_themes_and_icons()

    def save(self) -> None:
        old_language = load_ui_language()
        new_language = str(self.combo_ui_language.currentData() or "")
        voice_provider = self.combo_voice_input.currentData()
        if not isinstance(voice_provider, str):
            raise TypeError("Voice input provider ID must be a string")
        save_ui_language(new_language)
        save_voice_input_provider(voice_provider)

        theme_item = self.list_themes.currentItem()
        theme_id = str(theme_item.data(Qt.ItemDataRole.UserRole)) if theme_item else "system"
        icon_item = self.list_icon_themes.currentItem()
        icon_id = str(icon_item.data(Qt.ItemDataRole.UserRole)) if icon_item else "default"
        save_theme_settings(theme_id, icon_id)
        self.theme_manager.apply_theme(theme_id)
        self.icon_manager.set_current_iconset(icon_id)

        if new_language != old_language:
            app = QCoreApplication.instance()
            if app is None:
                raise RuntimeError("QCoreApplication インスタンスが存在しません")
            self.localization.apply_language(app, new_language)

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
