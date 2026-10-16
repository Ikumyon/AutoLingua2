from __future__ import annotations

from autolingua2 import __version__
from autolingua2.ui.resources.i18n import translation_source

import json
import os
import re
from copy import deepcopy
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QModelIndex, QObject, QPoint, QPropertyAnimation, QSize, Qt, QSignalBlocker, QTimer, QLocale, QItemSelection, QItemSelectionModel
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QContextMenuEvent, QIcon, QMouseEvent, QPixmap, QSyntaxHighlighter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autolingua2.ui.main.page_scrubber import RangeScrubberWidget

from autolingua2.adapters.base import EmbeddedTranslationAdapter, FileAdapter, SupportedLanguagesAdapter
from autolingua2.services.projects.project_io import detect_inherited_language, read_project_thumbnail
from autolingua2.services.settings.language_tags import qt_language_options
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ui.creation.creation_contract import CreationActions, CreationAdapter
from autolingua2.ui.creation.creation_panel import CommonCreationAdapter
from autolingua2.ui.components.searchable_combo_box import enable_combo_search
from autolingua2.ui.components.search_bar import SearchBar
from autolingua2.extensions import ExtensionEntrance
from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.infrastructure.platform import current_platform, log_directory
from autolingua2.infrastructure.platform.base import PlatformDriver
from autolingua2.infrastructure.operations import OperationCancelled
from autolingua2.ir import Issue, TranslationProject, UnitState
from autolingua2.ir.workspace import UnitView as TranslationUnit, Workspace, WorkspaceUnit, is_pending_translation
from autolingua2.ir.text_search import SearchSyntaxError, TextSearch
from autolingua2.services.projects.workspaces import WorkspaceService
from autolingua2.services.settings.glossary_store import GlossaryStore
from autolingua2.services.settings.tone_store import ToneStore
from autolingua2.ir.tone import DEFAULT_TONE_ID, ConditionalTone, Tone, ToneItem
from autolingua2.ir.glossary import Glossary, glossary_chain
from autolingua2.ui.dialogs.glossary import STORAGE_ERRORS
from autolingua2.ui.dialogs.workspace_language import WorkspaceLanguageDialog
from autolingua2.ui.dialogs.automation import AutomationDialogController
from autolingua2.services.ai.ai_network import AiNetworkClient
from autolingua2.services.ai.ai_chat import ChatFile, ChatReference
from autolingua2.services.operations.application_operations import ApplicationOperations
from autolingua2.services.integration.mcp_server import McpServer
from autolingua2.services.integration.mcp_client import McpClient
from autolingua2.services.settings.settings_store import load_mcp_settings
from autolingua2.ir.validation import array as json_array, text as json_text
from autolingua2.ui.chat.ai_chat_dock import AiChatDockController
from autolingua2.ui.components.chat_composer import ChatReferenceTable
from autolingua2.ui.components.drop_zone import DropZone
from autolingua2.services.settings.filter_rules import get_filter_config
from autolingua2.services.translation.source_classification import classify_sources
from autolingua2.ir.classification import ClassificationResult
from autolingua2.ir.key_conflict import KeyConflict
from autolingua2.ir.translation import ModelSelection
from autolingua2.ui.dialogs.key_conflict import KeyConflictDialog
from autolingua2.ui.components.translation_table_delegate import (
    ActionButtonDelegate,
    MultiLineTextDelegate,
    StatusComboBoxDelegate,
)
from autolingua2.ui.components.dock_tab_style import DockTabStyle
from autolingua2.services.exporting.export import export_translation
from autolingua2.ui.export.export_dialog import ExportDialog
from autolingua2.services.projects.project_archive import ProjectArchive, load_project, project_snapshot, save_project
from autolingua2.services.projects.recent_projects import load_recent_projects, remember_project
from autolingua2.services.translation.source_updates import (
    AppliedUpdate, SourceUpdate, apply_update, ensure_watcher, pending_target, prepare_update,
    notification_target, notifications_available, set_project_notification, import_notification_target,
)
from autolingua2.services.settings.settings_store import load_watch_settings
from autolingua2.ui.dialogs.source_watch import SourceUpdateDialog
from autolingua2.services.settings.settings_store import (
    AiSettings,
    DockTabPosition,
    WindowLayout,
    load_ai_settings,
    save_ai_settings,
    load_theme_settings,
    load_ui_display_flags,
    load_window_layout,
    save_ui_display_flags,
    save_window_layout,
)
from autolingua2.ui.dialogs import (
    SettingsDialogController,
    SimpleDialogController,
    load_ui,
    require_child,
    show_not_implemented,
)
from autolingua2.ui.dialogs.multi_model_dialog import MultiModelTranslationDialog
from autolingua2.ui.resources.i18n import current_ui_language, language_events, tr
from autolingua2.ui.main.language_names import workspace_language_name
from autolingua2.ui.creation.import_worker import ImportWorker
from autolingua2.services.operations.operation_worker import OperationWorker
from autolingua2.plugins.api import GameTextPresentation
from autolingua2.ui.main.main_window_focus import FocusEditorController
from autolingua2.ui.main.main_window_table import TranslationTableController
from autolingua2.ui.main.main_window_translation import MainWindowTranslationController
from autolingua2.ui.main.main_window_overview import OverviewController

STATUS_MATCHERS: dict[str, Callable[[TranslationUnit], bool]] = {
    "pending": is_pending_translation,
    "hidden": lambda unit: unit.state == UnitState.HIDDEN,
    "locked": lambda unit: unit.state == UnitState.LOCKED,
    "has_issues": lambda unit: bool(unit.issues),
    "source_changed": lambda unit: unit.source_changed,
    "doubtful": lambda unit: unit.state == UnitState.DOUBTFUL,
    "translation_error": lambda unit: unit.state == UnitState.TRANSLATION_ERROR,
    "review_error": lambda unit: unit.state == UnitState.REVIEW_ERROR,
    "review_issues": lambda unit: unit.state == UnitState.REVIEW_ISSUES,
    "ai_reviewed": lambda unit: unit.state == UnitState.AI_REVIEWED,
    "human_reviewed": lambda unit: unit.state == UnitState.HUMAN_REVIEWED,
    "ai_translated": lambda unit: unit.state == UnitState.AI_TRANSLATED,
    "human_translated": lambda unit: unit.state == UnitState.HUMAN_TRANSLATED,
    "untranslated": lambda unit: unit.state == UnitState.UNTRANSLATED,
}

class MainWindowCreationContext:
    """プラグインに提供する本体プロジェクト作成画面の操作コンテキスト。"""

    def __init__(self, controller: MainWindowController, adapter_id: str) -> None:
        self.controller = controller
        self.adapter_id = adapter_id
        self.active: bool = True

    def _check(self) -> None:
        if not self.active:
            raise RuntimeError("This creation panel is no longer active")
        if self.controller._changing_game and self.controller.creation_context is not self:
            raise RuntimeError("Panel constructors must not modify the creation form")
        if self.controller.import_worker is not None:
            raise RuntimeError("Project import is in progress")

    def add_target_path(self, path: Path) -> None:
        self._check()
        self.controller.add_target_path(path)

    def remove_target_path(self, path: Path) -> None:
        self._check()
        self.controller.remove_target_path_by_path(path)

    def set_project_name(self, name: str) -> None:
        self._check()
        self.controller.edit_project_name.setText(name)

    def set_project_icon(self, path: Path) -> None:
        self._check()
        self.controller.set_project_icon(path, manual=False)

    def select_game(self, game_id: str) -> None:
        self._check()
        if self.controller._changing_game:
            raise RuntimeError("Cannot select a game during a selection hook")
        self.controller.select_game_by_id(game_id, self.adapter_id)

    def set_source_language(self, lang_code: str) -> None:
        self._check()
        idx = self.controller.combo_source_language.findData(lang_code)
        if idx < 0:
            raise ValueError(f"Unknown source language: {lang_code}")
        self.controller.combo_source_language.setCurrentIndex(idx)

    def set_target_slot(self, slot_code: str) -> None:
        self._check()
        idx = self.controller.combo_target_slot.findData(slot_code)
        if idx < 0:
            raise ValueError(f"Unknown output slot: {slot_code}")
        self.controller.combo_target_slot.setCurrentIndex(idx)

    def cancel_operation(self) -> None:
        if not self.active:
            return
        if self.controller.import_worker:
            self.controller.import_worker.requestInterruption()
        if self.controller.io_worker:
            self.controller.io_worker.requestInterruption()

    def actions(self) -> CreationActions:
        return CreationActions(
            cancel_operation=self.cancel_operation, add_target_path=self.add_target_path,
            remove_target_path=self.remove_target_path, set_project_name=self.set_project_name,
            set_project_icon=self.set_project_icon,
            select_game=self.select_game, set_source_language=self.set_source_language,
            set_target_slot=self.set_target_slot,
        )

class MainWindowController(QObject):
    def __init__(self, entrance: ExtensionEntrance, platform_driver: PlatformDriver = current_platform) -> None:
        super().__init__()
        self.platform = platform_driver
        self.entrance = entrance
        self._initial_setup_dialog: QDialog | None = None
        self._settings_dialog: SettingsDialogController | None = None
        self.plugins = entrance.plugins
        self._known_plugin_errors = len(self.plugins.errors)
        self.io_worker: OperationWorker | None = None
        self._pending_rules_refresh = False
        self._close_after_io = False
        self._restart_target: bool | None = None
        self._restart_started = False
        self.project_path: Path | None = None
        self._saved_project: bytes | None = None
        widget = load_ui("MainWindow.ui")
        if not isinstance(widget, QMainWindow):
            raise TypeError("MainWindow.ui は QMainWindow ではありません")

        self.window = widget
        self.icon_manager = entrance.icons
        _, icon_theme = load_theme_settings()
        self.icon_manager.set_current_iconset(icon_theme)
        self.imported = ImportedTranslation(project=TranslationProject())
        self.output_path: Path | None = None
        self.provider_registry = self.plugins.providers
        self.ai_settings = load_ai_settings(self.provider_registry)
        self.project = self.imported.project
        self.workspace_service = WorkspaceService(self.imported)
        self.active_workspace: Workspace | None = None
        self.glossary_store = GlossaryStore()
        self.selected_glossary_id = ""
        self.glossary_choices: list[Glossary] = []
        self.tone_store = ToneStore()
        self.selected_tone_id = DEFAULT_TONE_ID
        self.tone_choices: list[Tone] = []
        self.units: list[TranslationUnit] = []
        self.filtered_units: list[TranslationUnit] = []
        self.table_controller = TranslationTableController(self)
        self.focus_controller = FocusEditorController(self)
        self.status_count_label: QLabel | None = None

        self.selected_icon_path: Path | None = None
        self._selected_thumbnail = ""
        self._project_icon_pixmap: QPixmap | None = None
        self._project_icon_is_manual = False
        self.target_paths: list[Path] = []
        self.target_item_widgets: dict[Path, tuple[QLabel, QListWidgetItem]] = {}
        self.inherited_paths: list[Path] = []
        self._embedded_sources = False
        self._inherit_language_manual = False
        self.inherited_item_widgets: dict[Path, tuple[QLabel, QListWidgetItem]] = {}
        self.target_files: list[Path] = []
        self.active_adapter: FileAdapter | None = None
        self.creation_adapters: dict[str, CreationAdapter] = {
            plugin_id: self.plugins.ui_extensions.get(plugin_id, CommonCreationAdapter())
            for plugin_id in self.plugins.parsers
        }
        self.active_creation_adapter: CreationAdapter | None = None
        self.active_creation_panel: QWidget | None = None
        self.creation_context: MainWindowCreationContext | None = None
        self.import_worker: ImportWorker | None = None
        self._changing_game = False
        self._creation_valid = False
        self._panel_valid = False
        self._close_after_import = False
        self._ai_dock_workspace_visible: bool = True
        render_newlines, highlight_tags, apply_colors = load_ui_display_flags()
        self.render_literal_newlines: bool = render_newlines
        self.highlight_translation_tags: bool = highlight_tags
        self.apply_color_tags: bool = apply_colors
        self._text_presentation: GameTextPresentation | None = None
        self.source_highlighter: QSyntaxHighlighter | None = None
        self.translation_highlighter: QSyntaxHighlighter | None = None
        self.ai_client = AiNetworkClient(self.window)
        self.translation_controller = MainWindowTranslationController(self)
        self._dock_tab_position: DockTabPosition = "bottom"
        self._dock_tab_vertical_text = True
        self._dock_tab_styles: dict[QTabBar, DockTabStyle] = {}
        self._dock_tab_refresh_timer = QTimer(self)
        self._dock_tab_refresh_timer.setSingleShot(True)
        self._dock_tab_refresh_timer.timeout.connect(self._refresh_dock_tab_bars)

        self._setup_widgets()
        self.overview_controller = OverviewController(self)
        self.operations = ApplicationOperations(
            lambda: self.workspace_service, lambda: self.project_path, lambda: self._saved_project,
            self._chat_settings, self.plugins.parsers, self.plugins.providers.providers, self.plugins.exporters,
            self.ai_client, self,
            plugin_inventory=self.entrance.plugin_inventory,
            ui_languages=lambda: tuple(self.entrance.localization.available_languages.values()),
            resolve_ui_language=self.entrance.localization.resolve_language,
            apply_ui_language=self._operation_apply_ui_language,
        )
        for plugin_id, contributions in self.plugins.operations.items():
            for contribution in contributions:
                self.operations.register_plugin(plugin_id, contribution)
        self.mcp_server = McpServer(self.operations, self)
        self.mcp_client = McpClient(self)
        self.operations.external_request = self.mcp_client.request
        self.operations.external_cancel = self.mcp_client.cancel_job
        self.operations.external_inventory = self.mcp_client.inventory
        self.operations.selection_requested.connect(self._operation_select)
        self.operations.project_replaced.connect(self._operation_project_replaced)
        self.operations.project_saved.connect(self._operation_project_saved)
        self.operations.preferences_changed.connect(self._operation_preferences)
        self.operations.translation_language_changed.connect(self._operation_translation_language_changed)
        self.operations.changed.connect(self._operation_refresh)
        self._close_after_operations = False
        self.operations.workers_idle.connect(self._operations_idle)
        self._configure_mcp()
        self.chat_dock = AiChatDockController(
            self.window, self.provider_registry, self._chat_settings,
            self._chat_current_file, self._chat_selected_references,
            self._chat_selection_origin,
            voice_input_providers=self.plugins.voice_inputs,
            operations=self.operations,
            get_icon=self.icon_manager.get_icon, chat_icon=self._chat_icon,
        )
        self.chat_dock.send_button.setIcon(self.icon_manager.get_icon("send-24"))
        require_child(self.window, ChatReferenceTable, "tableTranslations").reference_supplier = self.chat_dock.selected_attachment
        self.chat_dock.voice_button.setIcon(self.icon_manager.get_icon("microphone"))
        self.window.tabifyDockWidget(self.dock_ai_settings, self.chat_dock.dock)
        self.plugins.on_display_changed(self._on_plugin_display_changed)
        self._configure_text_presentation()
        self._connect_actions()
        from autolingua2.ui.shortcuts import ShortcutManager
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("QApplication is not running")
        self.shortcuts = ShortcutManager(app)
        save_menu = self.button_save_split.menu()
        if save_menu is None:
            raise RuntimeError("保存メニューがありません")
        self.shortcuts.register_main_window(self.window, self.page_focus, save_menu)
        self.shortcuts.edit_requested.connect(self._open_shortcut_settings)
        self.shortcuts.load()
        if self.shortcuts.errors:
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self.window, tr("MainWindow", "ショートカット設定"), "\n".join(self.shortcuts.errors)))
        self._set_initial_state()
        self.window.installEventFilter(self)
        language_events().changed.connect(self._on_ui_language_changed)
        if entrance.errors:
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self.window, "拡張読み込みエラー", "\n".join(entrance.errors)))
        self._requested_source_updates: list[str] = []
        self._refresh_project_notification()
        self.source_watch_timer = QTimer(self)
        self.source_watch_timer.setInterval(30000)
        self.source_watch_timer.timeout.connect(self._poll_source_updates)
        self.source_watch_timer.start()
        if load_watch_settings().enabled:
            QTimer.singleShot(0, lambda: self._run_operation(ensure_watcher, lambda _result: None))
        if update_info_json := os.environ.pop("AUTOLINGUA_UPDATE_INFO", None):
            try:
                update_info = json.loads(update_info_json)
                if isinstance(update_info, dict) and update_info.get("has_update"):
                    QTimer.singleShot(0, lambda info=update_info: self._open_update_dialog(initial_data=info))
            except Exception:
                pass

    def show(self) -> None:
        self.window.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.window and event.type() in (
            QEvent.Type.ChildAdded, QEvent.Type.LayoutRequest, QEvent.Type.Show,
        ):
            self._dock_tab_refresh_timer.start(0)
        if isinstance(watched, QTabBar) and watched in self._dock_tab_styles:
            if isinstance(event, QContextMenuEvent) and watched.tabAt(event.pos()) >= 0:
                self._show_dock_tab_menu(event.globalPos())
                event.accept()
                return True
        if watched is self.window and isinstance(event, QCloseEvent):
            if self.operations.has_workers:
                event.ignore()
                self._close_after_operations = True
                self.operations.cancel_active_jobs()
                return True
            if self.io_worker is not None:
                event.ignore()
                self._close_after_io = True
                self.io_worker.requestInterruption()
                return True
            if self.import_worker is not None:
                event.ignore()
                self._close_after_import = True
                self.import_worker.requestInterruption()
                return True
            if not self._confirm_project_change():
                self._restart_target = None
                event.ignore()
                return True
            if self._restart_target is not None:
                try:
                    self._save_window_layout()
                    self.platform.restart_process(self._restart_target)
                except Exception as exc:
                    self._restart_target = None
                    event.ignore()
                    QMessageBox.warning(self.window, "再起動エラー", str(exc))
                    return True
                self._restart_started = True
                self._restart_target = None
            else:
                self._save_window_layout()
            self.plugins.remove_display_listener(self._on_plugin_display_changed)
            self.automation_dialog.shutdown()
            self.chat_dock.close()
            self.mcp_server.close()
            self.mcp_client.close()
            self.operations.close()
            self._dispose_highlighters()
            if self.creation_context:
                self.creation_context.active = False
                self.plugins.bind_creation(self.creation_context.adapter_id, None)
            if self.active_creation_adapter is not None and self.active_creation_panel is not None:
                try:
                    self.active_creation_adapter.dispose_creation_panel(self.active_creation_panel)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Panel disposal failed")

        table = getattr(self, "table", None)
        if table is not None and watched is table.viewport():
            if isinstance(event, QMouseEvent) and event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.NoModifier:
                    index = table.indexAt(event.pos())
                    if index.isValid():
                        row = index.row()
                        selection_model = table.selectionModel()
                        if selection_model is not None and selection_model.isRowSelected(row, QModelIndex()):
                            visible_cols = self.table_controller.visible_columns()
                            col_id = visible_cols[index.column()].id if 0 <= index.column() < len(visible_cols) else ""
                            if col_id not in {"status", "action"}:
                                table.clearSelection()
                                table.setCurrentItem(None)
                                return True
                    else:
                        table.clearSelection()
                        table.setCurrentItem(None)
                        return True

        if watched is getattr(self, "frame_segment_mode", None):
            if event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
                self._sync_segment_indicator_pos(animate=False)
        if watched is getattr(self, "frame_icon_drop", None):
            if event.type() in {QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.Resize, QEvent.Type.Show}:
                if event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
                    side = self.frame_icon_drop.width()
                    if self.frame_icon_drop.height() != side:
                        self.frame_icon_drop.setFixedHeight(side)
                self._sync_project_icon_actions()
        if watched is getattr(self, "label_icon_preview", None):
            if event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
                self._resize_project_icon_preview()
        return False

    def _drop_inherited_paths(self, paths: list[Path]) -> None:
        for path in paths:
            self.add_inherited_path(path)

    def _drop_target_paths(self, paths: list[Path]) -> None:
        adapter = self.active_creation_adapter
        context = self.creation_context
        if (self.import_worker is not None or not self._creation_valid
                or adapter is None or context is None):
            return
        try:
            source_paths = self._set_dropped_project_icon(paths)
            remaining = adapter.on_paths_dropped(source_paths, self.plugins.context(context.adapter_id))
            if not isinstance(remaining, list) or any(path not in source_paths for path in remaining):
                raise ValueError("Invalid unhandled drop paths")
            for path in remaining:
                self.add_target_path(path)
        except Exception as exc:
            QMessageBox.warning(self.window, "プラグインエラー", str(exc))

    def _refresh_drop_actions(self) -> None:
        self.button_browse_icon.setText(tr("MainWindow", "選択..."))
        self.button_browse_icon.setToolTip(tr("MainWindow", "アイコン画像ファイルを選択"))
        self.button_edit_icon.setIcon(self.icon_manager.get_icon("pencil"))
        self.button_edit_icon.setToolTip(tr("MainWindow", "アイコン画像ファイルを選択"))
        self.button_clear_icon.setText("✕")
        self.button_clear_icon.setToolTip(tr("MainWindow", "アイコンを解除"))
        self.button_inherit_folder.setText(tr("MainWindow", "フォルダ追加"))
        self.button_inherit_folder.setIcon(self.icon_manager.get_icon("folder"))
        self.button_inherit_file.setText(tr("MainWindow", "ファイル追加"))
        self.button_inherit_file.setIcon(self.icon_manager.get_icon("file"))

    def _setup_widgets(self) -> None:
        self.table = require_child(self.window, QTableWidget, "tableTranslations")
        self.list_focus_units = require_child(self.window, QListWidget, "listFocusUnits")
        self.list_focus_units.setIconSize(QSize(16, 16))
        self.search_bar = require_child(self.window, SearchBar, "searchBar")
        self.search_bar.set_icons(self.icon_manager.get_icon)
        self.search = self.search_bar.editor
        self.search_case = self.search_bar.case_button
        self.search_word = self.search_bar.word_button
        self.search_regex = self.search_bar.regex_button
        self.search_bar.bind_replace_panel(require_child(self.window, QWidget, "replacePanel"))
        self.replace_text = require_child(self.window, QLineEdit, "editReplace")
        self.button_replace = require_child(self.window, QPushButton, "buttonReplace")
        self.button_replace_all = require_child(self.window, QPushButton, "buttonReplaceAll")
        self.button_replace.setIcon(self.icon_manager.get_icon("replace"))
        self.button_replace_all.setIcon(self.icon_manager.get_icon("replace-all"))
        self.label_search_result = require_child(self.window, QLabel, "labelSearchResult")
        self._text_search = TextSearch("")
        self._search_error = ""
        self.status_filter = require_child(self.window, QComboBox, "comboStatusFilter")
        self.stack = require_child(self.window, QStackedWidget, "stackTranslationView")
        self.page_dashboard = require_child(self.window, QWidget, "pageDashboard")
        self.page_list = require_child(self.window, QWidget, "pageList")
        self.page_focus = require_child(self.window, QWidget, "pageFocus")
        self.page_workspace = require_child(self.window, QWidget, "pageWorkspace")
        self.stack_workspace_controls = require_child(self.window, QStackedWidget, "stackWorkspaceControls")
        self.page_controls_dashboard = require_child(self.window, QWidget, "pageControlsDashboard")
        self.page_controls_translation = require_child(self.window, QWidget, "pageControlsTranslation")
        self.frame_segment_mode = require_child(self.window, QFrame, "frameSegmentMode")
        self.button_dashboard_mode = require_child(self.window, QToolButton, "buttonDashboardMode")
        self.button_list_mode = require_child(self.window, QToolButton, "buttonListMode")
        self.button_focus_mode = require_child(self.window, QToolButton, "buttonFocusMode")
        self.mode_group = QButtonGroup(self.window)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.button_dashboard_mode)
        self.mode_group.addButton(self.button_list_mode)
        self.mode_group.addButton(self.button_focus_mode)

        self.segment_indicator = QFrame(self.frame_segment_mode)
        self.segment_indicator.setObjectName("segmentIndicator")
        self.segment_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.segment_indicator.setStyleSheet(
            "background-color: palette(highlight); border-radius: 4px;"
        )
        self.segment_indicator.lower()
        self.segment_indicator.hide()

        self.segment_anim = QPropertyAnimation(self.segment_indicator, b"geometry")
        self.segment_anim.setDuration(220)
        self.segment_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self.frame_segment_mode.installEventFilter(self)

        self.button_display_settings = require_child(self.window, QToolButton, "buttonDisplaySettings")
        self.button_display_settings.setIcon(self.icon_manager.get_icon("settings-2"))

        self.display_settings_menu = QMenu(self.window)
        self.action_render_newlines = QAction(tr("MainWindow", "改行記号を改行して表示"), self.display_settings_menu)
        self.action_render_newlines.setCheckable(True)
        self.action_render_newlines.setChecked(self.render_literal_newlines)
        self.action_render_newlines.toggled.connect(self._on_toggle_render_newlines)
        self.display_settings_menu.addAction(self.action_render_newlines)

        self.action_highlight_tags = QAction(tr("MainWindow", "翻訳タグを色分けする"), self.display_settings_menu)
        self.action_highlight_tags.setCheckable(True)
        self.action_highlight_tags.setChecked(self.highlight_translation_tags)
        self.action_highlight_tags.toggled.connect(self._on_toggle_highlight_tags)
        self.display_settings_menu.addAction(self.action_highlight_tags)

        self.action_apply_color_tags = QAction(tr("MainWindow", "色タグで実際に色を付ける"), self.display_settings_menu)
        self.action_apply_color_tags.setCheckable(True)
        self.action_apply_color_tags.setChecked(self.apply_color_tags)
        self.action_apply_color_tags.toggled.connect(self._on_toggle_apply_color_tags)
        self.display_settings_menu.addAction(self.action_apply_color_tags)

        self.display_settings_separator = self.display_settings_menu.addSeparator()
        self.action_open_color_settings = QAction(self.display_settings_menu)
        self.action_open_color_settings.triggered.connect(self._open_game_color_settings)
        self.display_settings_menu.addAction(self.action_open_color_settings)

        self.button_display_settings.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.button_display_settings.clicked.connect(self._open_display_settings_menu)

        self.progress = require_child(self.window, QProgressBar, "progressTranslation")
        self.frame_files = require_child(self.window, QFrame, "frameFiles")
        self.splitter_main = require_child(self.window, QSplitter, "splitterMain")
        self.splitter_focus = require_child(self.window, QSplitter, "splitterFocusTexts")
        self.button_previous = require_child(self.window, QPushButton, "buttonPrevious")
        self.button_next = require_child(self.window, QPushButton, "buttonNext")
        self.button_revert = require_child(self.window, QPushButton, "buttonRevert")
        self.button_revert.setIcon(self.icon_manager.get_icon("rotate-ccw"))
        self.button_copy_source = require_child(self.window, QPushButton, "buttonCopySource")
        self.button_copy_source.setIcon(self.icon_manager.get_icon("copy"))
        self.button_ai_translate = require_child(self.window, QPushButton, "buttonAiTranslate")
        self.button_ai_translate.setIcon(self.icon_manager.get_icon("robot-edit"))
        self.button_ai_translate_all_models = require_child(self.window, QPushButton, "buttonAiTranslateAllModels")
        ai_button_height = self.button_copy_source.sizeHint().height()
        self.button_ai_translate.setFixedHeight(ai_button_height)
        self.button_ai_translate_all_models.setFixedHeight(ai_button_height)
        self.button_save_split = require_child(self.window, QToolButton, "buttonSaveSplit")
        self.button_save_split.setIcon(self.icon_manager.get_icon("save"))
        self.button_save_split.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        self.button_focus_first = require_child(self.window, QToolButton, "buttonFocusFirstPage")
        self.button_focus_first.setIcon(self.icon_manager.get_icon("chevrons-left"))
        self.button_focus_prev = require_child(self.window, QToolButton, "buttonFocusPrevPage")
        self.button_focus_prev.setIcon(self.icon_manager.get_icon("chevron-left"))
        self.button_focus_next = require_child(self.window, QToolButton, "buttonFocusNextPage")
        self.button_focus_next.setIcon(self.icon_manager.get_icon("chevron-right"))
        self.button_focus_last = require_child(self.window, QToolButton, "buttonFocusLastPage")
        self.button_focus_last.setIcon(self.icon_manager.get_icon("chevrons-right"))
        self.spin_focus_page_size = require_child(self.window, QSpinBox, "spinFocusPageSize")
        self.spin_focus_page_size.setValue(self.focus_controller.focus_page_size)

        layout_scrubber = require_child(self.window, QHBoxLayout, "layoutScrubberInner")
        scrubber_parent = layout_scrubber.parentWidget()
        if scrubber_parent is None:
            raise RuntimeError("スクラバーの配置先レイアウトに親ウィジェットがありません")
        self.page_scrubber = RangeScrubberWidget(scrubber_parent, text_alignment="center")
        layout_scrubber.addWidget(self.page_scrubber)

        self.edit_key = require_child(self.window, QLineEdit, "editKey")
        self.edit_file = require_child(self.window, QLineEdit, "editFile")
        self.edit_source = require_child(self.window, QPlainTextEdit, "editSource")
        self.edit_translation = require_child(self.window, QPlainTextEdit, "editTranslation")
        self.label_position = require_child(self.window, QLabel, "labelPosition")
        self.action_exit = require_child(self.window, QAction, "actionExit")
        self.action_translate_all = require_child(self.window, QAction, "actionTranslateAll")
        self.action_translate_selected = require_child(self.window, QAction, "actionTranslateSelected")
        self.action_translate_untranslated = require_child(self.window, QAction, "actionTranslateUntranslated")
        self.action_pause_translation = require_child(self.window, QAction, "actionPauseTranslation")
        self.action_stop_translation = require_child(self.window, QAction, "actionStopTranslation")
        self.action_settings = require_child(self.window, QAction, "actionSettings")
        self.action_initial_setup = require_child(self.window, QAction, "actionInitialSetup")
        self.check_project_notification = require_child(self.window, QCheckBox, "checkProjectNotification")
        self.button_project_notification_settings = require_child(self.window, QToolButton, "buttonProjectNotificationSettings")
        self.button_project_notification_settings.setIcon(self.icon_manager.get_icon("settings"))
        self.button_project_source_update = require_child(self.window, QPushButton, "buttonProjectSourceUpdate")
        self.button_project_source_update.setVisible(False)
        self.button_project_source_update.clicked.connect(self.check_source_updates)
        self.action_problems = require_child(self.window, QAction, "actionProblems")
        self.action_about = require_child(self.window, QAction, "actionAbout")
        self.action_list_mode = require_child(self.window, QAction, "actionListMode")
        self.action_dashboard_mode = require_child(self.window, QAction, "actionDashboardMode")
        self.action_focus_mode = require_child(self.window, QAction, "actionFocusMode")
        self.dock_ai_settings = require_child(self.window, QDockWidget, "dockAiSettings")
        self.action_toggle_ai_panel = require_child(self.window, QAction, "actionToggleAiPanel")
        self.label_source_language_work = require_child(self.window, QLabel, "labelSourceLanguageWork")
        self.button_translate_all = require_child(self.window, QPushButton, "buttonTranslateAll")
        self.label_translation_models = require_child(self.window, QLabel, "labelTranslationModels")
        self.button_translation_settings = require_child(self.window, QPushButton, "buttonTranslationSettings")
        self.check_auto_review = require_child(self.window, QCheckBox, "checkAutoReview")
        self.combo_review_model = require_child(self.window, QComboBox, "comboReviewModel")
        self.combo_tone = require_child(self.window, QComboBox, "comboTone")
        self.button_manage_tone = require_child(self.window, QPushButton, "buttonManageTone")
        self._refresh_tone_choices()
        self.combo_glossary = require_child(self.window, QComboBox, "comboGlossary")
        self.label_glossary_chain = require_child(self.window, QLabel, "labelGlossaryChain")
        self.button_manage_glossary = require_child(self.window, QPushButton, "buttonManageGlossary")
        self._refresh_glossary_choices()
        self._refresh_ai_choices()

        header = self.table.horizontalHeader()
        self.table_header = header
        self.table_header_viewport = header.viewport()
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.table_controller.open_table_header_menu)
        header.sectionMoved.connect(self.table_controller.handle_table_section_moved)
        header.installEventFilter(self.table_controller)
        if header.viewport() is not None:
            header.viewport().installEventFilter(self.table_controller)
        h_parent = header.viewport() if header.viewport() is not None else header
        self.header_drop_indicator = QFrame(h_parent)
        self.header_drop_indicator.setObjectName("headerDropIndicator")
        self.header_drop_indicator.setStyleSheet(
            "background-color: #2563eb; border: none; border-radius: 1px;"
        )
        self.header_drop_indicator.setFixedWidth(3)
        self.header_drop_indicator.hide()

        t_parent = self.table.viewport()
        self.table_drop_indicator = QFrame(t_parent)
        self.table_drop_indicator.setObjectName("tableDropIndicator")
        self.table_drop_indicator.setStyleSheet(
            "background-color: #2563eb; border: none; border-radius: 1px;"
        )
        self.table_drop_indicator.setFixedWidth(3)
        self.table_drop_indicator.hide()
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setShowGrid(True)
        self.table.viewport().installEventFilter(self)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.table_controller.open_row_menu)

        self.status_delegate = StatusComboBoxDelegate(self.icon_manager.get_icon, self.table)
        self.status_delegate.status_changed.connect(self.table_controller._on_table_status_delegate_changed)
        self.status_delegate.editing_started.connect(self.table_controller._on_table_status_editing_started)
        self.status_delegate.editing_finished.connect(self.table_controller._on_table_status_editing_finished)
        self.action_delegate = ActionButtonDelegate(self.icon_manager.get_icon, self.table)
        self.action_delegate.action_clicked.connect(self.table_controller._on_table_action_delegate_clicked)
        self.action_delegate.action_all_models_clicked.connect(self._on_table_action_all_models_clicked)
        self.target_text_delegate = MultiLineTextDelegate(self.table)
        self.target_text_delegate.text_edited.connect(self.table_controller._on_table_target_text_edited)
        self.target_text_delegate.editing_started.connect(self.table_controller._on_table_target_editing_started)
        self.target_text_delegate.text_committed.connect(self.table_controller._on_table_target_text_committed)
        self.target_text_delegate.editing_finished.connect(self.table_controller._on_table_target_editing_finished)

        self.progress.setVisible(False)
        count_label = QLabel(self.window)
        count_label.setObjectName("statusCountLabel")
        count_label.setStyleSheet("padding-right: 12px; font-size: 11px;")
        self.status_count_label = count_label
        status_bar = self.window.statusBar()
        if status_bar is not None:
            status_bar.addPermanentWidget(count_label)
            status_bar.addPermanentWidget(self.progress)

        # プロジェクト作成画面のウィジェット
        self.stack_main = require_child(self.window, QStackedWidget, "stackMain")
        self.frame_icon_drop = require_child(self.window, DropZone, "frameIconDrop")
        self.label_icon_preview = require_child(self.window, QLabel, "labelIconPreview")
        self.frame_icon_drop.auto_file_dialog = False
        self.frame_icon_drop.set_hint_text("")
        self.frame_icon_drop.set_content_widget(self.label_icon_preview)
        icon_frame = self.frame_icon_drop.frame_drop_zone
        icon_frame.setStyleSheet(
            icon_frame.styleSheet()
            + '\nQFrame#frameDropZone[hasIcon="true"] { border: none; }'
        )
        self.button_browse_icon = self.frame_icon_drop.add_button("", self._browse_project_icon)
        self.button_browse_icon.setObjectName("buttonBrowseIcon")
        require_child(self.frame_icon_drop.header, QHBoxLayout, "layoutDropInner").addStretch()
        self.icon_hover_actions = QWidget(self.frame_icon_drop)
        icon_actions_layout = QHBoxLayout(self.icon_hover_actions)
        icon_actions_layout.setContentsMargins(0, 0, 0, 0)
        icon_actions_layout.setSpacing(4)
        self.button_edit_icon = QToolButton(self.icon_hover_actions)
        self.button_edit_icon.setObjectName("buttonEditIcon")
        self.button_edit_icon.clicked.connect(self._browse_project_icon)
        self.button_clear_icon = QToolButton(self.icon_hover_actions)
        self.button_clear_icon.setObjectName("buttonClearIcon")
        self.button_clear_icon.clicked.connect(self.clear_project_icon)
        for button in (self.button_edit_icon, self.button_clear_icon):
            button.setFixedSize(28, 28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QToolButton { border: 1px solid palette(mid); border-radius: 14px;"
                " background-color: palette(button); color: palette(button-text); padding: 0px; }"
                "QToolButton:hover { background-color: palette(midlight); }"
            )
            icon_actions_layout.addWidget(button)
        self.icon_hover_actions.adjustSize()
        self.icon_hover_actions.hide()
        self.frame_icon_drop.installEventFilter(self)
        self.label_icon_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.label_icon_preview.installEventFilter(self)
        self.edit_icon_path = require_child(self.window, QLineEdit, "editIconPath")
        self.edit_project_name = require_child(self.window, QLineEdit, "editProjectName")
        self.combo_game = require_child(self.window, QComboBox, "comboGame")
        self.combo_source_language = require_child(self.window, QComboBox, "comboSourceLanguage")
        self.combo_source_slot = require_child(self.window, QComboBox, "comboSourceSlot")
        for code, name in qt_language_options():
            self.combo_source_language.addItem(f"{name} ({code})", code)
        source_index = self.combo_source_language.findData("en-US")
        self.combo_source_language.setCurrentIndex(max(0, source_index))
        enable_combo_search(self.combo_source_language)
        source_editor = self.combo_source_language.lineEdit()
        if source_editor is not None:
            source_editor.setPlaceholderText(tr("MainWindow", "言語名・コードで検索"))
        self.combo_target_slot = require_child(self.window, QComboBox, "comboTargetSlot")
        self.combo_target_language = require_child(self.window, QComboBox, "comboTargetLanguage")
        self.button_add_language = require_child(self.window, QPushButton, "buttonAddLanguage")

        self.frame_target_drop = require_child(self.window, DropZone, "frameDropZone")
        self.frame_target_drop.auto_file_dialog = False
        self.frame_target_drop.set_hint_text("")
        self.list_target_items = require_child(self.window, QListWidget, "listTargetItems")
        self.tab_project_inputs = require_child(self.window, QTabWidget, "tabProjectInputs")
        self.frame_inherit_drop = require_child(self.window, DropZone, "frameInheritDropZone")
        self.frame_inherit_drop.auto_file_dialog = False
        self.frame_inherit_drop.set_hint_text("")
        self.frame_inherit_drop.set_content_widget(require_child(self.window, QLabel, "labelInheritDropPrompt"))
        self.list_inherit_items = require_child(self.window, QListWidget, "listInheritItems")
        self.button_inherit_folder = self.frame_inherit_drop.add_button("", self._browse_inherit_folder)
        self.button_inherit_file = self.frame_inherit_drop.add_button("", self._browse_inherit_file)
        self.button_inherit_folder.setObjectName("buttonInheritFolder")
        self.button_inherit_file.setObjectName("buttonInheritFile")
        self._refresh_drop_actions()
        self.combo_inherit_state = require_child(self.window, QComboBox, "comboInheritState")
        self.combo_inherit_language = require_child(self.window, QComboBox, "comboInheritLanguage")
        self.combo_inherit_slot = require_child(self.window, QComboBox, "comboInheritSlot")
        self.label_embedded_translations = require_child(self.window, QLabel, "labelEmbeddedTranslations")
        self.label_embedded_translations.hide()
        self.combo_inherit_language.addItem(tr("MainWindow", "未選択"), "")
        for code, name in qt_language_options():
            self.combo_inherit_language.addItem(f"{name} ({code})", code)
        self.combo_inherit_language.currentIndexChanged.connect(self._on_inherited_language_changed)
        enable_combo_search(self.combo_inherit_language)
        inherit_editor = self.combo_inherit_language.lineEdit()
        if inherit_editor is not None:
            inherit_editor.setPlaceholderText(tr("MainWindow", "言語名・コードで検索"))
        self._init_inherited_state_choices()

        self.button_create_project = require_child(self.window, QPushButton, "buttonCreateProject")
        self.list_recent_projects = require_child(self.window, QListWidget, "listRecentProjects")
        self.list_recent_projects.itemActivated.connect(self._open_recent_project)
        self._refresh_recent_projects()
        self.action_new_project = require_child(self.window, QAction, "actionNewProject")

        self.frame_icon_drop.files_dropped.connect(self._set_dropped_project_icon)
        self.frame_target_drop.files_dropped.connect(self._drop_target_paths)
        self.frame_inherit_drop.files_dropped.connect(self._drop_inherited_paths)
        self._init_project_creation_ui()
        self._update_input_tabs_state()

    def _connect_actions(self) -> None:
        file_menu = require_child(self.window, QMenu, "menuFile")
        for command_id, title, callback in (
            ("actionOpenProject", translation_source('MainWindow', "プロジェクトを開く…"), self.open_project),
            ("actionSaveProject", "プロジェクトを保存", self.save_project),
            ("actionSaveProjectAs", translation_source('MainWindow', "プロジェクトを別名で保存…"), self.save_project_as),
            ("actionCheckSourceUpdates", translation_source('MainWindow', "翻訳元の更新を確認…"), self.check_source_updates),
        ):
            action = QAction(tr("MainWindow", title), self.window)
            action.setObjectName(command_id)
            action.triggered.connect(callback)
            file_menu.insertAction(self.action_new_project, action)
        file_menu.insertSeparator(self.action_new_project)
        export_action = QAction(tr("MainWindow", "訳文を出力…"), self.window)
        export_action.setObjectName("actionExportTranslation")
        export_action.triggered.connect(self.save_translation)
        file_menu.insertAction(self.action_exit, export_action)
        self.action_new_project.triggered.connect(self.show_new_project_page)
        self.action_exit.triggered.connect(self.window.close)

        self.combo_game.currentIndexChanged.connect(self._on_game_selection_changed)
        self.combo_source_language.currentIndexChanged.connect(self._on_source_language_changed)
        self.combo_source_slot.currentIndexChanged.connect(self._on_source_slot_changed)
        self.combo_inherit_slot.currentIndexChanged.connect(self._on_inherit_slot_changed)
        self.button_create_project.clicked.connect(self.create_project)

        self.action_settings.triggered.connect(self.open_settings)
        self.action_initial_setup.triggered.connect(self.open_initial_setup)
        self.check_project_notification.toggled.connect(self._toggle_project_notification)
        self.button_project_notification_settings.clicked.connect(lambda: self.open_settings("source_watch"))
        self.button_translation_settings.clicked.connect(lambda: self.open_settings("translation"))
        self.check_auto_review.toggled.connect(self._review_options_changed)
        self.combo_review_model.currentIndexChanged.connect(self._review_options_changed)
        self.combo_tone.currentIndexChanged.connect(self._on_tone_changed)
        self.button_manage_tone.clicked.connect(lambda: self.open_settings("tone"))
        self.combo_glossary.currentIndexChanged.connect(self._on_glossary_changed)
        self.button_manage_glossary.clicked.connect(lambda: self.open_settings("glossary"))
        self.action_glossary = QAction(tr("MainWindow", "用語集…"), self.window)
        self.action_glossary.setObjectName("actionGlossary")
        self.action_glossary.triggered.connect(lambda: self.open_settings("glossary"))
        glossary_menu = require_child(self.window, QMenu, "menuTranslate")
        glossary_menu.addSeparator()
        glossary_menu.addAction(self.action_glossary)
        self.action_problems.triggered.connect(self.open_problems_dialog)
        self.action_about.triggered.connect(self._open_about_dialog)
        self.automation_dialog = AutomationDialogController(self.window, self.icon_manager.get_icon)
        automation_action = QAction(tr("MainWindow", "自動化スクリプト…"), self.window)
        automation_action.setObjectName("actionAutomation")
        automation_action.triggered.connect(self.automation_dialog.show)
        glossary_menu.addAction(automation_action)

        self.action_list_mode.triggered.connect(self.show_list_mode)
        self.action_dashboard_mode.triggered.connect(self.show_dashboard_mode)
        self.action_focus_mode.triggered.connect(self.show_focus_mode)
        self.list_focus_units.currentRowChanged.connect(self.focus_controller._on_focus_unit_selected)
        self.action_toggle_ai_panel.triggered.connect(self._on_action_toggle_ai_panel_triggered)
        self.dock_ai_settings.visibilityChanged.connect(self._on_dock_ai_visibility_changed)
        self.stack_main.currentChanged.connect(self._on_main_page_changed)

        self.button_translate_all.clicked.connect(self.translation_controller._on_translate_button_clicked)
        self.action_translate_all.triggered.connect(self.translation_controller._start_batch_translation_all)
        self.action_translate_selected.triggered.connect(self.translation_controller._start_batch_translation_selected)
        self.action_translate_untranslated.triggered.connect(self.translation_controller._start_batch_translation_untranslated)
        self.action_stop_translation.triggered.connect(self.translation_controller._stop_batch_translation)
        self.combo_target_slot.currentIndexChanged.connect(self._on_target_slot_changed)
        self.combo_target_language.currentIndexChanged.connect(self._on_workspace_selected)
        self.button_add_language.clicked.connect(self._open_workspace_languages)

        self.button_list_mode.clicked.connect(self.show_list_mode)
        self.button_dashboard_mode.clicked.connect(self.show_dashboard_mode)
        self.button_focus_mode.clicked.connect(self.show_focus_mode)
        self.button_previous.clicked.connect(self.focus_controller.previous_entry)
        self.button_next.clicked.connect(self.focus_controller.next_entry)
        self.button_revert.clicked.connect(self.focus_controller.discard_current_draft)
        self.button_copy_source.clicked.connect(self.focus_controller.copy_source_to_translation)
        self.button_ai_translate.clicked.connect(self.ai_translate_current_unit)
        self.button_ai_translate_all_models.clicked.connect(self.ai_translate_all_models_current_unit)
        self.button_focus_first.clicked.connect(self.focus_controller.first_focus_page)
        self.button_focus_prev.clicked.connect(self.focus_controller.prev_focus_page)
        self.button_focus_next.clicked.connect(self.focus_controller.next_focus_page)
        self.button_focus_last.clicked.connect(self.focus_controller.last_focus_page)
        self.page_scrubber.value_changed.connect(self.focus_controller.set_focus_page)
        self.spin_focus_page_size.valueChanged.connect(self.focus_controller.on_focus_page_size_changed)
        self.focus_controller._setup_save_button_menu()
        self.button_save_split.clicked.connect(self.focus_controller.save_and_next)

        self.search.textChanged.connect(self.apply_filters)
        for button in (self.search_case, self.search_word, self.search_regex):
            button.toggled.connect(self.apply_filters)
        self.button_replace.clicked.connect(lambda: self._replace_matches(all_matches=False))
        self.button_replace_all.clicked.connect(lambda: self._replace_matches(all_matches=True))
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.table_controller._on_table_selection_changed)
        self.table.cellClicked.connect(self.table_controller._on_table_cell_clicked)

        self.edit_translation.textChanged.connect(self.focus_controller.mark_focus_edited)

        self._setup_debug_menu()

    def _setup_debug_menu(self) -> None:
        menu_bar = self.window.menuBar()
        help_menu: QMenu | None = None
        for action in menu_bar.actions():
            menu = action.menu()
            if isinstance(menu, QMenu) and ("ヘルプ" in action.text() or "Help" in action.text()):
                help_menu = menu
                break
        if help_menu is None:
            help_menu = QMenu(tr("MainWindow", "ヘルプ (&H)"), menu_bar)
            menu_bar.addMenu(help_menu)

        help_menu.addSeparator()

        action_update = help_menu.addAction(tr("MainWindow", "更新を確認…"))
        action_update.setObjectName("actionCheckForUpdates")
        action_update.setEnabled(True)
        action_update.triggered.connect(lambda checked=False: self._open_update_dialog())

        is_debug = "--debug" in sys.argv
        restart_label = tr("MainWindow", "通常モードで再起動") if is_debug else tr("MainWindow", "デバッグモードで再起動")
        action_restart = help_menu.addAction(restart_label)
        action_restart.setObjectName("actionRestartMode")
        action_restart.triggered.connect(self._restart_application_mode)

        action_open_plugins = help_menu.addAction(tr("MainWindow", "プラグインフォルダを開く"))
        action_open_plugins.setObjectName("actionOpenPluginsFolder")
        action_open_plugins.triggered.connect(lambda: self._open_folder(PROJECT_ROOT / "plugins"))
        action_logs = help_menu.addAction(tr("MainWindow", "ログフォルダを開く"))
        action_logs.setObjectName("actionOpenLogsFolder")
        action_logs.triggered.connect(lambda: self._open_folder(log_directory()))

    def _open_about_dialog(self) -> None:
        controller = SimpleDialogController("dialogs/AboutDialog.ui", self.window)
        require_child(controller.dialog, QLabel, "labelVersion").setText(f"Version {__version__}")
        controller.exec()

    def _open_update_dialog(self, initial_data: dict | None = None) -> None:
        from autolingua2.ui.dialogs.update import UpdateDialogController
        UpdateDialogController(self.window, initial_data=initial_data).exec()

    def _restart_application_mode(self) -> None:
        self.request_restart("--debug" not in sys.argv)

    def request_restart(self, debug: bool) -> None:
        if self._restart_target is not None or self._restart_started:
            return
        self._restart_target = debug
        self.window.close()

    def _open_folder(self, path: Path) -> None:
        try:
            self.platform.open_folder(path)
        except Exception as exc:
            QMessageBox.warning(self.window, "フォルダを開けません", str(exc))

    def _confirm_project_change(self) -> bool:
        if not self.project.sources or project_snapshot(self.workspace_service) == self._saved_project:
            return True
        answer = QMessageBox.question(
            self.window, tr("MainWindow", "未保存のプロジェクト"),
            tr("MainWindow", "プロジェクトに未保存の変更があります。保存しますか？"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def save_project_as(self) -> bool:
        return self.save_project(choose_path=True)

    def save_project(self, _checked: bool = False, *, choose_path: bool = False) -> bool:
        if self.io_worker is not None or (not self.project.sources and self.project_path is None):
            return False
        path = self.project_path
        if choose_path or path is None:
            selected, _ = QFileDialog.getSaveFileName(
                self.window, tr("MainWindow", "プロジェクトを保存"),
                str(path or (PROJECT_ROOT / "Untitled.alproj")), "Autolingua Project (*.alproj)",
            )
            if not selected:
                return False
            path = Path(selected)
            if path.suffix.lower() != ".alproj":
                path = path.with_suffix(".alproj")
        try:
            save_project(path, self.workspace_service)
            self._saved_project = project_snapshot(self.workspace_service)
        except Exception as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "保存エラー"), str(exc))
            return False
        self.project_path = path
        self._remember_current_project(path)
        self.window.statusBar().showMessage(tr("MainWindow", "プロジェクトを保存しました。"), 5000)
        if self.project.source_root:
            root = str(Path(self.project.source_root).resolve())
            if any(target.source_root == root for target in load_watch_settings().targets):
                try:
                    set_project_notification(self.project, path, True, self.plugins.parsers.get(self.project.adapter_id))
                except (OSError, ValueError) as exc:
                    QMessageBox.warning(self.window, tr("MainWindow", "通知設定エラー"), str(exc))
        self._refresh_project_notification()
        return True

    def _refresh_recent_projects(self) -> None:
        try:
            projects = load_recent_projects()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "履歴の読み込みエラー"), str(exc))
            return
        self.list_recent_projects.clear()
        for project in projects:
            item = QListWidgetItem(f"{project.name}\n{project.path}")
            item.setData(Qt.ItemDataRole.UserRole, str(project.path))
            item.setToolTip(str(project.path))
            self.list_recent_projects.addItem(item)

    def _remember_current_project(self, path: Path) -> None:
        try:
            remember_project(path, self.project.name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "履歴の保存エラー"), str(exc))
            return
        self._refresh_recent_projects()

    def _open_recent_project(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            raise ValueError("プロジェクト履歴のパスが不正です。")
        self._open_project_path(Path(path))

    def open_project(self) -> None:
        if self.import_worker is not None or self.io_worker is not None:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self.window, tr("MainWindow", "プロジェクトを開く"),
            str(self.project_path or PROJECT_ROOT), "Autolingua Project (*.alproj)",
        )
        if not selected:
            return
        self._open_project_path(Path(selected))

    def _open_project_path(self, path: Path, on_loaded: Callable[[], None] | None = None) -> bool:
        if self.import_worker is not None or self.io_worker is not None:
            return False
        if not self._confirm_project_change():
            return False

        def loaded(result: object) -> None:
            if not isinstance(result, ProjectArchive):
                raise TypeError("プロジェクトの読み込み結果が不正です。")
            service = WorkspaceService(result.imported)
            service.languages.update(result.languages)
            service.workspaces = result.workspaces
            self.load_import(result.imported, service)
            self.project_path = path
            self._refresh_project_notification()
            self._saved_project = project_snapshot(self.workspace_service)
            self.window.setWindowTitle(f"Autolingua Desktop - {self.project.name}")
            self._remember_current_project(path)
            QTimer.singleShot(0, self._poll_source_updates)
            if on_loaded is not None:
                on_loaded()

        self._run_operation(lambda: load_project(path, self.plugins.parsers), loaded)
        return True

    def _refresh_project_notification(self) -> None:
        self.button_project_source_update.setVisible(False)
        settings = load_watch_settings()
        path = str(Path(self.project.source_root).resolve()) if self.project.source_root else ""
        registered = any(target.source_root == path for target in settings.targets)
        supported = False
        error = ""
        try:
            supported = notifications_available()
        except (ImportError, AttributeError, OSError) as exc:
            error = str(exc)
        with QSignalBlocker(self.check_project_notification):
            self.check_project_notification.setChecked(registered)
        self.check_project_notification.setEnabled(bool(self.project.source_root) and supported)
        self.check_project_notification.setToolTip(error or (
            tr("MainWindow", "この環境では更新通知を利用できません。") if not supported else
            tr("MainWindow", "監視停止中") if not settings.enabled else ""))
        if registered and settings.enabled:
            self._poll_source_updates()

    def _toggle_project_notification(self, checked: bool) -> None:
        path = self.project_path
        if not self.project.source_root:
            self._refresh_project_notification()
            return
        try:
            set_project_notification(self.project, path, checked, self.plugins.parsers.get(self.project.adapter_id))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "通知設定エラー"), str(exc))
        self._refresh_project_notification()

    def request_source_update(self, project: str) -> None:
        if project not in self._requested_source_updates:
            self._requested_source_updates.append(project)

    def process_source_update_request(self) -> None:
        if not self._requested_source_updates or self.io_worker is not None or self.import_worker is not None:
            return
        if QApplication.activeModalWidget() is not None:
            return
        path = Path(self._requested_source_updates.pop(0))
        try:
            notification = notification_target(path)
            current = Path(self.project.source_root).resolve() if self.project.source_root else None
            if current != path.resolve():
                if notification.project_path:
                    self._open_project_path(Path(notification.project_path), self.check_source_updates)
                    return
                else:
                    if not self._confirm_project_change():
                        return
                    adapter = self.plugins.parsers.get(notification.adapter_id)
                    if adapter is None:
                        raise ValueError("この監視対象の読み込み方式がありません。翻訳元フォルダを読み込んでください。")
                    def loaded(value: object) -> None:
                        if not isinstance(value, ImportedTranslation):
                            raise TypeError("翻訳元の読み込み結果が不正です。")
                        self.load_import(value)
                    self._run_operation(lambda: import_notification_target(notification, adapter), loaded)
                    return
            self.check_source_updates()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "翻訳元データの更新"), str(exc))

    def _poll_source_updates(self) -> None:
        if not self.project.source_root or self.io_worker is not None or self.import_worker is not None:
            return
        if QApplication.activeModalWidget() is not None:
            return
        try:
            target, _ = pending_target(Path(self.project.source_root))
            self.button_project_source_update.setVisible(target is not None)
        except (OSError, ValueError) as exc:
            self.window.statusBar().showMessage(str(exc), 10000)

    def check_source_updates(self) -> None:
        path = self.project_path
        if not self.project.source_root or self.io_worker is not None or self.import_worker is not None:
            return
        settings = load_watch_settings()
        target = next((target for target in settings.targets if target.source_root == str(Path(self.project.source_root).resolve())), None)
        if target is None or not settings.enabled:
            QMessageBox.information(self.window, tr("MainWindow", "翻訳元データの更新"),
                                    tr("MainWindow", "設定でこのプロジェクトの監視を有効にしてください。"))
            return
        adapter = self.plugins.parsers.get(self.project.adapter_id)
        if adapter is None:
            QMessageBox.warning(self.window, tr("MainWindow", "翻訳元データの更新"),
                                tr("MainWindow", "読み込み方式がありません。"))
            return
        service = deepcopy(self.workspace_service)

        def prepared(result: object) -> None:
            if not isinstance(result, SourceUpdate):
                raise TypeError("原文の更新結果が不正です。")
            dialog = SourceUpdateDialog(result, self.window)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            dialog.dialog.deleteLater()
            if not accepted:
                return
            if self.active_workspace is not None and self.focus_controller.current_unit is not None:
                self.focus_controller.current_unit.target_text = self.edit_translation.toPlainText()
            self.translation_controller.service.stop()
            active_code = self.active_workspace.language_code if self.active_workspace is not None else None
            latest = deepcopy(self.workspace_service)

            def applied(value: object) -> None:
                if not isinstance(value, AppliedUpdate):
                    raise TypeError("原文の反映結果が不正です。")
                self.load_import(value.service.imported, value.service)
                self.project_path = path
                self._refresh_project_notification()
                QTimer.singleShot(0, self._poll_source_updates)
                self._saved_project = project_snapshot(self.workspace_service) if path is not None else None
                if active_code is not None:
                    self._select_workspace(active_code)
                if value.acknowledgment_error:
                    QMessageBox.warning(self.window, tr("MainWindow", "更新記録エラー"),
                                        value.acknowledgment_error)

            self._run_operation(lambda: apply_update(latest, result, path), applied)

        self._run_operation(lambda: prepare_update(service, target, adapter), prepared)

    def save_translation(self) -> None:
        if self.io_worker is not None:
            return
        if not self.workspace_service.workspaces:
            QMessageBox.information(
                self.window,
                tr("MainWindow", "訳文を出力"),
                tr("MainWindow", "出力する翻訳先のワークスペースを追加してください。"),
            )
            return
        snapshot = deepcopy(self.workspace_service.export_data())
        dialog = ExportDialog(
            snapshot, self.plugins.exporters, self.plugins.export_settings,
            self.output_path or PROJECT_ROOT, self.project.adapter_id, self.window,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._restart_target = None
            dialog.dialog.deleteLater()
            return
        exporter = dialog.exporter
        destination = dialog.destination
        settings = deepcopy(dialog.settings)
        dialog.dialog.deleteLater()
        if exporter is None or destination is None:
            raise RuntimeError("出力方式または出力先が選択されていません。")

        def completed(_result: object) -> None:
            self.output_path = destination

        self._run_operation(lambda: export_translation(snapshot, exporter, destination, settings), completed)

    def _run_operation(self, operation, completed) -> None:
        if self.io_worker is not None:
            return
        worker = OperationWorker(operation, self)
        self.io_worker = worker
        dialog = QProgressDialog("処理しています…", "キャンセル", 0, 0, self.window)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.canceled.connect(worker.requestInterruption)
        worker.progress.connect(dialog.setLabelText)
        worker.progress.connect(self._operation_progress)
        self._operation_dialog = dialog
        self._operation_completed = completed
        worker.finished.connect(self._operation_finished)
        worker.finished.connect(worker.deleteLater)
        dialog.show()
        worker.start()

    def _on_import_key_conflict(self, conflict: KeyConflict) -> None:
        worker = self.import_worker
        if worker is None:
            return
        if self._close_after_import or worker.isInterruptionRequested():
            worker.answer_conflict(conflict, None)
            return
        dialog = KeyConflictDialog(conflict, self.window)
        worker.finished.connect(dialog.reject)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        worker.answer_conflict(conflict, dialog.selection() if accepted else None)
        dialog.deleteLater()

    def _operation_finished(self) -> None:
        worker = self.io_worker
        if worker is None:
            return
        self.io_worker = None
        if self._pending_rules_refresh:
            QTimer.singleShot(0, self._refresh_source_rules)
        self._operation_dialog.close()
        self._operation_dialog.deleteLater()
        close_after_io = self._close_after_io
        self._close_after_io = False
        if worker.cancel_event.is_set():
            self._restart_target = None
            return
        if worker.error is not None:
            self._restart_target = None
            if not isinstance(worker.error, OperationCancelled):
                QMessageBox.warning(self.window, "プラグイン処理エラー", str(worker.error))
            return
        try:
            self._operation_completed(worker.result)
            if close_after_io and not self._restart_started:
                self.window.close()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Operation completion failed")
            self._restart_target = None
            QMessageBox.warning(self.window, "プラグイン処理エラー", str(exc))

    def _operation_progress(self, message: str) -> None:
        self.window.statusBar().showMessage(message)
        panel = self.active_creation_panel
        set_status = getattr(panel, "set_status", None)
        if callable(set_status):
            set_status(message)

    def open_settings(self, initial_category: str | None = None) -> None:
        if self._settings_dialog is not None:
            if initial_category is not None:
                self._settings_dialog.select_category(initial_category)
            self._settings_dialog.dialog.raise_()
            self._settings_dialog.dialog.activateWindow()
            return
        controller = SettingsDialogController(
            self.entrance, self.window, self.ai_settings.provider_id,
            self.ai_settings.models, self.ai_settings.selected_models, self.ai_settings.api_keys, self.ai_settings.concurrency,
            high_model=self.ai_settings.high_model, low_model=self.ai_settings.low_model, low_model_range=self.ai_settings.low_model_range,
            glossary_languages={code: workspace_language_name(self.workspace_service, code)
                                for code in self.workspace_service.languages},
            glossary_adapter_id=self.project.adapter_id, glossary_game_id=self.project.game_id,
            glossary_id=self.selected_glossary_id,
            glossary_source_language=self.project.source_language,
            glossary_target_language=self.project.target_language,
            tone_id=self.selected_tone_id,
            on_saved=self._apply_settings,
            mcp_server=self.mcp_server,
        )
        controller.watch_page.update_requested.connect(self.request_source_update)
        if initial_category is not None:
            controller.select_category(initial_category)
            if initial_category == "shortcuts":
                controller.shortcut_page.select_command(getattr(self, "_pending_shortcut_command", ""))
            if initial_category == "source_watch" and self.project.source_root:
                controller.watch_page.select_project(str(Path(self.project.source_root).resolve()))
        self._settings_dialog = controller
        try:
            controller.exec()
        finally:
            self._settings_dialog = None

        self._refresh_glossary_choices()
        self._refresh_tone_choices()
        self._refresh_project_notification()

    def show_initial_setup_if_needed(self) -> None:
        from autolingua2.services.settings.settings_store import initial_setup_seen
        if not initial_setup_seen():
            self.open_initial_setup()

    def _open_shortcut_settings(self, command_id: str) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.select_category("shortcuts")
            self._settings_dialog.shortcut_page.select_command(command_id)
            self._settings_dialog.dialog.raise_()
            self._settings_dialog.dialog.activateWindow()
            return
        self._pending_shortcut_command = command_id
        try:
            self.open_settings("shortcuts")
        finally:
            self._pending_shortcut_command = ""

    def open_initial_setup(self) -> None:
        from autolingua2.ui.dialogs.initial_setup import InitialSetupController
        if self._initial_setup_dialog is not None:
            self._initial_setup_dialog.raise_()
            self._initial_setup_dialog.activateWindow()
            return
        controller: InitialSetupController | None = None
        try:
            controller = InitialSetupController(self.entrance, self.window)
            self._initial_setup_dialog = controller.dialog
            controller.exec()
            if controller.saved:
                self.ai_settings = load_ai_settings(self.provider_registry)
                self._refresh_ai_choices()
                self.chat_dock.refresh_choices()
        except Exception as error:
            QMessageBox.warning(self.window, tr("MainWindow", "初期設定"), str(error))
        finally:
            self._initial_setup_dialog = None
            if controller is not None:
                controller.dialog.deleteLater()
                controller.deleteLater()

    def _apply_settings(self, controller: SettingsDialogController) -> None:
        self.ai_settings = deepcopy(controller.ai_page.settings())
        self._refresh_ai_choices()
        self.chat_dock.refresh_choices()
        _, icon_theme = load_theme_settings()
        self.icon_manager.set_current_iconset(icon_theme)
        self.chat_dock.refresh_icons()
        self.search_bar.set_icons(self.icon_manager.get_icon)
        self.button_replace.setIcon(self.icon_manager.get_icon("replace"))
        self.button_replace_all.setIcon(self.icon_manager.get_icon("replace-all"))
        self.automation_dialog.refresh_icons()
        self._refresh_drop_actions()
        self.chat_dock.refresh_voice_input()
        self._configure_mcp()
        if self.active_creation_panel:
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.sendEvent(self.active_creation_panel, QEvent(QEvent.Type.LanguageChange))
        if (self.project.adapter_id, self.project.game_id) in controller.filter_rules_page.changed_keys:
            self._refresh_source_rules()
        if self.units:
            self.refresh_all()
        self._refresh_glossary_choices()
        self._refresh_tone_choices()
        self._refresh_project_notification()

    def _refresh_tone_choices(self) -> None:
        try:
            self.tone_choices = self.tone_store.load()
        except (OSError, ValueError) as exc:
            self.tone_choices = []
            QMessageBox.warning(self.window, tr("MainWindow", "口調を読み込めません"), str(exc))
        with QSignalBlocker(self.combo_tone):
            self.combo_tone.clear()
            self.combo_tone.addItem(tr("MainWindow", "なし"), "")
            for tone in self.tone_choices:
                label = tone.name + (tr("MainWindow", "［条件付き］") if isinstance(tone, ConditionalTone) else "")
                self.combo_tone.addItem(label, tone.id)
            self.combo_tone.setCurrentIndex(max(0, self.combo_tone.findData(self.selected_tone_id)))
        self._on_tone_changed()

    def _on_tone_changed(self, _index: int = 0) -> None:
        self.selected_tone_id = str(self.combo_tone.currentData() or "")
        if self.active_workspace is not None:
            if self.active_workspace.tone_id != self.selected_tone_id:
                self.active_workspace.generation += 1
            self.active_workspace.tone_id = self.selected_tone_id

    def _refresh_glossary_choices(self) -> None:
        self.glossary_choices = []
        try:
            if self.project.adapter_id and self.project.game_id:
                self.glossary_choices = self.glossary_store.list_glossaries(
                    self.project.adapter_id, self.project.game_id)
            labels = [(item.id, " → ".join(g.name for g in glossary_chain(self.glossary_choices, item.id)))
                      for item in self.glossary_choices]
        except STORAGE_ERRORS as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "用語集を読み込めません"), str(exc))
            labels = []
            self.glossary_choices = []
        with QSignalBlocker(self.combo_glossary):
            self.combo_glossary.clear()
            self.combo_glossary.addItem(tr("MainWindow", "なし"), "")
            for glossary_id, label in labels:
                self.combo_glossary.addItem(label, glossary_id)
            selected = self.combo_glossary.findData(self.selected_glossary_id)
            self.combo_glossary.setCurrentIndex(max(0, selected))
        self.combo_glossary.setEnabled(bool(self.project.adapter_id and self.project.game_id))
        self._on_glossary_changed()

    def _on_glossary_changed(self, _index: int = 0) -> None:
        self.selected_glossary_id = str(self.combo_glossary.currentData() or "")
        if self.active_workspace is not None:
            if self.active_workspace.glossary_id != self.selected_glossary_id:
                self.active_workspace.generation += 1
            self.active_workspace.glossary_id = self.selected_glossary_id
        self.label_glossary_chain.setText(self.combo_glossary.currentText())

    def _refresh_ai_choices(self) -> None:
        def describe(selection: ModelSelection | None) -> str:
            if selection is None:
                return tr("MainWindow", "未設定")
            provider = self.provider_registry.get(selection.provider_id)
            model = next((item for item in self.ai_settings.models.get(selection.provider_id, [])
                          if item.model == selection.model_id and item.enabled), None)
            if provider is None or model is None:
                return tr("MainWindow", "利用不可：{provider} / {model}").format(
                    provider=selection.provider_id, model=selection.model_id)
            return f"{provider.display_name} / {model.name}"
        self.label_translation_models.setText(tr("MainWindow", "高モデル：{high}\n低モデル：{low}").format(
            high=describe(self.ai_settings.high_model), low=describe(self.ai_settings.low_model)))
        with QSignalBlocker(self.check_auto_review), QSignalBlocker(self.combo_review_model):
            self.check_auto_review.setChecked(self.ai_settings.review_enabled)
            self.combo_review_model.clear()
            self.combo_review_model.addItem(tr("MainWindow", "未設定"), "")
            for provider_id, models in self.ai_settings.models.items():
                provider = self.provider_registry.get(provider_id)
                if provider is None:
                    continue
                for model in models:
                    if model.enabled:
                        self.combo_review_model.addItem(f"{provider.display_name} / {model.name}",
                                                        json.dumps([provider_id, model.model]))
            selection = self.ai_settings.review_model
            if selection is not None:
                index = self.combo_review_model.findData(json.dumps([selection.provider_id, selection.model_id]))
                if index >= 0:
                    self.combo_review_model.setCurrentIndex(index)
            self.combo_review_model.setEnabled(self.ai_settings.review_enabled)

    def _review_options_changed(self) -> None:
        value = self.combo_review_model.currentData()
        selection: ModelSelection | None = None
        if isinstance(value, str) and value:
            provider_id, model_id = json.loads(value)
            if not isinstance(provider_id, str) or not isinstance(model_id, str):
                raise ValueError("校閲モデルの選択が不正です。")
            selection = ModelSelection(provider_id, model_id)
        self.ai_settings.review_enabled = self.check_auto_review.isChecked()
        self.ai_settings.review_model = selection
        self.combo_review_model.setEnabled(self.ai_settings.review_enabled)
        save_ai_settings(self.ai_settings)

    def _configure_mcp(self) -> None:
        settings = load_mcp_settings()
        self.mcp_server.configure(settings)
        self.mcp_client.configure(settings.connections)

    def _operations_idle(self) -> None:
        if self._close_after_operations:
            self._close_after_operations = False
            self.window.close()

    def _operation_select(self, language: str, value: object) -> None:
        ids = [json_text(item) for item in json_array(value)]
        if self.active_workspace is None or self.active_workspace.language_code != language:
            self._select_workspace(language, preserve_chat=True)
        self._chat_select_units(ids)

    def _operation_project_replaced(self, value: object) -> None:
        if not isinstance(value, WorkspaceService):
            raise TypeError("Invalid updated project")
        path, saved = self.project_path, self._saved_project
        self.load_import(value.imported, value)
        self.project_path, self._saved_project = path, saved

    def _operation_project_saved(self, path: str, snapshot: object) -> None:
        if not isinstance(snapshot, bytes):
            raise TypeError("Invalid saved project snapshot")
        self.project_path = Path(path)
        self._saved_project = snapshot
        self._refresh_project_notification()
        self._remember_current_project(self.project_path)

    def _operation_preferences(self, language: str, glossary_id: str, tone_id: str) -> None:
        if self.active_workspace is not None and self.active_workspace.language_code == language:
            self.selected_glossary_id, self.selected_tone_id = glossary_id, tone_id

    def _operation_apply_ui_language(self, language: str) -> None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication インスタンスが存在しません。")
        self.entrance.localization.apply_language(app, language)

    def _operation_translation_language_changed(self, language: str) -> None:
        ids = [reference.id for reference in self._chat_selected_references()]
        self._select_workspace(language or None, preserve_chat=True)
        self._refresh_workspace_selection()
        self.overview_controller.invalidate()
        if ids and language:
            self._chat_select_units(ids)
        self.operations.scope_language = language if self.chat_dock.scope_combo.currentData() != "project" else ""

    def _operation_refresh(self) -> None:
        self._refresh_glossary_choices()
        self._refresh_tone_choices()
        self.refresh_all()

    def _chat_settings(self) -> AiSettings:
        return self.ai_settings

    @staticmethod
    def _chat_reference(unit: TranslationUnit) -> ChatReference:
        return ChatReference(unit.id, unit.label, unit.source_text, unit.target_text,
                             unit.state == UnitState.UNTRANSLATED)

    def _chat_current_file(self) -> ChatFile | None:
        unit = self.focus_controller.current_unit
        if unit is None:
            return None
        ref = self.imported.source_refs.get(unit.id)
        if ref is None:
            return None
        units = tuple(self._chat_reference(item) for item in self.units
                      if (item_ref := self.imported.source_refs.get(item.id)) is not None
                      and item_ref.source_id == ref.source_id)
        language = self.active_workspace.language_code if self.active_workspace is not None else ""
        return ChatFile((id(self.imported), language, ref.source_id), self.source_name_for_unit(unit), units)

    def _chat_selected_references(self) -> tuple[ChatReference, ...]:
        if self.stack.currentWidget() is self.page_focus:
            return (self._chat_reference(self.focus_controller.current_unit),) if self.focus_controller.current_unit is not None else ()
        if self.stack.currentWidget() is not self.page_list:
            return ()
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return tuple(self._chat_reference(self.filtered_units[row]) for row in rows
                     if 0 <= row < len(self.filtered_units))

    def _chat_select_units(self, ids: list[str]) -> None:
        selected_ids = set(ids)
        if not selected_ids:
            self.table.clearSelection()
            return
        # Make matches visible even if the existing status/text filter excludes them.
        with QSignalBlocker(self.search), QSignalBlocker(self.status_filter):
            self.search.clear()
            self.status_filter.setCurrentText(tr("MainWindow", "すべて"))
        self.apply_filters()
        self.show_list_mode()
        selection_model = self.table.selectionModel()
        model = self.table.model()
        if selection_model is None or model is None:
            raise RuntimeError("翻訳表の選択モデルがありません。")
        selection = QItemSelection()
        first_row: int | None = None
        for row, unit in enumerate(self.filtered_units):
            if unit.id in selected_ids:
                selection.select(model.index(row, 0), model.index(row, self.table.columnCount() - 1))
                if first_row is None:
                    first_row = row
        selection_model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if first_row is not None:
            self.focus_controller.current_unit = self.filtered_units[first_row]
            self.table.scrollTo(model.index(first_row, 0))
            self.focus_controller.refresh_focus()

    def _chat_selection_origin(self) -> str:
        selected_ids = {reference.id for reference in self._chat_selected_references()}
        files = sorted({self.source_name_for_unit(unit) for unit in self.units if unit.id in selected_ids})
        language = self.active_workspace.language_code if self.active_workspace is not None else ""
        return " / ".join([language, *files])

    def _on_ui_language_changed(self, language_code: str) -> None:
        self._refresh_drop_actions()
        self._configure_text_presentation()
        previous_errors = self._known_plugin_errors
        self._known_plugin_errors = len(self.plugins.errors)
        if len(self.plugins.errors) > previous_errors:
            QMessageBox.warning(self.window, "プラグインエラー", "\n".join(self.plugins.errors[previous_errors:]))
        with QSignalBlocker(self.combo_game):
            for index in range(self.combo_game.count()):
                adapter, game = self.combo_game.itemData(index)
                self.combo_game.setItemText(index, f"{game.name} ({adapter.name})")
        if self.active_adapter:
            selected = self.combo_game.currentData()
            if selected:
                _, game = selected
                for combo in (self.combo_source_slot, self.combo_inherit_slot):
                    with QSignalBlocker(combo):
                        combo.setItemText(0, tr("MainWindow", "絞り込まない"))
                        for slot in game.slots:
                            index = combo.findData(slot.slot_id)
                            if index >= 0:
                                combo.setItemText(index, f"{slot.slot_id} ({slot.name})")
                with QSignalBlocker(self.combo_target_slot):
                    for slot in game.slots:
                        index = self.combo_target_slot.findData(slot.slot_id)
                        if index >= 0:
                            self.combo_target_slot.setItemText(index, f"{slot.slot_id} ({slot.name})")
                    if not game.slots:
                        self.combo_target_slot.setItemText(0, tr("MainWindow", "該当なし"))
        self._refresh_all_target_labels()
        self.table_controller.refresh_columns()
        self.refresh_all()

    def _refresh_source_rules(self) -> None:
        if self.io_worker is not None or self.import_worker is not None:
            self._pending_rules_refresh = True
            return
        self._pending_rules_refresh = False
        imported = self.imported
        adapter = self.plugins.parsers.get(imported.project.adapter_id)
        if adapter is None:
            return
        config = get_filter_config(adapter, imported.project.game_id)
        snapshot = deepcopy(imported)
        threshold = imported.classification.threshold if imported.classification is not None else 0.8

        def completed(result: ClassificationResult) -> None:
            if self.imported is not imported or imported.project.game_id != snapshot.project.game_id:
                return
            if get_filter_config(adapter, imported.project.game_id).rules != config.rules:
                return
            if [(unit.id, unit.source_text) for unit in imported.project.units] != [
                (unit.id, unit.source_text) for unit in snapshot.project.units
            ]:
                return
            imported.classification = result
            imported.excluded_unit_ids.clear()
            imported.excluded_unit_ids.update(snapshot.excluded_unit_ids)
            self.refresh_all()

        self._run_operation(
            lambda: classify_sources(snapshot, adapter, threshold=threshold, config=config), completed,
        )

    def _init_project_creation_ui(self) -> None:
        self.combo_game.blockSignals(True)
        self.combo_game.clear()
        for adapter in self.plugins.parsers.values():
            for game in adapter.supported_games:
                self.combo_game.addItem(f"{game.name} ({adapter.name})", (adapter, game))
        self.combo_game.blockSignals(False)

        self._on_game_selection_changed()

    def _on_game_selection_changed(self) -> None:
        if self._changing_game:
            return
        selected_data = self.combo_game.currentData()
        if not selected_data:
            return
        adapter, game = selected_data
        self._changing_game = True
        new_context: MainWindowCreationContext | None = None
        creation_adapter: CreationAdapter | None = None
        panel = None
        try:
            creation_adapter = self.creation_adapters.get(adapter.id)
            if creation_adapter is None:
                raise RuntimeError("UI extension is not connected: " + adapter.id)
            if self.active_adapter is not adapter:
                new_context = MainWindowCreationContext(self, adapter.id)
                self.plugins.bind_creation(adapter.id, new_context.actions())
                panel = creation_adapter.create_creation_panel(self.plugins.context(adapter.id))
                if not isinstance(panel, QWidget):
                    raise TypeError("create_creation_panel must return QWidget")
                if self.active_creation_panel is not None:
                    previous_adapter = self.active_creation_adapter
                    if previous_adapter is None:
                        raise RuntimeError("Creation panel has no owning adapter")
                    previous_adapter.dispose_creation_panel(self.active_creation_panel)
                if self.creation_context:
                    self.creation_context.active = False
                    self.plugins.bind_creation(self.creation_context.adapter_id, None)
                self.active_adapter = adapter
                self.active_creation_adapter = creation_adapter
                self.creation_context = new_context
                self.active_creation_panel = panel
                self.frame_target_drop.set_content_widget(panel)

            # ファイルのスロットとワークスペースの言語は独立して管理する。
            for combo in (self.combo_source_slot, self.combo_inherit_slot):
                with QSignalBlocker(combo):
                    previous = combo.currentData()
                    combo.clear()
                    combo.addItem(tr("MainWindow", "絞り込まない"), "")
                    for slot in game.slots:
                        combo.addItem(f"{slot.slot_id} ({slot.name})", slot.slot_id)
                    initial = game.default_slot_id if combo is self.combo_source_slot and previous is None else previous
                    combo.setCurrentIndex(max(0, combo.findData(initial or "")))
            for code, name in adapter.supported_languages if isinstance(adapter, SupportedLanguagesAdapter) else ():
                if self.combo_source_language.findData(code) < 0:
                    self.combo_source_language.addItem(f"{name} ({code})", code)

            # 出力言語スロット: 選択されたゲームのスロットに連動
            with QSignalBlocker(self.combo_target_slot):
                self.combo_target_slot.clear()
                for slot in game.slots:
                    self.combo_target_slot.addItem(f"{slot.slot_id} ({slot.name})", slot.slot_id)
                if not game.slots:
                    self.combo_target_slot.addItem(tr("MainWindow", "該当なし"), "")
                self.combo_target_slot.setEnabled(bool(game.slots))
                default_idx = self.combo_target_slot.findData(game.default_slot_id)
                self.combo_target_slot.setCurrentIndex(max(0, default_idx))
            context = self.creation_context
            if context is None:
                raise RuntimeError("Creation context is missing")
            creation_adapter.on_game_selected(game.id, self.plugins.context(adapter.id))
            self._creation_valid = True
            self._panel_valid = True
            self._refresh_inherited_language()
            self._refresh_all_target_labels()
        except Exception as exc:
            if new_context is not None and new_context is not self.creation_context:
                new_context.active = False
                self.plugins.bind_creation(new_context.adapter_id, None)
                if isinstance(panel, QWidget):
                    if creation_adapter is not None:
                        try:
                            creation_adapter.dispose_creation_panel(panel)
                        except Exception as disposal_error:
                            self.plugins.report_error(new_context.adapter_id, disposal_error)
                    panel.deleteLater()
            self._creation_valid = False
            self._panel_valid = False
            QMessageBox.warning(self.window, "プラグインエラー", f"{adapter.name}: {exc}")
        finally:
            self._changing_game = False
            self.button_create_project.setEnabled(self._creation_valid)

    def select_game_by_id(self, game_id: str, adapter_id: str) -> None:
        for idx in range(self.combo_game.count()):
            data = self.combo_game.itemData(idx)
            if data:
                adapter, game = data
                if adapter.id == adapter_id and game.id == game_id:
                    self.combo_game.setCurrentIndex(idx)
                    return
        raise ValueError(f"Unknown game: {adapter_id}/{game_id}")

    def show_new_project_page(self) -> None:
        self.stack_main.setCurrentIndex(0)

    def _set_dropped_project_icon(self, paths: list[Path]) -> list[Path]:
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".bmp"}
        images = [path for path in paths if not path.is_dir() and path.suffix.lower() in image_exts]
        for path in images:
            if self.set_project_icon(path):
                break
        return [path for path in paths if path not in images]

    def set_project_icon(self, path: Path, *, manual: bool = True) -> bool:
        if not manual and self._project_icon_is_manual:
            return False
        if not path.is_file():
            return False
        pixmap = self.icon_manager.load_pixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self.window, tr("MainWindow", "エラー"), tr("MainWindow", "有効な画像ファイルではありません。"))
            return False
        try:
            thumbnail = read_project_thumbnail(path)
        except OSError as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "エラー"), str(exc))
            return False
        self.selected_icon_path = path.resolve()
        self._selected_thumbnail = thumbnail
        self._project_icon_is_manual = manual
        self._project_icon_pixmap = pixmap
        self._resize_project_icon_preview()
        self.edit_icon_path.setText(path.name)
        self.edit_icon_path.setToolTip(str(self.selected_icon_path))
        self._sync_project_icon_actions()
        return True

    def _resize_project_icon_preview(self) -> None:
        pixmap = self._project_icon_pixmap
        if pixmap is None:
            return
        size = self.label_icon_preview.contentsRect().size()
        if size.isEmpty():
            return
        self.label_icon_preview.setPixmap(pixmap.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        ))

    def _sync_project_icon_actions(self) -> None:
        has_icon = self.selected_icon_path is not None
        frame = self.frame_icon_drop.frame_drop_zone
        if frame.property("hasIcon") != has_icon:
            frame.setProperty("hasIcon", has_icon)
            style = frame.style()
            if style is not None:
                style.unpolish(frame)
                style.polish(frame)
            frame.update()
        self.button_browse_icon.setVisible(not has_icon)
        self.frame_icon_drop.header.setVisible(not has_icon)
        actions = self.icon_hover_actions
        actions.move(
            max(0, self.frame_icon_drop.width() - actions.width() - 8),
            max(0, self.frame_icon_drop.height() - actions.height() - 8),
        )
        actions.setVisible(has_icon and self.frame_icon_drop.underMouse())
        actions.raise_()

    def _browse_project_icon(self) -> None:
        file_filter = tr("MainWindow", "画像ファイル (*.png *.jpg *.jpeg *.webp *.ico *.bmp);;すべてのファイル (*.*)")
        path_str, _ = QFileDialog.getOpenFileName(self.window, tr("MainWindow", "アイコン画像を選択"), "", file_filter)
        if path_str:
            self.set_project_icon(Path(path_str))

    def clear_project_icon(self) -> None:
        self.selected_icon_path = None
        self._selected_thumbnail = ""
        self._project_icon_pixmap = None
        self._project_icon_is_manual = False
        self.label_icon_preview.clear()
        self.label_icon_preview.setText(tr("MainWindow", "アイコン画像\n未設定"))
        self.edit_icon_path.clear()
        self.edit_icon_path.setToolTip("")
        self._sync_project_icon_actions()

    def _update_path_label(self, path: Path, lbl: QLabel) -> None:
        current_src = str(self.combo_source_slot.currentData() or "")
        try:
            adapter = self.active_adapter
            if adapter is None:
                raise RuntimeError("No creation adapter selected")
            if not path.exists() or (path.is_file() and not adapter.can_load(path)):
                raise ValueError(tr("MainWindow", "選択形式で読み込めない対象です"))
            creation_adapter = self.active_creation_adapter
            if creation_adapter is None:
                raise RuntimeError("No UI extension connected")
            text, style, tooltip = creation_adapter.format_target_path_label(path, current_src)
        except Exception as exc:
            text = path.name
            style = "color: #d97706;"
            tooltip = str(exc)
            self._creation_valid = False
            self.button_create_project.setEnabled(False)
        lbl.setText(text)
        lbl.setStyleSheet(style)
        lbl.setToolTip(tooltip)

    def _update_input_tabs_state(self) -> None:
        has_source = bool(self.target_paths)
        self.tab_project_inputs.setTabEnabled(1, has_source)
        if not has_source and self.tab_project_inputs.currentIndex() == 1:
            self.tab_project_inputs.setCurrentIndex(0)
        needs_language = bool(self.inherited_paths) or self._embedded_sources
        language_valid = not needs_language or bool(self.combo_inherit_language.currentData())
        self.label_embedded_translations.setVisible(self._embedded_sources)
        self.button_create_project.setEnabled(has_source and self._creation_valid and language_valid
                                              and self.import_worker is None and self.io_worker is None)

    def _on_inherited_language_changed(self) -> None:
        self._inherit_language_manual = True
        self._update_input_tabs_state()

    def _refresh_inherited_language(self) -> None:
        adapter = self.active_adapter
        source_paths = self.target_paths
        source_slot = str(self.combo_source_slot.currentData() or "")
        if adapter is not None and source_slot and source_paths:
            try:
                source_paths = adapter.filter_source_files(source_paths, source_slot)
            except (OSError, ValueError):
                source_paths = []
        self._embedded_sources = (isinstance(adapter, EmbeddedTranslationAdapter)
                                  and any(adapter.contains_translations(path) for path in source_paths))
        if isinstance(adapter, SupportedLanguagesAdapter):
            for code, name in adapter.supported_languages:
                if self.combo_inherit_language.findData(code) < 0:
                    self.combo_inherit_language.addItem(f"{name} ({code})", code)
        if not self.inherited_paths and not self._embedded_sources:
            self._inherit_language_manual = False
        if not self._inherit_language_manual:
            inherited_paths = self.inherited_paths
            inherited_slot = str(self.combo_inherit_slot.currentData() or "")
            if adapter is not None and inherited_slot and inherited_paths:
                try:
                    inherited_paths = adapter.filter_source_files(inherited_paths, inherited_slot)
                except (OSError, ValueError):
                    inherited_paths = []
            language = (detect_inherited_language(adapter, inherited_paths)
                        if adapter is not None and not self._embedded_sources else None)
            with QSignalBlocker(self.combo_inherit_language):
                self.combo_inherit_language.setCurrentIndex(max(0, self.combo_inherit_language.findData(language or "")))
        self._update_input_tabs_state()

    def _refresh_all_target_labels(self) -> None:
        self._creation_valid = self._panel_valid
        for path, (lbl, _) in self.target_item_widgets.items():
            self._update_path_label(path, lbl)
        self._update_input_tabs_state()

    def _on_source_language_changed(self) -> None:
        self._update_input_tabs_state()

    def _on_source_slot_changed(self) -> None:
        self._refresh_all_target_labels()
        self._refresh_inherited_language()

    def _on_inherit_slot_changed(self) -> None:
        self._refresh_inherited_language()

    def add_target_path(self, path: Path) -> None:
        resolved = path.resolve()
        if self.import_worker is not None:
            return
        adapter = self.active_adapter
        if adapter is None:
            raise RuntimeError("No creation adapter selected")
        if not resolved.exists() or (resolved.is_file() and not adapter.can_load(resolved)):
            raise ValueError(f"選択形式で読み込めない対象です: {path}")
        if resolved in self.target_paths:
            return
        self.target_paths.append(resolved)

        if not self.edit_project_name.text().strip():
            self.edit_project_name.setText(resolved.stem if resolved.is_file() else resolved.name)

        item = QListWidgetItem(self.list_target_items)
        row_widget = QWidget()
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # SVGアイコン表示
        icon_lbl = QLabel()
        icon_name = "folder" if resolved.is_dir() else "file"
        icon = self.icon_manager.get_icon(icon_name)
        icon_lbl.setPixmap(icon.pixmap(16, 16))
        icon_lbl.setFixedSize(18, 18)

        lbl = QLabel()
        btn_del = QPushButton()
        btn_del.setIcon(self.icon_manager.get_icon("trash"))
        btn_del.setFixedSize(24, 24)
        btn_del.setToolTip(tr("MainWindow", "この項目を削除"))
        btn_del.clicked.connect(lambda: self.remove_target_path(resolved, item))

        layout.addWidget(icon_lbl, 0)
        layout.addWidget(lbl, 1)
        layout.addWidget(btn_del, 0)

        item.setSizeHint(row_widget.sizeHint())
        self.list_target_items.addItem(item)
        self.list_target_items.setItemWidget(item, row_widget)

        self.target_item_widgets[resolved] = (lbl, item)
        self._update_path_label(resolved, lbl)
        self._refresh_inherited_language()

    def remove_target_path_by_path(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved in self.target_item_widgets:
            _, item = self.target_item_widgets[resolved]
            self.remove_target_path(resolved, item)

    def remove_target_path(self, path: Path, item: QListWidgetItem) -> None:
        if path in self.target_paths:
            self.target_paths.remove(path)
        self.target_item_widgets.pop(path, None)
        if path in self.target_files:
            self.target_files.remove(path)
        row = self.list_target_items.row(item)
        if row >= 0:
            self.list_target_items.takeItem(row)
        self._refresh_all_target_labels()
        self._refresh_inherited_language()

    def _browse_inherit_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.window, tr("MainWindow", "既存の翻訳フォルダを選択"))
        if folder:
            self.add_inherited_path(Path(folder))

    def _browse_inherit_file(self) -> None:
        adapter = self.active_adapter
        filter_str = tr("MainWindow", "すべてのファイル (*.*)")
        if adapter is not None and getattr(adapter, "suffixes", None):
            pattern = " ".join(f"*{s}" for s in adapter.suffixes)
            filter_str = tr("MainWindow", "対応ファイル ({pattern});;すべてのファイル (*.*)").format(pattern=pattern)
        files, _ = QFileDialog.getOpenFileNames(self.window, tr("MainWindow", "既存の翻訳ファイルを選択"), "", filter_str)
        for f in files:
            self.add_inherited_path(Path(f))

    def add_inherited_path(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.exists():
            return
        adapter = self.active_adapter
        if adapter is not None and resolved.is_file() and not adapter.can_load(resolved):
            QMessageBox.warning(self.window, tr("MainWindow", "警告"), tr("MainWindow", "選択形式で読み込めない対象です: ") + path.name)
            return
        if resolved in self.inherited_paths:
            return
        self.inherited_paths.append(resolved)

        item = QListWidgetItem(self.list_inherit_items)
        row_widget = QWidget()
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        icon_lbl = QLabel()
        icon_name = "folder" if resolved.is_dir() else "file"
        icon = self.icon_manager.get_icon(icon_name)
        icon_lbl.setPixmap(icon.pixmap(16, 16))
        icon_lbl.setFixedSize(18, 18)

        lbl = QLabel(resolved.name)
        lbl.setToolTip(str(resolved))

        btn_del = QPushButton()
        btn_del.setIcon(self.icon_manager.get_icon("trash"))
        btn_del.setFixedSize(24, 24)
        btn_del.setToolTip(tr("MainWindow", "この項目を削除"))
        btn_del.clicked.connect(lambda: self.remove_inherited_path(resolved, item))

        layout.addWidget(icon_lbl, 0)
        layout.addWidget(lbl, 1)
        layout.addWidget(btn_del, 0)

        item.setSizeHint(row_widget.sizeHint())
        self.list_inherit_items.addItem(item)
        self.list_inherit_items.setItemWidget(item, row_widget)
        self.inherited_item_widgets[resolved] = (lbl, item)
        self._refresh_inherited_language()

    def remove_inherited_path(self, path: Path, item: QListWidgetItem) -> None:
        if path in self.inherited_paths:
            self.inherited_paths.remove(path)
        self.inherited_item_widgets.pop(path, None)
        row = self.list_inherit_items.row(item)
        if row >= 0:
            self.list_inherit_items.takeItem(row)
        self._refresh_inherited_language()

    def _init_inherited_state_choices(self) -> None:
        self.combo_inherit_state.clear()
        options: list[tuple[str, UnitState, str]] = [
            (tr("MainWindow", "人間による校閲"), UnitState.HUMAN_REVIEWED, "person-check"),
            (tr("MainWindow", "人間による翻訳"), UnitState.HUMAN_TRANSLATED, "person-edit-32"),
            (tr("MainWindow", "AIによる校閲"), UnitState.AI_REVIEWED, "robot-check"),
            (tr("MainWindow", "AIによる翻訳"), UnitState.AI_TRANSLATED, "robot-edit"),
            (tr("MainWindow", "疑問あり"), UnitState.DOUBTFUL, "question"),
            (tr("MainWindow", "翻訳エラー"), UnitState.TRANSLATION_ERROR, "question"),
            (tr("MainWindow", "校閲エラー"), UnitState.REVIEW_ERROR, "question"),
            (tr("MainWindow", "校閲指摘あり"), UnitState.REVIEW_ISSUES, "question"),
            (tr("MainWindow", "未翻訳"), UnitState.UNTRANSLATED, "circle"),
        ]
        for label, state, icon_name in options:
            icon = self.icon_manager.get_icon(icon_name)
            self.combo_inherit_state.addItem(icon, label, state)
        self.combo_inherit_state.setCurrentIndex(0)

    def create_project(self) -> None:
        if self.import_worker is not None or self.io_worker is not None or not self._creation_valid:
            return
        if not self.target_paths:
            QMessageBox.warning(self.window, tr("MainWindow", "警告"), tr("MainWindow", "翻訳対象のファイルまたはフォルダを追加してください。"))
            return

        inherited_language = self.combo_inherit_language.currentData()
        if (self.inherited_paths or self._embedded_sources) and not inherited_language:
            self.tab_project_inputs.setCurrentIndex(1)
            QMessageBox.warning(self.window, tr("MainWindow", "警告"),
                                tr("MainWindow", "継承する訳文の言語を選択してください。"))
            return

        selected_data = self.combo_game.currentData()
        adapter, game = selected_data if selected_data else (None, None)

        if adapter is None or game is None:
            return
        self._import_metadata = dict(
            name=self.edit_project_name.text().strip() or "Untitled",
            thumbnail=self._selected_thumbnail,
            game_id=game.id,
            target_language="",
        )

        state_data = self.combo_inherit_state.currentData()
        inherited_state = state_data if isinstance(state_data, UnitState) else UnitState.HUMAN_REVIEWED

        worker = ImportWorker(
            adapter,
            self.target_paths,
            str(self.combo_source_language.currentData() or "en-US"),
            self,
            game_id=game.id,
            source_slot=str(self.combo_source_slot.currentData() or ""),
            inherited_paths=self.inherited_paths,
            inherited_slot=str(self.combo_inherit_slot.currentData() or ""),
            inherited_language=str(inherited_language or ""),
            inherited_state=inherited_state,
        )
        self.import_worker = worker
        self._set_import_busy(True)
        worker.loaded.connect(self._on_project_imported)
        worker.failed.connect(self._on_import_failed)
        worker.progress.connect(self._operation_progress)
        worker.conflict_requested.connect(self._on_import_key_conflict)
        worker.finished.connect(self._on_import_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _set_import_busy(self, busy: bool) -> None:
        for widget in (self.combo_game, self.combo_source_language, self.combo_source_slot,
                       self.edit_project_name, self.list_target_items,
                       self.list_inherit_items, self.button_inherit_folder,
                       self.button_inherit_file, self.combo_inherit_state, self.combo_inherit_language, self.combo_inherit_slot,
                       self.tab_project_inputs, self.frame_icon_drop):
            widget.setEnabled(not busy)
        if self.active_creation_panel is not None:
            set_busy = getattr(self.active_creation_panel, "set_busy", None)
            if callable(set_busy):
                set_busy(busy)
            else:
                self.active_creation_panel.setEnabled(not busy)
        for action in (self.action_new_project, self.action_settings):
            action.setEnabled(not busy)
        if not busy:
            self._update_input_tabs_state()
        else:
            self.button_create_project.setEnabled(False)
        self.window.statusBar().showMessage(tr("MainWindow", "対象を解析しています…") if busy else "")

    def _on_project_imported(self, imported: ImportedTranslation) -> None:
        if self._close_after_import:
            return
        for key, value in self._import_metadata.items():
            setattr(imported.project, key, value)
        adapter = self.active_adapter
        suggestions = getattr(adapter, "suggestions", {})
        if suggestions and adapter is not None:
            text = "\n".join(f"{key}: {value}" for key, value in suggestions.items())
            if QMessageBox.question(self.window, "解析結果の提案", text + "\nこの設定を適用しますか？") == QMessageBox.StandardButton.Yes:
                imported.project.name = suggestions.get("project_name", imported.project.name)
                if suggestions.get("game_id"):
                    game = next(g for g in adapter.supported_games if g.id == suggestions["game_id"])
                    imported.project.game_id = game.id
        if not self._confirm_project_change():
            return
        self.load_import(imported)
        if adapter is not None and imported.project.game_id != self._import_metadata["game_id"]:
            self._refresh_source_rules()
        self.window.setWindowTitle(f"Autolingua Desktop - {imported.project.name}")

    def _on_import_failed(self, message: str) -> None:
        self._operation_progress(message)
        if not self._close_after_import:
            QMessageBox.warning(self.window, tr("MainWindow", "読み込みエラー"), message)

    def _on_import_finished(self) -> None:
        self.import_worker = None
        if self._pending_rules_refresh:
            QTimer.singleShot(0, self._refresh_source_rules)
        self._set_import_busy(False)
        if self._close_after_import:
            self._close_after_import = False
            self.window.close()

    def _set_initial_state(self) -> None:
        self.stack_main.setCurrentIndex(0)
        self.show_list_mode()
        self.action_stop_translation.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_filter.setCurrentText(tr("MainWindow", "未翻訳"))
        self._refresh_workspace_selection()
        self._set_workspace_controls()
        self.refresh_all()
        self._restore_window_layout()

    def _restore_window_layout(self) -> None:
        layout = load_window_layout()
        if layout.geometry:
            self.window.restoreGeometry(QByteArray.fromHex(layout.geometry.encode("ascii")))
        if layout.state:
            self.window.restoreState(QByteArray.fromHex(layout.state.encode("ascii")))
            self.chat_dock.restore_visibility()
        self._dock_tab_vertical_text = layout.dock_tab_vertical_text
        self._set_dock_tab_position(layout.dock_tab_position)
        if layout.splitter_main:
            self.splitter_main.restoreState(QByteArray.fromHex(layout.splitter_main.encode("ascii")))
        if layout.splitter_focus:
            self.splitter_focus.restoreState(QByteArray.fromHex(layout.splitter_focus.encode("ascii")))
        self.frame_files.setVisible(self.stack.currentWidget() is self.page_focus)
        self._ai_dock_workspace_visible = layout.ai_panel_visible
        self._on_main_page_changed(self.stack_main.currentIndex())

    def _save_window_layout(self) -> None:
        geom = self.window.saveGeometry().data().hex()
        state = self.window.saveState().data().hex()
        sp_main = self.splitter_main.saveState().data().hex()
        sp_focus = self.splitter_focus.saveState().data().hex()
        save_window_layout(WindowLayout(
            geometry=geom,
            state=state,
            splitter_main=sp_main,
            splitter_focus=sp_focus,
            ai_panel_visible=self._ai_dock_workspace_visible,
            dock_tab_position=self._dock_tab_position,
            dock_tab_vertical_text=self._dock_tab_vertical_text,
        ))

    def _set_dock_tab_position(
        self, position: DockTabPosition, vertical_text: bool | None = None,
    ) -> None:
        self._dock_tab_position = position
        if vertical_text is not None:
            self._dock_tab_vertical_text = vertical_text
        self.window.setDockOptions(
            self.window.dockOptions() & ~QMainWindow.DockOption.VerticalTabs
        )
        positions = {
            "top": QTabWidget.TabPosition.North,
            "bottom": QTabWidget.TabPosition.South,
            "left": QTabWidget.TabPosition.West,
            "right": QTabWidget.TabPosition.East,
        }
        self.window.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, positions[position])
        self._refresh_dock_tab_bars()

    def _refresh_dock_tab_bars(self) -> None:
        horizontal = not self._dock_tab_vertical_text
        # QMainWindow owns dock tab bars directly; nested page tabs are excluded.
        for bar in self.window.findChildren(
            QTabBar, "", Qt.FindChildOption.FindDirectChildrenOnly,
        ):
            style = self._dock_tab_styles.get(bar)
            if style is None:
                style = DockTabStyle(bar, horizontal)
                self._dock_tab_styles[bar] = style
                bar.destroyed.connect(lambda _object=None, tab=bar: self._dock_tab_styles.pop(tab, None))
                bar.setStyle(style)
                bar.installEventFilter(self)
            elif style.horizontal_text != horizontal:
                style.horizontal_text = horizontal
                # StyleChange invalidates QTabBar's cached tab sizes.
                QApplication.sendEvent(bar, QEvent(QEvent.Type.StyleChange))
                bar.updateGeometry()
                bar.update()

    def _show_dock_tab_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self.window)
        group = QActionGroup(menu)
        group.setExclusive(True)
        choices: dict[QAction, tuple[DockTabPosition, bool | None]] = {}
        top_bottom: tuple[tuple[DockTabPosition, str], ...] = (
            ("top", tr("MainWindow", "上")), ("bottom", tr("MainWindow", "下")),
        )
        sides: tuple[tuple[DockTabPosition, str], ...] = (
            ("left", tr("MainWindow", "左")), ("right", tr("MainWindow", "右")),
        )
        directions = ((True, tr("MainWindow", "縦表示")), (False, tr("MainWindow", "横表示")))
        for position, label in top_bottom:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._dock_tab_position == position)
            group.addAction(action)
            choices[action] = (position, None)
        for position, label in sides:
            side_menu = menu.addMenu(label)
            for vertical, text in directions:
                action = side_menu.addAction(text)
                action.setCheckable(True)
                action.setChecked(
                    self._dock_tab_position == position and self._dock_tab_vertical_text == vertical
                )
                group.addAction(action)
                choices[action] = (position, vertical)
        selected = menu.exec(global_pos)
        if selected is not None and selected in choices:
            position, vertical = choices[selected]
            self._set_dock_tab_position(position, vertical)
        menu.deleteLater()

    def _on_action_toggle_ai_panel_triggered(self, checked: bool) -> None:
        if self.stack_main.currentIndex() != 0:
            self._ai_dock_workspace_visible = checked
            self.dock_ai_settings.setVisible(checked)

    def _on_dock_ai_visibility_changed(self, visible: bool) -> None:
        if self.stack_main.currentIndex() != 0:
            self._ai_dock_workspace_visible = visible
            self.action_toggle_ai_panel.setChecked(visible)

    def _on_main_page_changed(self, index: int) -> None:
        if self.stack_main.currentWidget() is self.page_workspace and self.stack.currentWidget() is self.page_dashboard:
            self.overview_controller.enter()
        else:
            self.overview_controller.leave()
        self.chat_dock.set_workspace_page(index != 0)
        if index == 0:
            self.dock_ai_settings.setVisible(False)
            self.action_toggle_ai_panel.setEnabled(False)
        else:
            self.action_toggle_ai_panel.setEnabled(True)
            self.action_toggle_ai_panel.setChecked(self._ai_dock_workspace_visible)
            self.dock_ai_settings.setVisible(self._ai_dock_workspace_visible)

    def load_import(self, imported: ImportedTranslation, service: WorkspaceService | None = None) -> None:
        self.chat_dock.reset()
        self.translation_controller.reset_confirmations()
        self.output_path = None
        self.imported = imported
        self.project = imported.project
        self.workspace_service = service if service is not None else WorkspaceService(imported)
        self.operations.project_changed()
        self.active_workspace = self.workspace_service.workspaces.get(self.project.target_language)
        self.workspace_service.set_active_language(self.active_workspace.language_code if self.active_workspace else None)
        self.selected_glossary_id = self.active_workspace.glossary_id if self.active_workspace is not None else ""
        self.selected_tone_id = self.active_workspace.tone_id if self.active_workspace is not None else ""
        self._refresh_glossary_choices()
        self._refresh_tone_choices()
        self.units = list(self.workspace_service.units(self.active_workspace)) if self.active_workspace is not None else list(self.workspace_service.source_units())
        self.project_path = None
        self._saved_project = None
        self._refresh_project_notification()
        self.focus_controller.current_unit = self.units[0] if self.units else None
        self.focus_controller.focus_current_page = 1
        self.status_filter.setCurrentText(tr("MainWindow", "未翻訳"))
        self._sync_workspace_language_ui()
        self._refresh_workspace_selection()
        self._set_workspace_controls()
        self._configure_text_presentation()
        self.refresh_all()
        self.show_list_mode()
        self.stack_main.setCurrentIndex(1)
        self.window.statusBar().showMessage(
            tr("MainWindow", "{source_count}ソース / {unit_count}項目を読み込みました").format(
                source_count=len(self.project.sources),
                unit_count=len(self.units),
            ),
            5000,
        )
    def _sync_workspace_language_ui(self) -> None:
        adapter = self.plugins.parsers.get(self.project.adapter_id)
        game = None
        if adapter:
            for g in adapter.supported_games:
                if g.id == self.project.game_id:
                    game = g
                    break

        src_code = self.project.source_language or "en-US"
        src_label = src_code
        if src_code in self.workspace_service.languages:
            src_label = workspace_language_name(self.workspace_service, src_code)
        self.label_source_language_work.setText(src_label)

        with QSignalBlocker(self.combo_target_slot):
            self.combo_target_slot.clear()
            if game and game.slots:
                for slot in game.slots:
                    self.combo_target_slot.addItem(f"{slot.slot_id} ({slot.name})", slot.slot_id)
                workspace = self.active_workspace
                target_slot = workspace.output_slot if workspace is not None else self.project.source_slot
                idx = self.combo_target_slot.findData(target_slot)
                if idx < 0 and target_slot:
                    self.combo_target_slot.addItem(target_slot, target_slot)
                    idx = self.combo_target_slot.count() - 1
                self.combo_target_slot.setCurrentIndex(idx)
                self.combo_target_slot.setEnabled(workspace is not None)
            else:
                self.combo_target_slot.addItem(tr("MainWindow", "該当なし"), "")
                self.combo_target_slot.setEnabled(False)

    def _on_target_slot_changed(self) -> None:
        workspace = self.active_workspace
        if workspace is None:
            return
        data = self.combo_target_slot.currentData()
        val = str(data) if data else ""
        self.workspace_service.set_output_slot(workspace, val)

    def _open_workspace_languages(self) -> None:
        WorkspaceLanguageDialog(self.workspace_service, self._workspaces_changed, self.window).exec()

    def _workspaces_changed(self, code: str | None) -> None:
        if code is not None:
            self._select_workspace(code)
        elif self.active_workspace is not None and self.workspace_service.workspaces.get(
                self.active_workspace.language_code) is not self.active_workspace:
            self._select_workspace(None)
        self._refresh_workspace_selection()
        self.overview_controller.invalidate()

    def _refresh_workspace_selection(self) -> None:
        with QSignalBlocker(self.combo_target_language):
            self.combo_target_language.clear()
            self.combo_target_language.addItem(tr("MainWindow", "未選択"), "")
            for code in self.workspace_service.workspaces:
                name = workspace_language_name(self.workspace_service, code)
                self.combo_target_language.addItem(f"{name} ({code})", code)
            code = self.active_workspace.language_code if self.active_workspace is not None else ""
            self.combo_target_language.setCurrentIndex(self.combo_target_language.findData(code))

    def _on_workspace_selected(self) -> None:
        code = self.combo_target_language.currentData()
        self._select_workspace(str(code) if code else None)

    def _select_workspace(self, code: str | None, *, preserve_chat: bool = False) -> None:
        keep_overview = self.stack.currentWidget() is self.page_dashboard
        if not preserve_chat:
            self.chat_dock.context_changed()
        workspace = self.workspace_service.workspaces.get(code) if code is not None else None
        self.active_workspace = workspace
        if workspace is not None:
            self.selected_glossary_id, self.selected_tone_id = workspace.glossary_id, workspace.tone_id
            self._refresh_glossary_choices()
            self._refresh_tone_choices()
        self.workspace_service.set_active_language(workspace.language_code if workspace is not None else None)
        self.units = list(self.workspace_service.units(workspace)) if workspace is not None else list(self.workspace_service.source_units())
        self._sync_workspace_language_ui()
        self.focus_controller.current_unit = None
        self.focus_controller.focus_current_page = 1
        with QSignalBlocker(self.search), QSignalBlocker(self.status_filter):
            self.search.clear()
            self.status_filter.setCurrentText(tr("MainWindow", "未翻訳"))
        self._set_workspace_controls()
        self.apply_filters()
        if not keep_overview:
            self.show_list_mode()

    def _set_workspace_controls(self) -> None:
        enabled = self.active_workspace is not None
        self.edit_translation.setReadOnly(not enabled)
        for widget in (self.button_ai_translate, self.button_ai_translate_all_models,
                       self.button_copy_source, self.button_save_split, self.button_revert):
            widget.setEnabled(enabled)
        for action in (self.action_translate_all, self.action_translate_selected,
                       self.action_translate_untranslated):
            action.setEnabled(enabled)
        self.translation_controller._update_translation_button_state()
        self._update_status_bar_counts()

    def _workspace_is_alive(self, workspace: Workspace) -> bool:
        return self.workspace_service.workspaces.get(workspace.language_code) is workspace

    def refresh_all(self) -> None:
        self.apply_filters()

    def _replace_matches(self, *, all_matches: bool) -> None:
        workspace = self.active_workspace
        if workspace is None or self._search_error or not self._text_search.can_replace:
            return
        current = self.focus_controller.current_unit
        candidates = self.filtered_units if all_matches else (
            [current] if current is not None and current in self.filtered_units else []
        )
        units = [unit for unit in candidates if isinstance(unit, WorkspaceUnit)]
        try:
            changed, count = self.workspace_service.replace_translation_drafts(
                workspace, units, self._text_search, self.replace_text.text(), all_matches=all_matches,
            )
        except (re.error, IndexError) as error:
            self.label_search_result.setText(tr("MainWindow", "置換式が無効です：{error}").format(error=error))
            return
        for unit in changed:
            self.translation_controller.cancel_deferred_confirmation(unit)
            self.translation_controller.remember_confirmation(unit)
        self.apply_filters()
        self.label_search_result.setText(
            self.label_search_result.text() + " | "
            + tr("MainWindow", "{count}箇所を置換（{units}件）").format(count=count, units=len(changed))
        )

    def _update_search_controls(self) -> None:
        if self._search_error:
            self.label_search_result.setText(
                tr("MainWindow", "検索エラー：{error}").format(error=self._search_error)
            )
        else:
            replace_count = sum(self._text_search.count(unit.target_text) for unit in self.filtered_units
                                if isinstance(unit, WorkspaceUnit) and not unit.locked and not unit.hidden
                                and not unit.record.translating)
            self.label_search_result.setText(
                tr("MainWindow", "一致：{units}件 / 置換可能：{count}箇所").format(
                    units=len(self.filtered_units), count=replace_count,
                )
            )
        enabled = self.active_workspace is not None and self._text_search.can_replace and not self._search_error
        self.button_replace.setEnabled(enabled)
        self.button_replace_all.setEnabled(enabled)

    def apply_filters(self) -> None:
        self._search_error = ""
        try:
            self._text_search = TextSearch(
                self.search.text(), case_sensitive=self.search_case.isChecked(),
                whole_word=self.search_word.isChecked(), regex=self.search_regex.isChecked(),
            )
        except SearchSyntaxError as error:
            self._search_error = str(error)
        selected_status = self.status_filter.currentText()

        self.filtered_units = [
            unit
            for unit in self.units
            if not self._search_error and unit.id not in self.imported.excluded_unit_ids
            and (selected_status == tr("MainWindow", "すべて") or self.unit_matches_status(unit, selected_status))
            and self._text_search.matches(
                unit, file_name=self.source_name_for_unit(unit), status=self.status_text(unit),
            )
        ]
        if self.focus_controller.current_unit in self.filtered_units:
            idx = self.filtered_units.index(self.focus_controller.current_unit)
            self.focus_controller.focus_current_page = (idx // self.focus_controller.focus_page_size) + 1
        else:
            self.focus_controller.focus_current_page = 1
        if self.filtered_units and self.focus_controller.current_unit not in self.filtered_units:
            self.focus_controller.current_unit = self.filtered_units[0]
        elif not self.filtered_units:
            self.focus_controller.current_unit = None
        self.table_controller.refresh_table()
        self.focus_controller.refresh_focus_unit_list()
        self.focus_controller.refresh_focus()
        self._update_status_bar_counts()
        self.translation_controller._update_translation_button_state()

    def _dispose_highlighters(self) -> None:
        # Removing formats emits textChanged too; it must never edit the new unit.
        with QSignalBlocker(self.edit_source), QSignalBlocker(self.edit_translation):
            for highlighter in (self.source_highlighter, self.translation_highlighter):
                if highlighter is not None:
                    highlighter.setDocument(None)
                    highlighter.deleteLater()
        self.source_highlighter = None
        self.translation_highlighter = None

    def _configure_text_presentation(self) -> None:
        self._dispose_highlighters()
        self._text_presentation = None
        try:
            self._text_presentation = self.plugins.get_text_presentation(
                self.project.adapter_id, self.project.game_id)
            factory = self.plugins.get_highlighter_factory(self.project.adapter_id)
            if factory is not None:
                for editor, attribute in ((self.edit_source, "source_highlighter"),
                                          (self.edit_translation, "translation_highlighter")):
                    document = editor.document()
                    if document is None:
                        raise RuntimeError("Text editor has no document")
                    highlighter = factory(self.project.game_id, document,
                                          lambda: self.highlight_translation_tags,
                                          lambda: self.apply_color_tags)
                    if highlighter is not None and not isinstance(highlighter, QSyntaxHighlighter):
                        raise TypeError("Invalid plugin highlighter")
                    if attribute == "source_highlighter":
                        self.source_highlighter = highlighter
                    else:
                        self.translation_highlighter = highlighter
        except Exception as exc:
            self._dispose_highlighters()
            self._text_presentation = None
            self.plugins.report_error(self.project.adapter_id, exc)
        presentation = self._text_presentation
        has_highlighter = self.source_highlighter is not None and self.translation_highlighter is not None
        self.action_render_newlines.setEnabled(presentation is not None and presentation.newline_codec is not None)
        self.action_highlight_tags.setEnabled(presentation is not None and presentation.highlight_tags and has_highlighter)
        self.action_apply_color_tags.setEnabled(presentation is not None and presentation.apply_colors and has_highlighter)
        has_settings = presentation is not None and presentation.settings_page_id is not None
        self.action_open_color_settings.setVisible(has_settings)
        self.display_settings_separator.setVisible(has_settings)
        self.action_open_color_settings.setText(presentation.settings_label if presentation is not None else "")

    def _on_plugin_display_changed(self, plugin_id: str) -> None:
        self.chat_dock.refresh_icons(plugin_id)
        if plugin_id == self.project.adapter_id:
            self._configure_text_presentation()
            self.focus_controller.refresh_focus()
            self.table_controller.refresh_table()

    def _chat_icon(self, provider_id: str) -> QIcon:
        contribution = self.plugins.ui_contributions.get(provider_id)
        if contribution is not None and contribution.chat_icon is not None:
            icon = contribution.chat_icon()
            if not icon.isNull():
                return icon
        return self.icon_manager.get_icon("robot-head")

    def _open_game_color_settings(self) -> None:
        presentation = self._text_presentation
        if presentation is not None and presentation.settings_page_id is not None:
            self.open_settings(presentation.settings_page_id)

    def _expand_display_text(self, text: str) -> str:
        presentation = self._text_presentation
        if self.render_literal_newlines and presentation is not None and presentation.newline_codec is not None:
            return presentation.newline_codec.expand(text)
        return text

    def _collapse_display_text(self, text: str) -> str:
        presentation = self._text_presentation
        if self.render_literal_newlines and presentation is not None and presentation.newline_codec is not None:
            return presentation.newline_codec.collapse(text)
        return text

    def _update_status_bar_counts(self) -> None:
        self.overview_controller.invalidate()
        self._update_search_controls()
        if self.status_count_label is None:
            return
        if not self.units:
            self.status_count_label.setText("")
            return

        total_count = len(self.units)
        filtered_count = len(self.filtered_units)
        selected_count = len(self.table_controller._get_selected_rows())

        if filtered_count != total_count:
            count_str = f"{filtered_count:,} / {total_count:,} 件"
        else:
            count_str = f"{total_count:,} 件"

        if selected_count > 0:
            text = f"選択中: {selected_count:,} 件 | {count_str}"
        else:
            text = count_str

        pending_count = sum(is_pending_translation(unit) for unit in self.units)
        self.status_count_label.setText(
            text + " | " + tr("MainWindow", "未確定 {count}件").format(count=pending_count)
        )

    def ai_translate_current_unit(self) -> None:
        unit = self.focus_controller.current_unit
        if unit is not None:
            self.translation_controller._translate_single_unit(unit)

    def _get_active_models_list(self) -> list[tuple[str, str, str, str]]:
        return self.provider_registry.get_active_models(self.ai_settings.models)

    def _open_multi_model_dialog(self, unit: TranslationUnit, row: int = -1) -> None:
        workspace = self.active_workspace
        if workspace is None:
            return
        active_models = self._get_active_models_list()
        if not active_models:
            QMessageBox.warning(
                self.window,
                tr("MainWindow", "AI設定"),
                tr("MainWindow", "利用可能な登録モデルがありません。設定画面でモデルの設定を確認してください。"),
            )
            return

        source_text = unit.source_text.strip()
        if not source_text:
            return

        source_lang = self.project.source_language or "en"
        target_lang = self.project.target_language
        high_model = self.ai_settings.high_model
        default_model = high_model.model_id if high_model is not None else ""

        selected_tone = deepcopy(next((tone for tone in self.tone_choices if tone.id == self.selected_tone_id), None))
        tone_items = tuple(deepcopy(tone) for tone in self.tone_choices if isinstance(tone, ToneItem))
        try:
            applied_tone = self.translation_controller.service.resolved_tone(unit, selected_tone, tone_items)
            peers = self.translation_controller.service.matching_tone_peers(
                self.workspace_service.exact_peers(workspace, unit.id), applied_tone, selected_tone, tone_items)
        except ValueError as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "口調"), str(exc))
            return
        eligible_ids = {peer.id for peer in peers}

        dialog = MultiModelTranslationDialog(
            source_text=unit.source_text,
            active_models=active_models,
            providers=self.plugins.providers,
            api_keys_map=self.ai_settings.api_keys,
            default_model_id=default_model,
            default_provider_id=high_model.provider_id if high_model is not None else self.ai_settings.provider_id,
            ai_client=self.ai_client,
            source_lang=source_lang,
            target_lang=target_lang,
            source_language_name=workspace_language_name(self.workspace_service, source_lang)
                if source_lang in self.workspace_service.languages else "",
            target_language_name=workspace_language_name(self.workspace_service, target_lang),
            tone=applied_tone.prompt if applied_tone is not None else None,
            parent=self.window,
        )

        def on_adopted(adopted_text: str) -> None:
            if not self._workspace_is_alive(workspace):
                return
            unit.target_text = adopted_text
            unit.state = UnitState.AI_TRANSLATED
            workspace.records[unit.id].tone = applied_tone
            workspace.records[unit.id].pending_confirmation = None
            self.translation_controller._unit_translated(workspace, unit, False, eligible_ids=eligible_ids)

        dialog.translation_adopted.connect(on_adopted)
        dialog.exec()

    def ai_translate_all_models_current_unit(self) -> None:
        if self.focus_controller.current_unit is None:
            return
        try:
            row = self.filtered_units.index(self.focus_controller.current_unit)
        except ValueError:
            row = -1
        self._open_multi_model_dialog(self.focus_controller.current_unit, row)

    def _on_table_action_all_models_clicked(self, row: int) -> None:
        if not (0 <= row < len(self.filtered_units)):
            return
        unit = self.filtered_units[row]
        self._open_multi_model_dialog(unit, row)

    def _show_translation_mode(self, page: QWidget, button: QToolButton) -> None:
        if page is not self.page_dashboard:
            self.overview_controller.leave()
        self.stack.setCurrentWidget(page)
        button.setChecked(True)
        self.action_dashboard_mode.setChecked(page is self.page_dashboard)
        self.action_list_mode.setChecked(page is self.page_list)
        self.action_focus_mode.setChecked(page is self.page_focus)
        self.stack_workspace_controls.setCurrentWidget(
            self.page_controls_dashboard if page is self.page_dashboard else self.page_controls_translation)
        self.stack_workspace_controls.setVisible(page is not self.page_dashboard)
        focus = page is self.page_focus
        self.frame_files.setVisible(focus)
        self._animate_segment_indicator(button)
        self.chat_dock.context_changed()

    def show_dashboard_mode(self) -> None:
        self._show_translation_mode(self.page_dashboard, self.button_dashboard_mode)
        self.overview_controller.enter()

    def show_list_mode(self) -> None:
        was_focus = self.stack.currentWidget() is self.page_focus
        self._show_translation_mode(self.page_list, self.button_list_mode)
        if was_focus:
            self.apply_filters()

    def _animate_segment_indicator(self, target_btn: QToolButton) -> None:
        geom = target_btn.geometry()
        if geom.width() <= 0:
            return
        if not self.segment_indicator.isVisible():
            self.segment_indicator.setGeometry(geom)
            self.segment_indicator.show()
            self.segment_indicator.lower()
            return
        self.segment_anim.stop()
        self.segment_anim.setStartValue(self.segment_indicator.geometry())
        self.segment_anim.setEndValue(geom)
        self.segment_anim.start()

    def _sync_segment_indicator_pos(self, animate: bool = True) -> None:
        target_btn = (self.button_dashboard_mode if self.button_dashboard_mode.isChecked() else
                      self.button_focus_mode if self.button_focus_mode.isChecked() else self.button_list_mode)
        geom = target_btn.geometry()
        if geom.width() <= 0:
            return
        if animate and self.segment_indicator.isVisible():
            self._animate_segment_indicator(target_btn)
        else:
            self.segment_anim.stop()
            self.segment_indicator.setGeometry(geom)
            self.segment_indicator.show()
            self.segment_indicator.lower()

    def _save_display_flags(self) -> None:
        save_ui_display_flags(
            self.render_literal_newlines,
            self.highlight_translation_tags,
            self.apply_color_tags,
        )

    def _on_toggle_render_newlines(self, enabled: bool) -> None:
        self.render_literal_newlines = enabled
        self._save_display_flags()
        self.focus_controller.refresh_focus(sync_list=False)
        self.table_controller.refresh_table()

    def _on_toggle_highlight_tags(self, enabled: bool) -> None:
        self.highlight_translation_tags = enabled
        self._save_display_flags()
        if self.source_highlighter is not None:
            self.source_highlighter.rehighlight()
        if self.translation_highlighter is not None:
            self.translation_highlighter.rehighlight()

    def _on_toggle_apply_color_tags(self, enabled: bool) -> None:
        self.apply_color_tags = enabled
        self._save_display_flags()
        if self.source_highlighter is not None:
            self.source_highlighter.rehighlight()
        if self.translation_highlighter is not None:
            self.translation_highlighter.rehighlight()

    def _open_display_settings_menu(self) -> None:
        pos = self.button_display_settings.mapToGlobal(QPoint(0, self.button_display_settings.height()))
        self.display_settings_menu.exec(pos)

    def show_focus_mode(self) -> None:
        was_focus = self.stack.currentWidget() is self.page_focus
        if self.focus_controller.current_unit is None and self.filtered_units:
            self.focus_controller.current_unit = self.filtered_units[0]
        self._show_translation_mode(self.page_focus, self.button_focus_mode)
        self.focus_controller._ensure_focus_sidebar_minimum_width()
        if not was_focus:
            self.apply_filters()
        else:
            self.focus_controller.refresh_focus()

    def open_problems_dialog(self) -> None:
        controller = SimpleDialogController("dialogs/ProblemsDialog.ui", self.window)
        dialog = controller.dialog
        table = require_child(dialog, QTableWidget, "tableProblems")
        button_close = require_child(dialog, QPushButton, "buttonClose")
        button_go_to = require_child(dialog, QPushButton, "buttonGoTo")
        problems: list[tuple[str, str, str, str]] = []
        for source in self.project.sources:
            for issue in source.issues:
                problems.append((issue.kind, source.name, issue.message, source.name))
        for unit in self.units:
            for issue in unit.issues:
                source_name = self.source_name_for_unit(unit)
                problems.append((issue.kind, unit.label, issue.message, source_name))

        table.setRowCount(len(problems))
        for row, values in enumerate(problems):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        button_close.clicked.connect(dialog.close)
        button_go_to.clicked.connect(lambda: show_not_implemented(dialog, tr("MainWindow", "該当箇所へ移動")))
        dialog.exec()

    def status_text(self, unit: TranslationUnit) -> str:
        previous = self._confirmed_status_text(unit, show_issues=not is_pending_translation(unit))
        if is_pending_translation(unit):
            return tr("MainWindow", "未確定（前回：{state}）").format(state=previous)
        return previous

    def _confirmed_status_text(self, unit: TranslationUnit, *, show_issues: bool = True) -> str:
        if unit.state == UnitState.REVIEW_ISSUES:
            return tr("MainWindow", "校閲指摘あり")
        if unit.state == UnitState.TRANSLATION_ERROR:
            return tr("MainWindow", "翻訳エラー")
        if unit.state == UnitState.REVIEW_ERROR:
            return tr("MainWindow", "校閲エラー")
        if show_issues and unit.source_changed:
            return tr("MainWindow", "原文更新・要確認")
        if unit.hidden or unit.state == UnitState.HIDDEN:
            return tr("MainWindow", "非表示")
        if unit.locked or unit.state == UnitState.LOCKED:
            return tr("MainWindow", "ロック")
        if show_issues and unit.issues:
            return tr("MainWindow", "問題あり")
        if unit.state == UnitState.DOUBTFUL:
            return tr("MainWindow", "疑問あり")
        if unit.state == UnitState.AI_REVIEWED:
            return tr("MainWindow", "AIによる校閲")
        if unit.state == UnitState.HUMAN_REVIEWED:
            return tr("MainWindow", "人間による校閲")
        if unit.state == UnitState.AI_TRANSLATED:
            return tr("MainWindow", "AIによる翻訳")
        if unit.state == UnitState.HUMAN_TRANSLATED:
            return tr("MainWindow", "人間による翻訳")
        return tr("MainWindow", "未翻訳")

    def unit_matches_status(self, unit: TranslationUnit, status: str) -> bool:
        matcher = self.status_matchers_by_label().get(status)
        return matcher(unit) if matcher is not None else False

    def status_matchers_by_label(self) -> dict[str, Callable[[TranslationUnit], bool]]:
        return {
            tr("MainWindow", "原文更新・要確認"): STATUS_MATCHERS["source_changed"],
            tr("MainWindow", "未確定"): STATUS_MATCHERS["pending"],
            tr("MainWindow", "非表示"): STATUS_MATCHERS["hidden"],
            tr("MainWindow", "ロック"): STATUS_MATCHERS["locked"],
            tr("MainWindow", "問題あり"): STATUS_MATCHERS["has_issues"],
            tr("MainWindow", "疑問あり"): STATUS_MATCHERS["doubtful"],
            tr("MainWindow", "翻訳エラー"): STATUS_MATCHERS["translation_error"],
            tr("MainWindow", "校閲エラー"): STATUS_MATCHERS["review_error"],
            tr("MainWindow", "校閲指摘あり"): STATUS_MATCHERS["review_issues"],
            tr("MainWindow", "AIによる校閲"): STATUS_MATCHERS["ai_reviewed"],
            tr("MainWindow", "人間による校閲"): STATUS_MATCHERS["human_reviewed"],
            tr("MainWindow", "AIによる翻訳"): STATUS_MATCHERS["ai_translated"],
            tr("MainWindow", "人間による翻訳"): STATUS_MATCHERS["human_translated"],
            tr("MainWindow", "未翻訳"): STATUS_MATCHERS["untranslated"],
        }

    def source_name_for_unit(self, unit: TranslationUnit) -> str:
        ref = self.imported.source_refs.get(unit.id)
        if ref is None:
            return ""
        for source in self.project.sources:
            if source.id == ref.source_id:
                return source.name
        return ref.source_id
