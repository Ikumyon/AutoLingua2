from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, Qt, QSignalBlocker, QTimer, QLocale
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autolingua2.adapters.base import PluginAdapter, ImportedTranslation
from autolingua2.adapters.pairing import apply_existing_translation
from autolingua2.adapters.registry import (
    PLUGINS_DIR,
    adapter_for,
    adapter_by_id,
    plugin_errors,
    get_all_adapters,
    load_file,
    supported_file_filter,
)
from autolingua2.infrastructure.platform import current_platform, log_directory
from autolingua2.infrastructure.platform.base import PlatformDriver
from autolingua2.infrastructure.operations import OperationCancelled
from autolingua2.ir import Issue, TranslationProject, TranslationSource, TranslationUnit, UnitState
from autolingua2.services.filter_rules import AdapterFilterConfig, get_default_filter_config, should_hide_unit
from autolingua2.services.ai_providers import discover_providers
from autolingua2.services.settings_store import (
    AiSettings,
    ColumnLayout,
    WindowLayout,
    load_adapter_filter_rules,
    load_ai_settings,
    load_theme_settings,
    load_translation_table_columns,
    load_window_layout,
    save_ai_settings,
    save_translation_table_columns,
    save_window_layout,
)
from autolingua2.services.translation_memory_store import TranslationMemoryStore
from autolingua2.services.project_io import plan_output, write_output
from autolingua2.ui.dialogs import (
    SettingsDialogController,
    SimpleDialogController,
    load_ui,
    require_child,
    show_not_implemented,
)
from autolingua2.ui.icons import IconManager
from autolingua2.ui.i18n import current_ui_language, language_events, tr
from autolingua2.ui.import_worker import ImportWorker
from autolingua2.ui.operation_worker import OperationWorker
from autolingua2.ui.models.translation_table_model import TranslationTableColumn, default_translation_table_columns
from autolingua2.ui.translation_worker import TranslationWorker


STATUS_MATCHERS: dict[str, Callable[[TranslationUnit], bool]] = {
    "hidden": lambda unit: unit.hidden,
    "locked": lambda unit: unit.locked,
    "has_issues": lambda unit: bool(unit.issues),
    "doubtful": lambda unit: unit.state == UnitState.DOUBTFUL,
    "translated": lambda unit: unit.state == UnitState.TRANSLATED,
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

    @property
    def parent_widget(self) -> QWidget:
        return self.controller.window

    def add_target_path(self, path: Path) -> None:
        self._check()
        self.controller.add_target_path(path)

    def remove_target_path(self, path: Path) -> None:
        self._check()
        self.controller.remove_target_path_by_path(path)

    def set_project_name(self, name: str) -> None:
        self._check()
        self.controller.edit_project_name.setText(name)

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

    def get_icon(self, name: str) -> Any:
        return self.controller.icon_manager.get_icon(name)

    def cancel_operation(self) -> None:
        if not self.active:
            return
        if self.controller.import_worker:
            self.controller.import_worker.requestInterruption()
        if self.controller.io_worker:
            self.controller.io_worker.requestInterruption()

    @property
    def current_ui_language(self) -> str:
        return current_ui_language()



class MainWindowController(QObject):
    def __init__(self, platform_driver: PlatformDriver = current_platform) -> None:
        super().__init__()
        self.platform = platform_driver
        self.io_worker: OperationWorker | None = None
        self._close_after_io = False
        self._restart_target: bool | None = None
        self._restart_started = False
        self._saved_targets: list[tuple[str, str]] = []
        widget = load_ui("MainWindow.ui")
        if not isinstance(widget, QMainWindow):
            raise TypeError("MainWindow.ui は QMainWindow ではありません")

        self.window = widget
        self.icon_manager = IconManager()
        _, icon_theme = load_theme_settings()
        self.icon_manager.set_current_iconset(icon_theme)
        self.imported = ImportedTranslation(project=TranslationProject())
        self.existing_translation: ImportedTranslation | None = None
        self.output_path: Path | None = None
        self.provider_registry = discover_providers()
        ai_settings = load_ai_settings()
        self.ai_provider_id = ai_settings.provider_id
        self.ai_models = ai_settings.models
        self.ai_selected_models = ai_settings.selected_models
        self.ai_concurrency = ai_settings.concurrency
        self.ai_api_keys = ai_settings.api_keys
        self.translation_worker: TranslationWorker | None = None
        self._pending_human_memory: dict[str, str] = {}
        self._translation_methods: dict[str, str] = {}
        self._close_after_translation = False
        self.project = self.imported.project
        self.units: list[TranslationUnit] = []
        self.filtered_units: list[TranslationUnit] = []
        self.current_unit: TranslationUnit | None = None
        self.columns = default_translation_table_columns(self.status_text, lambda unit: unit.context)
        self.columns_by_id: dict[str, TranslationTableColumn] = {column.id: column for column in self.columns}
        self.column_layout = load_translation_table_columns(
            [column.id for column in self.columns],
            {column.id for column in self.columns if not column.default_visible},
        )
        self._syncing_header_order = False
        self._dragged_header_logical_index: int | None = None
        self._updating_focus = False

        self.selected_icon_path: Path | None = None
        self.target_paths: list[Path] = []
        self.target_item_widgets: dict[Path, tuple[QLabel, QListWidgetItem]] = {}
        self.target_files: list[Path] = []
        self.active_adapter: PluginAdapter | None = None
        self.active_creation_panel: QWidget | None = None
        self.creation_context: MainWindowCreationContext | None = None
        self.import_worker: ImportWorker | None = None
        self._changing_game = False
        self._creation_valid = False
        self._panel_valid = False
        self._close_after_import = False

        self._setup_widgets()
        self._connect_actions()
        self._set_initial_state()
        self.window.installEventFilter(self)
        language_events().changed.connect(self._on_ui_language_changed)
        if plugin_errors():
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self.window, "プラグイン読み込みエラー", "\n".join(plugin_errors())))

    def show(self) -> None:
        self.window.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.window and isinstance(event, QCloseEvent):
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
            if self.translation_worker is not None:
                event.ignore()
                self._close_after_translation = True
                self.stop_translation()
                return True
            if self._restart_target is not None:
                if self._target_snapshot() != self._saved_targets:
                    answer = QMessageBox.question(self.window, "再起動", "未保存の訳文を保存しますか？",
                        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel)
                    if answer == QMessageBox.StandardButton.Cancel:
                        self._restart_target = None
                        event.ignore()
                        return True
                    if answer == QMessageBox.StandardButton.Save:
                        event.ignore()
                        self.save_translation()
                        return True
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
            if self.creation_context:
                self.creation_context.active = False
            if self.active_adapter and self.active_creation_panel:
                try:
                    self.active_adapter.dispose_creation_panel(self.active_creation_panel)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Panel disposal failed")

        # プロジェクト作成画面のドラッグ＆ドロップ処理
        frame_icon = getattr(self, "frame_icon_drop", None)
        frame_target = getattr(self, "frame_target_drop", None)
        if watched in {frame_icon, frame_target}:
            if isinstance(event, QDragEnterEvent):
                if event.mimeData().hasUrls():
                    self._set_drop_hover(watched, True)
                    event.acceptProposedAction()
                    return True
            elif isinstance(event, QDragMoveEvent):
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif isinstance(event, QDragLeaveEvent):
                self._set_drop_hover(watched, False)
                return True
            elif isinstance(event, QDropEvent):
                self._set_drop_hover(watched, False)
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    urls = event.mimeData().urls()
                    paths = [Path(u.toLocalFile()) for u in urls if u.toLocalFile()]

                    # 左列アイコン枠: 画像ファイルのみを受け付け
                    if watched is frame_icon:
                        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".bmp"}
                        img_files = [p for p in paths if p.is_file() and p.suffix.lower() in image_exts]
                        if img_files:
                            self.set_project_icon(img_files[0])
                        elif paths:
                            self.set_project_icon(paths[0])
                        return True

                    # 中央スロット枠: アクティブなプラグインにドロップイベントを委譲
                    if watched is frame_target:
                        adapter = self.active_adapter
                        context = self.creation_context
                        if (self.import_worker is not None or not self._creation_valid
                                or adapter is None or context is None):
                            return True
                        try:
                            remaining = adapter.on_paths_dropped(paths, context)
                            if not isinstance(remaining, list) or any(p not in paths for p in remaining):
                                raise ValueError("Invalid unhandled drop paths")
                            for p in remaining:
                                self.add_target_path(p)
                        except Exception as exc:
                            QMessageBox.warning(self.window, "プラグインエラー", str(exc))
                        return True

        header = getattr(self, "table_header", None)
        header_viewport = getattr(self, "table_header_viewport", None)
        if header is not None and (watched is header or watched is header_viewport):
            if isinstance(event, QMouseEvent):
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    self._dragged_header_logical_index = header.logicalIndexAt(event.position().toPoint())
                elif event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                    if self._dragged_header_logical_index is not None and self._dragged_header_logical_index >= 0:
                        self.show_header_drop_indicator(event.position().toPoint())
            if event.type() in {QEvent.Type.MouseButtonRelease, QEvent.Type.Leave}:
                self.hide_header_drop_indicator()
        return False

    def _set_drop_hover(self, target: QObject, is_hover: bool) -> None:
        if isinstance(target, QWidget):
            target.setProperty("dragOver", is_hover)
            target.style().unpolish(target)
            target.style().polish(target)

    def _setup_widgets(self) -> None:
        self.table = require_child(self.window, QTableWidget, "tableTranslations")
        self.tree_files = require_child(self.window, QTreeWidget, "treeFiles")
        self.search = require_child(self.window, QLineEdit, "editSearch")
        self.status_filter = require_child(self.window, QComboBox, "comboStatusFilter")
        self.stack = require_child(self.window, QStackedWidget, "stackTranslationView")
        self.button_list_mode = require_child(self.window, QToolButton, "buttonListMode")
        self.button_focus_mode = require_child(self.window, QToolButton, "buttonFocusMode")
        self.progress = require_child(self.window, QProgressBar, "progressTranslation")
        self.frame_files = require_child(self.window, QFrame, "frameFiles")
        self.splitter_main = require_child(self.window, QSplitter, "splitterMain")
        self.splitter_focus = require_child(self.window, QSplitter, "splitterFocusTexts")
        self.button_previous = require_child(self.window, QPushButton, "buttonPrevious")
        self.button_next = require_child(self.window, QPushButton, "buttonNext")
        self.button_revert = require_child(self.window, QPushButton, "buttonRevert")
        self.button_save_and_next = require_child(self.window, QPushButton, "buttonSaveAndNext")

        self.edit_key = require_child(self.window, QLineEdit, "editKey")
        self.edit_source = require_child(self.window, QPlainTextEdit, "editSource")
        self.edit_translation = require_child(self.window, QPlainTextEdit, "editTranslation")
        self.edit_context = require_child(self.window, QPlainTextEdit, "editContext")
        self.label_position = require_child(self.window, QLabel, "labelPosition")
        self.check_translated = require_child(self.window, QCheckBox, "checkTranslated")
        self.check_doubtful = require_child(self.window, QCheckBox, "checkDoubtful")
        self.check_hidden = require_child(self.window, QCheckBox, "checkHidden")
        self.check_locked = require_child(self.window, QCheckBox, "checkLocked")

        self.action_open_file = require_child(self.window, QAction, "actionOpenFile")
        self.action_open_folder = require_child(self.window, QAction, "actionOpenFolder")
        self.action_open_translation_file = require_child(self.window, QAction, "actionOpenTranslationFile")
        self.action_save = require_child(self.window, QAction, "actionSave")
        self.action_save_as = require_child(self.window, QAction, "actionSaveAs")
        self.action_exit = require_child(self.window, QAction, "actionExit")
        self.action_start_translation = require_child(self.window, QAction, "actionStartTranslation")
        self.action_translate_selected = require_child(self.window, QAction, "actionTranslateSelected")
        self.action_translate_untranslated = require_child(self.window, QAction, "actionTranslateUntranslated")
        self.action_pause_translation = require_child(self.window, QAction, "actionPauseTranslation")
        self.action_stop_translation = require_child(self.window, QAction, "actionStopTranslation")
        self.action_settings = require_child(self.window, QAction, "actionSettings")
        self.action_problems = require_child(self.window, QAction, "actionProblems")
        self.action_about = require_child(self.window, QAction, "actionAbout")
        self.action_list_mode = require_child(self.window, QAction, "actionListMode")
        self.action_focus_mode = require_child(self.window, QAction, "actionFocusMode")
        self.action_toggle_file_sidebar = require_child(self.window, QAction, "actionToggleFileSidebar")
        toolbar = require_child(self.window, QToolBar, "mainToolBar")
        toolbar.insertSeparator(self.action_start_translation)
        toolbar.insertWidget(self.action_start_translation, QLabel("Provider", toolbar))
        self.combo_ai_provider = QComboBox(toolbar)
        self.combo_ai_provider.setObjectName("comboAiProvider")
        self.combo_ai_provider.setMinimumWidth(120)
        toolbar.insertWidget(self.action_start_translation, self.combo_ai_provider)
        toolbar.insertWidget(self.action_start_translation, QLabel("モデル", toolbar))
        self.combo_ai_model = QComboBox(toolbar)
        self.combo_ai_model.setObjectName("comboAiModel")
        self.combo_ai_model.setMinimumWidth(180)
        toolbar.insertWidget(self.action_start_translation, self.combo_ai_model)
        toolbar.insertSeparator(self.action_start_translation)
        self._refresh_ai_choices()

        header = self.table.horizontalHeader()
        self.table_header = header
        self.table_header_viewport = header.viewport()
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.open_table_header_menu)
        header.sectionMoved.connect(self.handle_table_section_moved)
        header.installEventFilter(self)
        header.viewport().installEventFilter(self)
        self.header_drop_indicator = QFrame(header)
        self.header_drop_indicator.setObjectName("headerDropIndicator")
        self.header_drop_indicator.setFixedWidth(3)
        self.header_drop_indicator.setStyleSheet("QFrame#headerDropIndicator { background: #2d8cff; }")
        self.header_drop_indicator.hide()
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(True)

        self.window.statusBar().addPermanentWidget(self.progress)

        # プロジェクト作成画面のウィジェット
        self.stack_main = require_child(self.window, QStackedWidget, "stackMain")
        self.frame_icon_drop = require_child(self.window, QFrame, "frameIconDrop")
        self.label_icon_preview = require_child(self.window, QLabel, "labelIconPreview")
        self.button_browse_icon = require_child(self.window, QPushButton, "buttonBrowseIcon")
        self.button_clear_icon = require_child(self.window, QPushButton, "buttonClearIcon")
        self.edit_icon_path = require_child(self.window, QLineEdit, "editIconPath")
        self.edit_project_name = require_child(self.window, QLineEdit, "editProjectName")
        self.combo_game = require_child(self.window, QComboBox, "comboGame")
        self.combo_source_language = require_child(self.window, QComboBox, "comboSourceLanguage")
        self.combo_target_language = require_child(self.window, QComboBox, "comboTargetLanguage")
        self.combo_target_slot = require_child(self.window, QComboBox, "comboTargetSlot")
        self.frame_target_drop = require_child(self.window, QFrame, "frameTargetDrop")
        self.list_target_items = require_child(self.window, QListWidget, "listTargetItems")
        self.button_create_project = require_child(self.window, QPushButton, "buttonCreateProject")
        self.list_recent_projects = require_child(self.window, QListWidget, "listRecentProjects")
        self.action_new_project = require_child(self.window, QAction, "actionNewProject")

        self.frame_icon_drop.installEventFilter(self)
        self.frame_target_drop.installEventFilter(self)
        self._init_project_creation_ui()

    def _connect_actions(self) -> None:
        self.action_new_project.triggered.connect(self.show_new_project_page)
        self.action_open_file.triggered.connect(self.open_file)
        self.action_open_folder.triggered.connect(self.open_folder)
        self.action_open_translation_file.triggered.connect(self.open_translation_file)
        self.action_save.triggered.connect(self.save_translation)
        self.action_save_as.triggered.connect(self.save_translation_as)
        self.action_exit.triggered.connect(self.window.close)

        self.combo_game.currentIndexChanged.connect(self._on_game_selection_changed)
        self.combo_source_language.currentIndexChanged.connect(self._on_source_language_changed)
        self.button_browse_icon.clicked.connect(self._browse_project_icon)
        self.button_clear_icon.clicked.connect(self.clear_project_icon)
        self.button_create_project.clicked.connect(self.create_project)

        self.action_start_translation.triggered.connect(self.open_translation_dialog)
        self.action_translate_selected.triggered.connect(self.open_translation_dialog)
        self.action_translate_untranslated.triggered.connect(self.open_translation_dialog)
        self.action_pause_translation.triggered.connect(lambda: show_not_implemented(self.window, tr("MainWindow", "一時停止")))
        self.action_stop_translation.triggered.connect(self.stop_translation)

        self.action_settings.triggered.connect(self.open_settings)
        self.combo_ai_provider.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.combo_ai_model.currentIndexChanged.connect(self._on_ai_model_changed)
        self.action_problems.triggered.connect(self.open_problems_dialog)
        self.action_about.triggered.connect(lambda: SimpleDialogController("AboutDialog.ui", self.window).exec())

        self.action_list_mode.triggered.connect(self.show_list_mode)
        self.action_focus_mode.triggered.connect(self.show_focus_mode)
        self.action_toggle_file_sidebar.triggered.connect(self.toggle_file_sidebar)

        self.button_list_mode.clicked.connect(self.show_list_mode)
        self.button_focus_mode.clicked.connect(self.show_focus_mode)
        self.button_previous.clicked.connect(self.previous_entry)
        self.button_next.clicked.connect(self.next_entry)
        self.button_revert.clicked.connect(self.refresh_focus)
        self.button_save_and_next.clicked.connect(self.save_focus_edits_and_next)

        self.search.textChanged.connect(self.apply_filters)
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.sync_focus_from_table)

        self.edit_translation.textChanged.connect(self.mark_focus_edited)
        self.edit_context.textChanged.connect(self.mark_focus_edited)
        self.check_translated.stateChanged.connect(self.mark_focus_edited)
        self.check_doubtful.stateChanged.connect(self.mark_focus_edited)
        self.check_hidden.stateChanged.connect(self.mark_focus_edited)
        self.check_locked.stateChanged.connect(self.mark_focus_edited)

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

        from autolingua2.services.updates import check_for_updates
        update_status = check_for_updates()
        action_update = help_menu.addAction(tr("MainWindow", "更新を確認"))
        action_update.setObjectName("actionCheckForUpdates")
        action_update.setEnabled(False)
        action_update.setToolTip(tr("MainWindow", "更新機能は未実装です"))
        action_update.setStatusTip(update_status.message)
        help_menu.setToolTipsVisible(True)

        is_debug = "--debug" in sys.argv
        restart_label = tr("MainWindow", "通常モードで再起動") if is_debug else tr("MainWindow", "デバッグモードで再起動")
        action_restart = help_menu.addAction(restart_label)
        action_restart.triggered.connect(self._restart_application_mode)

        action_open_plugins = help_menu.addAction(tr("MainWindow", "プラグインフォルダを開く"))
        action_open_plugins.triggered.connect(lambda: self._open_folder(PLUGINS_DIR))
        action_logs = help_menu.addAction(tr("MainWindow", "ログフォルダを開く"))
        action_logs.triggered.connect(lambda: self._open_folder(log_directory()))

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

    def _target_snapshot(self) -> list[tuple[str, str]]:
        return [(unit.id, unit.target_text) for unit in self.units]

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

    def _operation_finished(self) -> None:
        worker = self.io_worker
        if worker is None:
            return
        self.io_worker = None
        self._operation_dialog.close()
        self._operation_dialog.deleteLater()
        if self._close_after_io:
            self._close_after_io = False
            self.window.close()
            return
        if worker.error is not None:
            self._restart_target = None
            if not isinstance(worker.error, OperationCancelled):
                QMessageBox.warning(self.window, "プラグイン処理エラー", str(worker.error))
            return
        try:
            self._operation_completed(worker.result)
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

    def open_settings(self) -> None:
        controller = SettingsDialogController(
            self.window, self.provider_registry, self.ai_provider_id,
            self.ai_models, self.ai_selected_models, self.ai_api_keys, self.ai_concurrency,
        )
        if controller.exec() == QDialog.DialogCode.Accepted:
            self.ai_models = controller.ai_models
            self.ai_selected_models = controller.ai_selected_models
            self.ai_api_keys = controller.ai_api_keys
            self.ai_concurrency = controller.spin_concurrency.value()
            self._refresh_ai_choices()
            self._save_ai_choice()
            _, icon_theme = load_theme_settings()
            self.icon_manager.set_current_iconset(icon_theme)
            if self.active_creation_panel:
                from PySide6.QtCore import QCoreApplication
                QCoreApplication.sendEvent(self.active_creation_panel, QEvent(QEvent.Type.LanguageChange))
            if self.units:
                self.apply_filter_rules_to_units()
                self.refresh_all()

    def _refresh_ai_choices(self) -> None:
        self.combo_ai_provider.blockSignals(True)
        self.combo_ai_provider.clear()
        for plugin in self.provider_registry.providers.values():
            self.combo_ai_provider.addItem(plugin.display_name, plugin.id)
        if self.combo_ai_provider.findData(self.ai_provider_id) < 0:
            self.combo_ai_provider.addItem(f"{self.ai_provider_id} (利用不可)", self.ai_provider_id)
        self.combo_ai_provider.setCurrentIndex(self.combo_ai_provider.findData(self.ai_provider_id))
        self.combo_ai_provider.blockSignals(False)
        self._refresh_ai_models()

    def _on_ui_language_changed(self, language_code: str) -> None:
        if self.active_adapter is not None and self.creation_context is not None:
            try:
                self.active_adapter.on_ui_language_changed(language_code, self.creation_context)
            except Exception as exc:
                self._creation_valid = False
                self._panel_valid = False
                self.button_create_project.setEnabled(False)
                QMessageBox.warning(self.window, "プラグインエラー", str(exc))
        with QSignalBlocker(self.combo_game):
            for index in range(self.combo_game.count()):
                adapter, game = self.combo_game.itemData(index)
                self.combo_game.setItemText(index, f"{game.name} ({adapter.name})")
        if self.active_adapter:
            with QSignalBlocker(self.combo_source_language):
                self.combo_source_language.setItemText(0, tr("MainWindow", "自動検出 (Auto Detect)"))
                for code, label in self.active_adapter.supported_languages:
                    index = self.combo_source_language.findData(code)
                    if index >= 0:
                        self.combo_source_language.setItemText(index, label)
            selected = self.combo_game.currentData()
            if selected:
                for code, label in selected[1].available_slots:
                    index = self.combo_target_slot.findData(code)
                    if index >= 0:
                        self.combo_target_slot.setItemText(index, label)
                if not selected[1].available_slots:
                    self.combo_target_slot.setItemText(0, tr("MainWindow", "該当なし"))
        self._refresh_all_target_labels()
        self.columns = default_translation_table_columns(self.status_text, lambda unit: unit.context)
        self.columns_by_id = {column.id: column for column in self.columns}
        self.refresh_all()

    def _refresh_ai_models(self) -> None:
        self.combo_ai_model.blockSignals(True)
        self.combo_ai_model.clear()
        for entry in self.ai_models.get(self.ai_provider_id, []):
            if entry.enabled:
                self.combo_ai_model.addItem(entry.name, entry.model)
        selected = self.ai_selected_models.get(self.ai_provider_id, "")
        index = self.combo_ai_model.findData(selected)
        self.combo_ai_model.setCurrentIndex(index if index >= 0 else 0 if self.combo_ai_model.count() else -1)
        if self.combo_ai_model.currentData() is not None:
            self.ai_selected_models[self.ai_provider_id] = str(self.combo_ai_model.currentData())
        else:
            self.ai_selected_models.pop(self.ai_provider_id, None)
        self.combo_ai_model.blockSignals(False)

    def _save_ai_choice(self) -> None:
        save_ai_settings(AiSettings(
            provider_id=self.ai_provider_id,
            models=self.ai_models,
            selected_models=self.ai_selected_models,
            api_keys=self.ai_api_keys,
            concurrency=self.ai_concurrency,
        ))

    def _on_ai_provider_changed(self, index: int) -> None:
        if index < 0:
            return
        self.ai_provider_id = str(self.combo_ai_provider.itemData(index))
        self._refresh_ai_models()
        self._save_ai_choice()

    def _on_ai_model_changed(self, index: int) -> None:
        if index < 0:
            return
        self.ai_selected_models[self.ai_provider_id] = str(self.combo_ai_model.itemData(index))
        self._save_ai_choice()

    def apply_filter_rules_to_units(self) -> None:
        configs: dict[str, AdapterFilterConfig] = {}

        for unit in self.units:
            adapter_id = self.project.adapter_id

            if adapter_id not in configs:
                saved = load_adapter_filter_rules(adapter_id)
                default_cfg = get_default_filter_config(adapter_id)
                configs[adapter_id] = AdapterFilterConfig.from_dict(saved, default_cfg.rules)

            cfg = configs[adapter_id]
            if should_hide_unit(unit, cfg):
                unit.hidden = True

    def _init_project_creation_ui(self) -> None:
        self.combo_game.blockSignals(True)
        self.combo_game.clear()
        for adapter in get_all_adapters():
            for game in getattr(adapter, "supported_games", []):
                self.combo_game.addItem(f"{game.name} ({adapter.name})", (adapter, game))
        self.combo_game.blockSignals(False)

        self.combo_target_language.clear()
        languages = {locale.bcp47Name(): locale.nativeLanguageName() for locale in QLocale.matchingLocales(
            QLocale.Language.AnyLanguage, QLocale.Script.AnyScript, QLocale.Country.AnyCountry)}
        for code, label in sorted(languages.items(), key=lambda pair: pair[1]):
            self.combo_target_language.addItem(f"{label} ({code})", code)
        self.combo_target_language.setCurrentIndex(self.combo_target_language.findData("ja"))

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
        panel = None
        try:
            if self.active_adapter is not adapter:
                new_context = MainWindowCreationContext(self, adapter.id)
                panel = adapter.create_creation_panel(new_context)
                if not isinstance(panel, QWidget):
                    raise TypeError("create_creation_panel must return QWidget")
                layout = self.frame_target_drop.layout()
                if layout is None:
                    raise RuntimeError("Creation slot layout is missing")
                if self.active_creation_panel is not None:
                    previous_adapter = self.active_adapter
                    if previous_adapter is None:
                        raise RuntimeError("Creation panel has no owning adapter")
                    previous_adapter.dispose_creation_panel(self.active_creation_panel)
                if self.creation_context:
                    self.creation_context.active = False
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget() if item is not None else None
                    if widget:
                        widget.hide()
                        widget.deleteLater()
                self.active_adapter = adapter
                self.creation_context = new_context
                self.active_creation_panel = panel
                layout.addWidget(panel)
                panel.show()
                with QSignalBlocker(self.combo_source_language):
                    self.combo_source_language.clear()
                    self.combo_source_language.addItem(tr("MainWindow", "自動検出 (Auto Detect)"), "auto")
                    for code, label in adapter.supported_languages:
                        self.combo_source_language.addItem(label, code)
            with QSignalBlocker(self.combo_target_slot):
                self.combo_target_slot.clear()
                for code, label in game.available_slots:
                    self.combo_target_slot.addItem(label, code)
                if not game.available_slots:
                    self.combo_target_slot.addItem(tr("MainWindow", "該当なし"), "")
                self.combo_target_slot.setEnabled(bool(game.available_slots))
                self.combo_target_slot.setCurrentIndex(max(0, self.combo_target_slot.findData(game.default_slot)))
            context = self.creation_context
            if context is None:
                raise RuntimeError("Creation context is missing")
            adapter.on_game_selected(game.id, context)
            adapter.on_ui_language_changed(current_ui_language(), context)
            self._creation_valid = True
            self._panel_valid = True
            self._refresh_all_target_labels()
        except Exception as exc:
            if new_context is not None and new_context is not self.creation_context:
                new_context.active = False
                if isinstance(panel, QWidget):
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

    def set_project_icon(self, path: Path) -> None:
        if not path.is_file():
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            QMessageBox.warning(self.window, tr("MainWindow", "エラー"), tr("MainWindow", "有効な画像ファイルではありません。"))
            return
        self.selected_icon_path = path
        scaled = pixmap.scaled(90, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.label_icon_preview.setPixmap(scaled)
        self.label_icon_preview.setText("")
        self.edit_icon_path.setText(path.name)
        self.edit_icon_path.setToolTip(str(path))

    def _browse_project_icon(self) -> None:
        file_filter = tr("MainWindow", "画像ファイル (*.png *.jpg *.jpeg *.webp *.ico *.bmp);;すべてのファイル (*.*)")
        path_str, _ = QFileDialog.getOpenFileName(self.window, tr("MainWindow", "アイコン画像を選択"), "", file_filter)
        if path_str:
            self.set_project_icon(Path(path_str))

    def clear_project_icon(self) -> None:
        self.selected_icon_path = None
        self.label_icon_preview.setPixmap(QPixmap())
        self.label_icon_preview.setText(tr("MainWindow", "アイコン画像\nDnD / 選択"))
        self.edit_icon_path.clear()
        self.edit_icon_path.setToolTip("")

    def _update_path_label(self, path: Path, lbl: QLabel) -> None:
        current_src = str(self.combo_source_language.currentData() or "auto")
        try:
            adapter = self.active_adapter
            if adapter is None:
                raise RuntimeError("No creation adapter selected")
            if not path.exists() or (path.is_file() and not adapter.can_load(path)):
                raise ValueError(tr("MainWindow", "選択形式で読み込めない対象です"))
            text, style, tooltip = adapter.format_target_path_label(path, current_src)
        except Exception as exc:
            text = path.name
            style = "color: #d97706;"
            tooltip = str(exc)
            self._creation_valid = False
            self.button_create_project.setEnabled(False)
        lbl.setText(text)
        lbl.setStyleSheet(style)
        lbl.setToolTip(tooltip)

    def _refresh_all_target_labels(self) -> None:
        self._creation_valid = self._panel_valid
        for path, (lbl, _) in self.target_item_widgets.items():
            self._update_path_label(path, lbl)
        self.button_create_project.setEnabled(self._creation_valid and self.import_worker is None)

    def _on_source_language_changed(self) -> None:
        self._refresh_all_target_labels()

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

    def create_project(self) -> None:
        if self.import_worker is not None or not self._creation_valid:
            return
        if not self.target_paths:
            QMessageBox.warning(self.window, tr("MainWindow", "警告"), tr("MainWindow", "翻訳対象のファイルまたはフォルダを追加してください。"))
            return

        selected_data = self.combo_game.currentData()
        adapter, game = selected_data if selected_data else (None, None)

        if adapter is None or game is None:
            return
        self._import_metadata = dict(
            name=self.edit_project_name.text().strip() or "Untitled",
            icon_path=str(self.selected_icon_path or ""), game_id=game.id,
            target_language=str(self.combo_target_language.currentData()),
            target_file_language=str(self.combo_target_slot.currentData() or ""))
        worker = ImportWorker(adapter, self.target_paths,
                              str(self.combo_source_language.currentData() or "auto"), self)
        self.import_worker = worker
        self._set_import_busy(True)
        worker.loaded.connect(self._on_project_imported)
        worker.failed.connect(self._on_import_failed)
        worker.progress.connect(self._operation_progress)
        worker.finished.connect(self._on_import_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _set_import_busy(self, busy: bool) -> None:
        for widget in (self.combo_game, self.combo_source_language, self.combo_target_language,
                       self.edit_project_name, self.list_target_items,
                       self.frame_icon_drop):
            widget.setEnabled(not busy)
        if self.active_creation_panel is not None:
            set_busy = getattr(self.active_creation_panel, "set_busy", None)
            if callable(set_busy):
                set_busy(busy)
            else:
                self.active_creation_panel.setEnabled(not busy)
        self.combo_target_slot.setEnabled(not busy and bool(self.combo_target_slot.currentData()))
        self.button_create_project.setEnabled(not busy and self._creation_valid)
        for action in (self.action_open_file, self.action_open_folder, self.action_new_project,
                       self.action_settings):
            action.setEnabled(not busy)
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
                    imported.project.target_file_language = game.default_slot
        self.load_import(imported)
        self.window.setWindowTitle(f"AUTOlingua - {imported.project.name}")

    def _on_import_failed(self, message: str) -> None:
        self._operation_progress(message)
        if not self._close_after_import:
            QMessageBox.warning(self.window, tr("MainWindow", "読み込みエラー"), message)

    def _on_import_finished(self) -> None:
        self.import_worker = None
        self._set_import_busy(False)
        if self._close_after_import:
            self._close_after_import = False
            self.window.close()

    def _set_initial_state(self) -> None:
        self.stack_main.setCurrentIndex(0)
        self.action_open_translation_file.setEnabled(False)
        self.action_save.setEnabled(False)
        self.action_save_as.setEnabled(False)
        self.action_stop_translation.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.refresh_all()
        self._restore_window_layout()

    def _restore_window_layout(self) -> None:
        layout = load_window_layout()
        if layout.geometry:
            self.window.restoreGeometry(QByteArray.fromHex(layout.geometry.encode("ascii")))
        if layout.state:
            self.window.restoreState(QByteArray.fromHex(layout.state.encode("ascii")))
        if layout.splitter_main:
            self.splitter_main.restoreState(QByteArray.fromHex(layout.splitter_main.encode("ascii")))
        if layout.splitter_focus:
            self.splitter_focus.restoreState(QByteArray.fromHex(layout.splitter_focus.encode("ascii")))
        self.action_toggle_file_sidebar.setChecked(layout.sidebar_visible)
        self.frame_files.setVisible(layout.sidebar_visible)

    def _save_window_layout(self) -> None:
        geom = self.window.saveGeometry().data().hex()
        state = self.window.saveState().data().hex()
        sp_main = self.splitter_main.saveState().data().hex()
        sp_focus = self.splitter_focus.saveState().data().hex()
        sidebar = self.action_toggle_file_sidebar.isChecked()
        save_window_layout(WindowLayout(
            geometry=geom,
            state=state,
            splitter_main=sp_main,
            splitter_focus=sp_focus,
            sidebar_visible=sidebar,
        ))

    def open_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self.window,
            tr("MainWindow", "翻訳対象ファイルを開く"),
            str(Path.cwd()),
            supported_file_filter(),
        )
        if not file_name:
            return

        path = Path(file_name)
        try:
            adapter = self.active_adapter if self.active_adapter and self.active_adapter.can_load(path) else adapter_for(path)
        except Exception as exc:
            QMessageBox.warning(self.window, "読み込みエラー", str(exc))
            return
        if adapter is None:
            QMessageBox.warning(self.window, tr("MainWindow", "エラー"), tr("MainWindow", "対応するアダプターが見つかりません。"))
            return

        self.show_new_project_page()
        if adapter is not self.active_adapter:
            self.select_game_by_id(adapter.supported_games[0].id, adapter.id)
        try:
            self.add_target_path(path)
        except Exception as exc:
            QMessageBox.warning(self.window, "読み込みエラー", str(exc))

    def open_folder(self) -> None:
        folder_name = QFileDialog.getExistingDirectory(
            self.window,
            tr("MainWindow", "翻訳対象フォルダを開く"),
            str(Path.cwd()),
        )
        if not folder_name:
            return

        self.show_new_project_page()
        try:
            self.add_target_path(Path(folder_name))
        except Exception as exc:
            QMessageBox.warning(self.window, "読み込みエラー", str(exc))

    def open_translation_file(self) -> None:
        if len(self.project.sources) != 1:
            return

        file_name, _ = QFileDialog.getOpenFileName(
            self.window,
            tr("MainWindow", "既存訳ファイルを開く"),
            str(Path(self.project.sources[0].id).parent),
            supported_file_filter(),
        )
        if not file_name:
            return

        path = Path(file_name)
        if path.resolve() == Path(self.project.sources[0].id).resolve():
            QMessageBox.warning(self.window, tr("MainWindow", "エラー"), tr("MainWindow", "原文と同じファイルは指定できません。"))
            return

        adapter = adapter_by_id(self.project.adapter_id)
        if not adapter.can_load(path):
            QMessageBox.warning(self.window, tr("MainWindow", "エラー"), tr("MainWindow", "原文と同じ形式のファイルを選択してください。"))
            return

        if any(unit.target_text for unit in self.units):
            answer = QMessageBox.question(
                self.window,
                tr("MainWindow", "既存訳の読み込み"),
                tr("MainWindow", "現在の訳文を既存訳ファイルの内容で置き換えますか？"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._run_operation(lambda: load_file(path, adapter), self._existing_translation_loaded)

    def _existing_translation_loaded(self, translation: ImportedTranslation) -> None:
        try:
            summary = apply_existing_translation(self.imported, translation)
        except Exception as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "エラー"), str(exc))
            return

        self.existing_translation = translation
        self._pending_human_memory.clear()
        self._translation_methods.clear()
        try:
            with TranslationMemoryStore() as memory:
                for unit in self.units:
                    memory.record_imported(
                        unit.source_text, unit.target_text, self.project.source_language,
                        self.project.target_language, self.memory_context_for_unit(unit),
                    )
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "翻訳メモリ"), str(exc))
        self.output_path = None
        self.status_filter.setCurrentText(tr("MainWindow", "未翻訳"))
        self.refresh_all()
        self.window.statusBar().showMessage(
            tr("MainWindow", "既存訳を{matched}件対応付けました（未翻訳{untranslated}件、翻訳済み{translated}件）。").format(
                matched=summary.matched,
                untranslated=summary.untranslated,
                translated=summary.translated,
            ),
            8000,
        )

    def load_import(self, imported: ImportedTranslation) -> None:
        self._pending_human_memory.clear()
        self._translation_methods.clear()
        self.existing_translation = None
        self.output_path = None
        self.imported = imported
        self.project = imported.project
        self.units = self.project.units
        self._saved_targets = self._target_snapshot()
        self.action_open_translation_file.setEnabled(
            len(self.project.sources) == 1
        )
        self.action_save.setEnabled(bool(self.project.sources))
        self.action_save_as.setEnabled(self.action_save.isEnabled())
        self.apply_filter_rules_to_units()
        self.current_unit = self.units[0] if self.units else None
        self.status_filter.setCurrentText(tr("MainWindow", "未翻訳"))
        self.refresh_all()
        self.stack_main.setCurrentIndex(1)
        self.window.statusBar().showMessage(
            tr("MainWindow", "{source_count}ソース / {unit_count}項目を読み込みました").format(
                source_count=len(self.project.sources),
                unit_count=len(self.units),
            ),
            5000,
        )

    def refresh_all(self) -> None:
        self.refresh_file_tree()
        self.apply_filters()

    def refresh_file_tree(self) -> None:
        self.tree_files.clear()
        for source in self.project.sources:
            count = self.count_units_for_source(source)
            item = QTreeWidgetItem([f"{source.name} ({count})"])
            item.setToolTip(0, source.name)
            self.tree_files.addTopLevelItem(item)

    def apply_filters(self) -> None:
        query = self.search.text()
        selected_status = self.status_filter.currentText()

        self.filtered_units = [
            unit
            for unit in self.units
            if unit.matches(query)
            and (selected_status == tr("MainWindow", "すべて") or self.unit_matches_status(unit, selected_status))
        ]
        self.refresh_table()
        if self.filtered_units and self.current_unit not in self.filtered_units:
            self.current_unit = self.filtered_units[0]
        elif not self.filtered_units:
            self.current_unit = None
        self.refresh_focus()

    def refresh_table(self) -> None:
        visible_columns = self.visible_columns()
        self.table.clear()
        self.table.setColumnCount(len(visible_columns))
        self.table.setHorizontalHeaderLabels([column.label for column in visible_columns])
        self.table.setRowCount(len(self.filtered_units))
        for row, unit in enumerate(self.filtered_units):
            for column_index, column in enumerate(visible_columns):
                value = column.value_for(unit, self.source_name_for_unit)
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, unit)
                self.table.setItem(row, column_index, item)
        self.apply_header_visual_order()
        self.table.resizeColumnsToContents()
        self.progress.setMaximum(max(len(self.units), 1))
        self.progress.setValue(sum(1 for unit in self.units if unit.state == UnitState.TRANSLATED))

    def sync_focus_from_table(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        unit = selected[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(unit, TranslationUnit):
            self.current_unit = unit
            self.refresh_focus()

    def refresh_focus(self) -> None:
        self._updating_focus = True
        try:
            unit = self.current_unit
            if unit is None:
                self.edit_key.clear()
                self.edit_source.clear()
                self.edit_translation.clear()
                self.edit_context.clear()
                self.label_position.setText("0 / 0")
                self.check_translated.setChecked(False)
                self.check_doubtful.setChecked(False)
                self.check_hidden.setChecked(False)
                self.check_locked.setChecked(False)
                return

            position = self.filtered_units.index(unit) + 1 if unit in self.filtered_units else 0
            self.label_position.setText(f"{position} / {len(self.filtered_units)}")
            self.edit_key.setText(unit.label)
            self.edit_source.setPlainText(unit.source_text)
            self.edit_translation.setPlainText(unit.target_text)
            self.edit_context.setPlainText(unit.context)
            self.check_translated.setChecked(unit.state == UnitState.TRANSLATED)
            self.check_doubtful.setChecked(unit.state == UnitState.DOUBTFUL)
            self.check_hidden.setChecked(unit.hidden)
            self.check_locked.setChecked(unit.locked)
        finally:
            self._updating_focus = False

    def mark_focus_edited(self) -> None:
        if self._updating_focus or self.current_unit is None:
            return
        new_target = self.edit_translation.toPlainText()
        if new_target != self.current_unit.target_text:
            self._pending_human_memory[self.current_unit.id] = new_target
            self._translation_methods[self.current_unit.id] = "human"
        self.current_unit.target_text = new_target
        self.current_unit.context = self.edit_context.toPlainText()
        self.current_unit.state = self.current_state_from_controls(self.current_unit.target_text)
        self._updating_focus = True
        try:
            self.check_translated.setChecked(self.current_unit.state == UnitState.TRANSLATED)
            self.check_doubtful.setChecked(self.current_unit.state == UnitState.DOUBTFUL)
        finally:
            self._updating_focus = False
        self.current_unit.hidden = self.check_hidden.isChecked()
        self.current_unit.locked = self.check_locked.isChecked()
        self.refresh_table()

    def save_focus_edits_and_next(self) -> None:
        self.mark_focus_edited()
        self.next_entry()

    def previous_entry(self) -> None:
        self.move_focus(-1)

    def next_entry(self) -> None:
        self.move_focus(1)

    def move_focus(self, step: int) -> None:
        if not self.filtered_units:
            return
        if self.current_unit in self.filtered_units:
            index = self.filtered_units.index(self.current_unit)
        else:
            index = 0
        self.current_unit = self.filtered_units[(index + step) % len(self.filtered_units)]
        self.refresh_focus()

    def show_list_mode(self) -> None:
        self.stack.setCurrentIndex(0)
        self.button_list_mode.setChecked(True)
        self.button_focus_mode.setChecked(False)
        self.action_list_mode.setChecked(True)
        self.action_focus_mode.setChecked(False)

    def show_focus_mode(self) -> None:
        if self.current_unit is None and self.filtered_units:
            self.current_unit = self.filtered_units[0]
        self.stack.setCurrentIndex(1)
        self.button_list_mode.setChecked(False)
        self.button_focus_mode.setChecked(True)
        self.action_list_mode.setChecked(False)
        self.action_focus_mode.setChecked(True)
        self.refresh_focus()

    def toggle_file_sidebar(self) -> None:
        visible = self.action_toggle_file_sidebar.isChecked()
        self.frame_files.setVisible(visible)

    def open_translation_dialog(self) -> None:
        selected_only = self.sender() is self.action_translate_selected
        if self.translation_worker is not None or not self.units:
            return
        dialog = SimpleDialogController("TranslationDialog.ui", self.window).dialog
        label_total = require_child(dialog, QLabel, "labelTotalValue")
        label_untranslated = require_child(dialog, QLabel, "labelUntranslatedValue")
        label_selected = require_child(dialog, QLabel, "labelSelectedValue")
        combo_source = require_child(dialog, QComboBox, "comboSourceLanguage")
        combo_target = require_child(dialog, QComboBox, "comboTargetLanguage")
        skip_translated = require_child(dialog, QCheckBox, "checkSkipTranslated")
        skip_translated.setText(tr("MainWindow", "未翻訳のみ翻訳（既存テキストを保持）"))
        skip_translated.setChecked(True)
        skip_translated.setEnabled(False)
        skip_locked = require_child(dialog, QCheckBox, "checkSkipLocked")
        skip_locked.setChecked(True)
        skip_locked.setEnabled(False)

        label_total.setText(str(len(self.units)))
        label_untranslated.setText(str(sum(1 for unit in self.units if unit.state == UnitState.UNTRANSLATED)))
        label_selected.setText(str(len({item.row() for item in self.table.selectedItems()})))

        combo_source.clear()
        combo_target.clear()
        for combo, code in ((combo_source, self.project.source_language),
                            (combo_target, self.project.target_language)):
            combo.addItem(f"{QLocale(code).nativeLanguageName()} ({code})", code)

        if self.project.source_language:
            idx = combo_source.findData(self.project.source_language)
            if idx >= 0:
                combo_source.setCurrentIndex(idx)
        if self.project.target_language:
            idx = combo_target.findData(self.project.target_language)
            if idx >= 0:
                combo_target.setCurrentIndex(idx)
        combo_source.setEnabled(False)
        combo_target.setEnabled(False)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if combo_source.currentData() == combo_target.currentData():
            QMessageBox.warning(self.window, tr("MainWindow", "翻訳"), tr("MainWindow", "翻訳元と翻訳先の言語が同じです。"))
            return

        if selected_only:
            rows = {item.row() for item in self.table.selectedItems()}
            candidates = [self.filtered_units[row] for row in sorted(rows)]
        else:
            candidates = self.units
        items = [
            (unit.id, unit.source_text, self.memory_context_for_unit(unit))
            for unit in candidates
            if unit.state == UnitState.UNTRANSLATED and not unit.locked
            and (not unit.target_text.strip() or unit.target_text == unit.source_text)
            and unit.source_text.strip()
        ]
        if not items:
            QMessageBox.information(self.window, tr("MainWindow", "翻訳"), tr("MainWindow", "翻訳できる未翻訳項目がありません。"))
            return
        self.project.source_language = str(combo_source.currentData())
        self.project.target_language = str(combo_target.currentData())
        self.start_translation(items)

    def memory_context_for_unit(self, unit: TranslationUnit) -> str:
        ref = self.imported.source_refs.get(unit.id)
        return f"{ref.source_id if ref else ''}::{unit.label}"

    def start_translation(self, items: list[tuple[str, str, str]]) -> None:
        worker = TranslationWorker(
            items,
            self.project.source_language,
            self.project.target_language,
            self.ai_provider_id,
            self.provider_registry.get(self.ai_provider_id),
            self.ai_api_keys.get(self.ai_provider_id, ""),
            str(self.combo_ai_model.currentData() or ""),
            self.ai_concurrency,
        )
        self.translation_worker = worker
        worker.translated.connect(self.on_translation_result)
        worker.failed.connect(self.on_translation_error)
        worker.advanced.connect(self.on_translation_progress)
        worker.finished.connect(self.on_translation_finished)
        worker.finished.connect(worker.deleteLater)
        self.action_start_translation.setEnabled(False)
        self.action_translate_selected.setEnabled(False)
        self.action_translate_untranslated.setEnabled(False)
        self.action_open_file.setEnabled(False)
        self.action_open_folder.setEnabled(False)
        self.action_open_translation_file.setEnabled(False)
        self.action_stop_translation.setEnabled(True)
        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        worker.start()

    def stop_translation(self) -> None:
        if self.translation_worker is not None:
            self.translation_worker.stop()
            self.window.statusBar().showMessage(tr("MainWindow", "停止しています。現在のリクエストの終了を待ちます。"))

    def on_translation_result(self, unit_id: str, target_text: str, method: str) -> None:
        unit = next((item for item in self.units if item.id == unit_id), None)
        if unit is None or unit.state != UnitState.UNTRANSLATED or unit.locked or (
            unit.target_text.strip() and unit.target_text != unit.source_text
        ):
            return
        unit.target_text = target_text
        unit.state = UnitState.TRANSLATED
        self._translation_methods[unit_id] = method
        self.refresh_all()

    def on_translation_error(self, unit_id: str, message: str) -> None:
        unit = next((item for item in self.units if item.id == unit_id), None)
        if unit is not None:
            unit.issues.append(Issue(message=f"翻訳: {message}"))
            self.refresh_all()

    def on_translation_progress(self, completed: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(completed)
        self.window.statusBar().showMessage(f"{completed} / {total}")

    def on_translation_finished(self) -> None:
        self.translation_worker = None
        self.action_start_translation.setEnabled(True)
        self.action_translate_selected.setEnabled(True)
        self.action_translate_untranslated.setEnabled(True)
        self.action_open_file.setEnabled(True)
        self.action_open_folder.setEnabled(True)
        self.action_open_translation_file.setEnabled(len(self.project.sources) == 1)
        self.action_stop_translation.setEnabled(False)
        self.refresh_all()
        self.window.statusBar().showMessage(tr("MainWindow", "翻訳処理が終了しました。"), 5000)
        if self._close_after_translation:
            self._close_after_translation = False
            self.window.close()

    def save_translation(self) -> None:
        if self.output_path is None:
            self.save_translation_as()
        else:
            self._write_translation(self.output_path)

    def save_translation_as(self) -> None:
        if not self.project.sources:
            self._restart_target = None
            return
        if len(self.project.sources) > 1:
            folder = QFileDialog.getExistingDirectory(self.window, tr("MainWindow", "翻訳結果の出力フォルダ"))
            if folder:
                self._write_translation(Path(folder))
            else:
                self._restart_target = None
            return
        adapter = adapter_by_id(self.project.adapter_id)
        source_path = Path(self.project.sources[0].id)
        self._run_operation(lambda: adapter.output_name(source_path, self.project),
                            lambda name: self._choose_output_file(source_path, name))

    def _choose_output_file(self, source_path: Path, default_name: str) -> None:
        if not default_name or Path(default_name).name != default_name:
            self._restart_target = None
            QMessageBox.warning(self.window, "保存エラー", "出力ファイル名が不正です。")
            return
        if self.existing_translation is not None:
            existing_path = Path(self.existing_translation.project.sources[0].id)
            if source_path.with_name(default_name).resolve() == existing_path.resolve():
                default_name = f"{source_path.with_name(default_name).stem}_autolingua{source_path.suffix}"
        file_name, _ = QFileDialog.getSaveFileName(
            self.window, tr("MainWindow", "翻訳結果を別ファイルへ保存"),
            str(source_path.with_name(default_name)),
            supported_file_filter(adapter_by_id(self.project.adapter_id)))
        if file_name:
            self._write_translation(Path(file_name))
        else:
            self._restart_target = None

    def _write_translation(self, path: Path) -> None:
        adapter = adapter_by_id(self.project.adapter_id)
        self._run_operation(lambda: plan_output(adapter, self.imported, path, self.existing_translation),
                            lambda outputs: self._confirm_output(path, outputs))

    def _confirm_output(self, path: Path, outputs) -> None:
        existing_paths = [str(output.path) for output in outputs if output.path.exists()]
        if existing_paths and path != self.output_path:
            answer = QMessageBox.question(self.window, tr("MainWindow", "保存"),
                tr("MainWindow", "既存の出力ファイルを上書きしますか？") + "\n" + "\n".join(existing_paths))
            if answer != QMessageBox.StandardButton.Yes:
                self._restart_target = None
                return
        adapter = adapter_by_id(self.project.adapter_id)
        self._run_operation(lambda: write_output(adapter, outputs, self.existing_translation),
                            lambda _: self._output_saved(path))

    def _output_saved(self, path: Path) -> None:
        self.output_path = path
        self._saved_targets = self._target_snapshot()
        self._record_human_edits()
        self.window.statusBar().showMessage(tr("MainWindow", "翻訳結果を保存しました: {path}").format(path=str(path)), 8000)
        if self._restart_target is not None:
            QTimer.singleShot(0, self.window.close)

    def _record_human_edits(self) -> None:
        if not self._pending_human_memory:
            return
        try:
            with TranslationMemoryStore() as memory:
                for unit in self.units:
                    target = self._pending_human_memory.get(unit.id)
                    if target is None or target != unit.target_text:
                        continue
                    if not target.strip() or target == unit.source_text or unit.state != UnitState.TRANSLATED:
                        continue
                    memory.record(
                        unit.source_text, target, self.project.source_language,
                        self.project.target_language, "human", self.memory_context_for_unit(unit),
                    )
                    del self._pending_human_memory[unit.id]
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self.window, tr("MainWindow", "翻訳メモリ"), str(exc))

    def open_problems_dialog(self) -> None:
        controller = SimpleDialogController("ProblemsDialog.ui", self.window)
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
        if unit.hidden:
            return tr("MainWindow", "非表示")
        if unit.locked:
            return tr("MainWindow", "ロック")
        if unit.issues:
            return tr("MainWindow", "問題あり")
        if unit.state == UnitState.DOUBTFUL:
            return tr("MainWindow", "疑問あり")
        if unit.state == UnitState.TRANSLATED:
            method = self._translation_methods.get(unit.id)
            if method == "human":
                return tr("MainWindow", "人間が修正")
            if method == "exact":
                return tr("MainWindow", "翻訳メモリ")
            if method == "structural":
                return tr("MainWindow", "構造一致")
            if method == "ai":
                return tr("MainWindow", "AI翻訳")
            return tr("MainWindow", "翻訳済み")
        return tr("MainWindow", "未翻訳")

    def unit_matches_status(self, unit: TranslationUnit, status: str) -> bool:
        matcher = self.status_matchers_by_label().get(status)
        return matcher(unit) if matcher is not None else False

    def status_matchers_by_label(self) -> dict[str, Callable[[TranslationUnit], bool]]:
        return {
            tr("MainWindow", "非表示"): STATUS_MATCHERS["hidden"],
            tr("MainWindow", "ロック"): STATUS_MATCHERS["locked"],
            tr("MainWindow", "問題あり"): STATUS_MATCHERS["has_issues"],
            tr("MainWindow", "疑問あり"): STATUS_MATCHERS["doubtful"],
            tr("MainWindow", "翻訳済み"): STATUS_MATCHERS["translated"],
            tr("MainWindow", "未翻訳"): STATUS_MATCHERS["untranslated"],
        }

    def current_state_from_controls(self, target_text: str) -> UnitState:
        if not target_text.strip() or (
            self.current_unit is not None and target_text == self.current_unit.source_text
        ):
            return UnitState.UNTRANSLATED
        if self.check_doubtful.isChecked():
            return UnitState.DOUBTFUL
        return UnitState.TRANSLATED

    def count_units_for_source(self, source: TranslationSource) -> int:
        return sum(1 for ref in self.imported.source_refs.values() if ref.source_id == source.id)

    def source_name_for_unit(self, unit: TranslationUnit) -> str:
        ref = self.imported.source_refs.get(unit.id)
        if ref is None:
            return ""
        for source in self.project.sources:
            if source.id == ref.source_id:
                return source.name
        return ref.source_id

    def visible_columns(self) -> list[TranslationTableColumn]:
        return [
            self.columns_by_id[column_id]
            for column_id in self.column_layout.order
            if column_id in self.columns_by_id and column_id not in self.column_layout.hidden
        ]

    def open_table_header_menu(self, position: QPoint) -> None:
        header = self.table.horizontalHeader()
        logical_index = header.logicalIndexAt(position)
        visible_columns = self.visible_columns()
        clicked_column = visible_columns[logical_index].id if 0 <= logical_index < len(visible_columns) else None

        menu = QMenu(self.window)
        visible_count = len(visible_columns)

        for column_id in self.column_layout.order:
            column = self.columns_by_id.get(column_id)
            if column is None:
                continue
            action = QAction(column.label, menu)
            action.setCheckable(True)
            action.setChecked(column_id not in self.column_layout.hidden)
            action.setEnabled(not action.isChecked() or visible_count > 1)
            action.toggled.connect(lambda checked, selected_id=column_id: self.set_column_visible(selected_id, checked))
            menu.addAction(action)

        menu.addSeparator()
        move_left = menu.addAction(tr("MainWindow", "左へ移動"))
        move_left.setEnabled(clicked_column is not None and self.can_move_visible_column(clicked_column, -1))
        move_left.triggered.connect(lambda: self.move_visible_column(clicked_column, -1))

        move_right = menu.addAction(tr("MainWindow", "右へ移動"))
        move_right.setEnabled(clicked_column is not None and self.can_move_visible_column(clicked_column, 1))
        move_right.triggered.connect(lambda: self.move_visible_column(clicked_column, 1))

        menu.addSeparator()
        reset = menu.addAction(tr("MainWindow", "初期状態に戻す"))
        reset.triggered.connect(self.reset_column_layout)

        menu.exec(header.mapToGlobal(position))

    def set_column_visible(self, column_id: str, visible: bool) -> None:
        if visible:
            self.column_layout.hidden.discard(column_id)
        else:
            if len(self.visible_columns()) <= 1:
                return
            self.column_layout.hidden.add(column_id)
        self.save_and_refresh_column_layout()

    def can_move_visible_column(self, column_id: str | None, direction: int) -> bool:
        if column_id is None:
            return False
        visible_ids = [column.id for column in self.visible_columns()]
        if column_id not in visible_ids:
            return False
        new_index = visible_ids.index(column_id) + direction
        return 0 <= new_index < len(visible_ids)

    def move_visible_column(self, column_id: str | None, direction: int) -> None:
        if not self.can_move_visible_column(column_id, direction) or column_id is None:
            return
        visible_ids = [column.id for column in self.visible_columns()]
        old_visible_index = visible_ids.index(column_id)
        other_column_id = visible_ids[old_visible_index + direction]
        old_index = self.column_layout.order.index(column_id)
        other_index = self.column_layout.order.index(other_column_id)
        self.column_layout.order[old_index], self.column_layout.order[other_index] = (
            self.column_layout.order[other_index],
            self.column_layout.order[old_index],
        )
        self.save_and_refresh_column_layout()

    def reset_column_layout(self) -> None:
        self.column_layout = ColumnLayout(
            order=[column.id for column in self.columns],
            hidden={column.id for column in self.columns if not column.default_visible},
        )
        self.save_and_refresh_column_layout()

    def handle_table_section_moved(self, logical_index: int, old_visual_index: int, new_visual_index: int) -> None:
        if self._syncing_header_order or old_visual_index == new_visual_index:
            return
        visible_ids = [column.id for column in self.visible_columns()]
        if logical_index < 0 or logical_index >= len(visible_ids):
            return
        moved_column_id = visible_ids[logical_index]
        remaining_visible = [column_id for column_id in visible_ids if column_id != moved_column_id]
        bounded_index = max(0, min(new_visual_index, len(remaining_visible)))
        remaining_visible.insert(bounded_index, moved_column_id)
        self.reorder_layout_by_visible_ids(remaining_visible)
        save_translation_table_columns(self.column_layout)

    def reorder_layout_by_visible_ids(self, visible_ids: list[str]) -> None:
        visible_set = set(visible_ids)
        reordered: list[str] = []
        visible_iter = iter(visible_ids)
        for column_id in self.column_layout.order:
            if column_id in visible_set:
                reordered.append(next(visible_iter))
            else:
                reordered.append(column_id)
        self.column_layout.order = reordered

    def apply_header_visual_order(self) -> None:
        header = self.table.horizontalHeader()
        self._syncing_header_order = True
        try:
            for target_visual_index, logical_index in enumerate(range(self.table.columnCount())):
                current_visual_index = header.visualIndex(logical_index)
                if current_visual_index != target_visual_index:
                    header.moveSection(current_visual_index, target_visual_index)
        finally:
            self._syncing_header_order = False

    def save_and_refresh_column_layout(self) -> None:
        save_translation_table_columns(self.column_layout)
        self.refresh_table()

    def show_header_drop_indicator(self, position: QPoint) -> None:
        header = self.table.horizontalHeader()
        if self.table.columnCount() == 0:
            self.hide_header_drop_indicator()
            return

        x = self.header_drop_indicator_x(position)
        self.header_drop_indicator.setGeometry(x - 1, 0, 3, header.height())
        self.header_drop_indicator.raise_()
        self.header_drop_indicator.show()

    def hide_header_drop_indicator(self) -> None:
        self._dragged_header_logical_index = None
        if hasattr(self, "header_drop_indicator"):
            self.header_drop_indicator.hide()

    def header_drop_indicator_x(self, position: QPoint) -> int:
        header = self.table.horizontalHeader()
        logical_index = header.logicalIndexAt(position)

        if logical_index < 0:
            if position.x() < 0:
                first_logical = header.logicalIndex(0)
                return header.sectionViewportPosition(first_logical)
            last_logical = header.logicalIndex(header.count() - 1)
            return header.sectionViewportPosition(last_logical) + header.sectionSize(last_logical)

        section_left = header.sectionViewportPosition(logical_index)
        section_width = header.sectionSize(logical_index)
        section_center = section_left + section_width // 2
        if position.x() < section_center:
            return section_left
        return section_left + section_width
