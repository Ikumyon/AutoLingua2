from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QSize, Qt, QSignalBlocker, QTimer, QLocale
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QIcon, QMouseEvent, QPixmap, QSyntaxHighlighter
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
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autolingua2.ui.page_scrubber import RangeScrubberWidget

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ui.creation_contract import CreationActions, CreationAdapter
from autolingua2.ui.creation_panel import CommonCreationAdapter
from autolingua2.extensions import ExtensionEntrance
from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.infrastructure.platform import current_platform, log_directory
from autolingua2.infrastructure.platform.base import PlatformDriver
from autolingua2.infrastructure.operations import OperationCancelled
from autolingua2.ir import Issue, TranslationProject, TranslationSource, TranslationUnit, UnitState
from autolingua2.ir.filter_rules import AdapterFilterConfig, should_hide_unit
from autolingua2.services.filter_rules import get_default_filter_config
from autolingua2.services.export import export_translation
from autolingua2.services.settings_store import (
    AiSettings,
    ColumnLayout,
    WindowLayout,
    load_adapter_filter_rules,
    load_ai_settings,
    load_theme_settings,
    load_translation_table_columns,
    load_ui_display_flags,
    load_window_layout,
    save_ai_settings,
    save_translation_table_columns,
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
from autolingua2.ui.i18n import current_ui_language, language_events, tr
from autolingua2.ui.import_worker import ImportWorker
from autolingua2.ui.operation_worker import OperationWorker
from autolingua2.plugins.api import GameTextPresentation
from autolingua2.ui.models.translation_table_model import TranslationTableColumn, default_translation_table_columns


STATUS_MATCHERS: dict[str, Callable[[TranslationUnit], bool]] = {
    "hidden": lambda unit: unit.hidden or unit.state == UnitState.HIDDEN,
    "locked": lambda unit: unit.locked or unit.state == UnitState.LOCKED,
    "has_issues": lambda unit: bool(unit.issues),
    "doubtful": lambda unit: unit.state == UnitState.DOUBTFUL,
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

    def get_icon(self, name: str) -> QIcon:
        return self.controller.icon_manager.get_icon(name)

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
            select_game=self.select_game, set_source_language=self.set_source_language,
            set_target_slot=self.set_target_slot, get_icon=self.get_icon,
        )



class MainWindowController(QObject):
    def __init__(self, entrance: ExtensionEntrance, platform_driver: PlatformDriver = current_platform) -> None:
        super().__init__()
        self.platform = platform_driver
        self.entrance = entrance
        self.plugins = entrance.plugins
        self._known_plugin_errors = len(self.plugins.errors)
        self.io_worker: OperationWorker | None = None
        self._close_after_io = False
        self._restart_target: bool | None = None
        self._restart_started = False
        self._saved_targets: list[tuple[str, str]] = []
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
        ai_settings = load_ai_settings()
        self.ai_provider_id = ai_settings.provider_id
        self.ai_models = ai_settings.models
        self.ai_selected_models = ai_settings.selected_models
        self.ai_concurrency = ai_settings.concurrency
        self.ai_api_keys = ai_settings.api_keys
        self.project = self.imported.project
        self.units: list[TranslationUnit] = []
        self.filtered_units: list[TranslationUnit] = []
        self.current_unit: TranslationUnit | None = None
        self.columns = default_translation_table_columns(self.status_text)
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
        self._focus_sidebar_visible: bool = True
        self._syncing_focus_list: bool = False
        self.focus_page_size: int = 50
        self.focus_current_page: int = 1
        render_newlines, highlight_tags, apply_colors = load_ui_display_flags()
        self.render_literal_newlines: bool = render_newlines
        self.highlight_translation_tags: bool = highlight_tags
        self.apply_color_tags: bool = apply_colors
        self._text_presentation: GameTextPresentation | None = None
        self.source_highlighter: QSyntaxHighlighter | None = None
        self.translation_highlighter: QSyntaxHighlighter | None = None

        self._setup_widgets()
        self.plugins.on_display_changed(self._on_plugin_display_changed)
        self._configure_text_presentation()
        self._connect_actions()
        self._set_initial_state()
        self.window.installEventFilter(self)
        language_events().changed.connect(self._on_ui_language_changed)
        if entrance.errors:
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self.window, "拡張読み込みエラー", "\n".join(entrance.errors)))

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
            self.plugins.remove_display_listener(self._on_plugin_display_changed)
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
                        adapter = self.active_creation_adapter
                        context = self.creation_context
                        if (self.import_worker is not None or not self._creation_valid
                                or adapter is None or context is None):
                            return True
                        try:
                            remaining = adapter.on_paths_dropped(paths, self.plugins.context(context.adapter_id))
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
                    self._is_header_dragging = True
                    self._drag_start_global_pos = event.globalPosition().toPoint()
                elif event.type() == QEvent.Type.MouseMove and bool(event.buttons() & Qt.MouseButton.LeftButton):
                    if getattr(self, "_is_header_dragging", False):
                        curr_global = event.globalPosition().toPoint()
                        start_global = getattr(self, "_drag_start_global_pos", curr_global)
                        if (curr_global - start_global).manhattanLength() >= 4:
                            vp = header.viewport()
                            ref = vp if vp is not None else header
                            pos_in_vp = ref.mapFromGlobal(curr_global)
                            self.show_header_drop_indicator(pos_in_vp)
                elif event.type() == QEvent.Type.MouseButtonRelease:
                    self.hide_header_drop_indicator()
            elif event.type() == QEvent.Type.Leave:
                if not getattr(self, "_is_header_dragging", False):
                    self.hide_header_drop_indicator()
        elif watched is getattr(self, "frame_segment_mode", None):
            if event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
                self._sync_segment_indicator_pos(animate=False)
        return False

    def _set_drop_hover(self, target: QObject, is_hover: bool) -> None:
        if isinstance(target, QWidget):
            target.setProperty("dragOver", is_hover)
            target.style().unpolish(target)
            target.style().polish(target)

    def _setup_widgets(self) -> None:
        self.table = require_child(self.window, QTableWidget, "tableTranslations")
        self.list_focus_units = require_child(self.window, QListWidget, "listFocusUnits")
        self.list_focus_units.setIconSize(QSize(16, 16))
        self.search = require_child(self.window, QLineEdit, "editSearch")
        self.status_filter = require_child(self.window, QComboBox, "comboStatusFilter")
        self.stack = require_child(self.window, QStackedWidget, "stackTranslationView")
        self.frame_segment_mode = require_child(self.window, QFrame, "frameSegmentMode")
        self.button_list_mode = require_child(self.window, QToolButton, "buttonListMode")
        self.button_focus_mode = require_child(self.window, QToolButton, "buttonFocusMode")
        self.mode_group = QButtonGroup(self.window)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.button_list_mode)
        self.mode_group.addButton(self.button_focus_mode)

        self.segment_indicator = QFrame(self.frame_segment_mode)
        self.segment_indicator.setObjectName("segmentIndicator")
        self.segment_indicator.setStyleSheet(
            "background-color: palette(highlight); border-radius: 4px;"
        )
        self.segment_indicator.stackUnder(self.button_list_mode)
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
        self.spin_focus_page_size.setValue(self.focus_page_size)

        self.container_scrubber = require_child(self.window, QWidget, "containerFocusPageScrubber")
        self.page_scrubber = RangeScrubberWidget(self.container_scrubber, text_alignment="center")
        layout_scrubber = require_child(self.container_scrubber, QHBoxLayout, "layoutScrubberInner")
        layout_scrubber.addWidget(self.page_scrubber)

        self.edit_key = require_child(self.window, QLineEdit, "editKey")
        self.edit_file = require_child(self.window, QLineEdit, "editFile")
        self.edit_source = require_child(self.window, QPlainTextEdit, "editSource")
        self.edit_translation = require_child(self.window, QPlainTextEdit, "editTranslation")
        self.label_position = require_child(self.window, QLabel, "labelPosition")
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
        self.dock_ai_settings = require_child(self.window, QDockWidget, "dockAiSettings")
        self.action_toggle_ai_panel = require_child(self.window, QAction, "actionToggleAiPanel")
        self.label_source_language_work = require_child(self.window, QLabel, "labelSourceLanguageWork")
        self.button_start_translation = require_child(self.window, QPushButton, "buttonStartTranslation")
        self.button_stop_translation = require_child(self.window, QPushButton, "buttonStopTranslation")
        self.combo_ai_provider = require_child(self.window, QComboBox, "comboAiProvider")
        self.combo_ai_model = require_child(self.window, QComboBox, "comboAiModel")
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
        if header.viewport() is not None:
            header.viewport().installEventFilter(self)
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
        self.frame_target_drop = require_child(self.window, QFrame, "frameDropZone")
        self.list_target_items = require_child(self.window, QListWidget, "listTargetItems")
        self.button_create_project = require_child(self.window, QPushButton, "buttonCreateProject")
        self.list_recent_projects = require_child(self.window, QListWidget, "listRecentProjects")
        self.action_new_project = require_child(self.window, QAction, "actionNewProject")

        self.frame_icon_drop.installEventFilter(self)
        self.frame_target_drop.installEventFilter(self)
        self._init_project_creation_ui()

    def _connect_actions(self) -> None:
        self.action_new_project.triggered.connect(self.show_new_project_page)
        self.action_exit.triggered.connect(self.window.close)

        self.combo_game.currentIndexChanged.connect(self._on_game_selection_changed)
        self.combo_source_language.currentIndexChanged.connect(self._on_source_language_changed)
        self.button_browse_icon.clicked.connect(self._browse_project_icon)
        self.button_clear_icon.clicked.connect(self.clear_project_icon)
        self.button_create_project.clicked.connect(self.create_project)

        self.action_settings.triggered.connect(self.open_settings)
        self.combo_ai_provider.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.combo_ai_model.currentIndexChanged.connect(self._on_ai_model_changed)
        self.action_problems.triggered.connect(self.open_problems_dialog)
        self.action_about.triggered.connect(lambda: SimpleDialogController("AboutDialog.ui", self.window).exec())

        self.action_list_mode.triggered.connect(self.show_list_mode)
        self.action_focus_mode.triggered.connect(self.show_focus_mode)
        self.action_toggle_file_sidebar.triggered.connect(self.toggle_file_sidebar)
        self.list_focus_units.currentRowChanged.connect(self._on_focus_unit_selected)
        self.action_toggle_ai_panel.triggered.connect(self._on_action_toggle_ai_panel_triggered)
        self.dock_ai_settings.visibilityChanged.connect(self._on_dock_ai_visibility_changed)
        self.stack_main.currentChanged.connect(self._on_main_page_changed)

        self.button_start_translation.clicked.connect(self.action_start_translation.trigger)
        self.button_stop_translation.clicked.connect(self.action_stop_translation.trigger)
        self.action_start_translation.changed.connect(lambda: self.button_start_translation.setEnabled(self.action_start_translation.isEnabled()))
        self.action_stop_translation.changed.connect(lambda: self.button_stop_translation.setEnabled(self.action_stop_translation.isEnabled()))
        self.combo_target_language.currentIndexChanged.connect(self._on_target_language_changed)
        self.combo_target_slot.currentIndexChanged.connect(self._on_target_slot_changed)

        self.button_list_mode.clicked.connect(self.show_list_mode)
        self.button_focus_mode.clicked.connect(self.show_focus_mode)
        self.button_previous.clicked.connect(self.previous_entry)
        self.button_next.clicked.connect(self.next_entry)
        self.button_revert.clicked.connect(self.refresh_focus)
        self.button_copy_source.clicked.connect(self.copy_source_to_translation)
        self.button_focus_first.clicked.connect(self.first_focus_page)
        self.button_focus_prev.clicked.connect(self.prev_focus_page)
        self.button_focus_next.clicked.connect(self.next_focus_page)
        self.button_focus_last.clicked.connect(self.last_focus_page)
        self.page_scrubber.page_changed.connect(self.set_focus_page)
        self.spin_focus_page_size.valueChanged.connect(self.on_focus_page_size_changed)
        self._setup_save_button_menu()
        self.button_save_split.clicked.connect(self.save_and_next)

        self.search.textChanged.connect(self.apply_filters)
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.sync_focus_from_table)

        self.edit_translation.textChanged.connect(self.mark_focus_edited)

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
        action_open_plugins.triggered.connect(lambda: self._open_folder(PROJECT_ROOT / "plugins"))
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

    def save_translation(self) -> None:
        adapter = self.plugins.parsers.get(self.project.adapter_id)
        if adapter is None:
            self._restart_target = None
            QMessageBox.warning(self.window, "保存エラー", "このプロジェクトの保存パーサーがありません。")
            return
        selected = QFileDialog.getExistingDirectory(
            self.window, "訳文の出力先フォルダ", str(self.output_path or PROJECT_ROOT),
        )
        if not selected:
            self._restart_target = None
            return
        snapshot = deepcopy(self.imported)
        saved_targets = [(unit.id, unit.target_text) for unit in snapshot.project.units]
        destination = Path(selected)

        def completed(_result: object) -> None:
            self.output_path = destination
            self._saved_targets = saved_targets
            if self._restart_target is not None:
                self.window.close()

        self._run_operation(lambda: export_translation(snapshot, adapter, destination), completed)

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
        close_after_io = self._close_after_io
        self._close_after_io = False
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
        controller = SettingsDialogController(
            self.entrance, self.window, self.ai_provider_id,
            self.ai_models, self.ai_selected_models, self.ai_api_keys, self.ai_concurrency,
        )
        if initial_category is not None:
            controller.select_category(initial_category)
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

    def _refresh_ai_models(self) -> None:
        if self.ai_provider_id not in self.ai_models or not self.ai_models[self.ai_provider_id]:
            defaults = self.provider_registry.get_default_models(self.ai_provider_id)
            if defaults:
                self.ai_models[self.ai_provider_id] = defaults
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

    def _on_ui_language_changed(self, language_code: str) -> None:
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
                with QSignalBlocker(self.combo_source_language):
                    self.combo_source_language.setItemText(0, tr("MainWindow", "自動検出 (Auto Detect)"))
                    for slot in game.slots:
                        index = self.combo_source_language.findData(slot.language_code)
                        if index >= 0:
                            self.combo_source_language.setItemText(index, slot.name)
                with QSignalBlocker(self.combo_target_slot):
                    for slot in game.slots:
                        index = self.combo_target_slot.findData(slot.slot_id)
                        if index >= 0:
                            self.combo_target_slot.setItemText(index, f"{slot.slot_id} ({slot.name})")
                    if not game.slots:
                        self.combo_target_slot.setItemText(0, tr("MainWindow", "該当なし"))
        self._refresh_all_target_labels()
        self.columns = default_translation_table_columns(self.status_text)
        self.columns_by_id = {column.id: column for column in self.columns}
        self.refresh_all()

    def apply_filter_rules_to_units(self) -> None:
        configs: dict[str, AdapterFilterConfig] = {}

        for unit in self.units:
            adapter_id = self.project.adapter_id

            if adapter_id not in configs:
                saved = load_adapter_filter_rules(adapter_id)
                default_cfg = get_default_filter_config(adapter_id, self.plugins.parsers.values())
                configs[adapter_id] = AdapterFilterConfig.from_dict(saved, default_cfg.rules)

            cfg = configs[adapter_id]
            if should_hide_unit(unit, cfg):
                unit.hidden = True

    def _init_project_creation_ui(self) -> None:
        self.combo_game.blockSignals(True)
        self.combo_game.clear()
        for adapter in self.plugins.parsers.values():
            for game in adapter.supported_games:
                self.combo_game.addItem(f"{game.name} ({adapter.name})", (adapter, game))
        self.combo_game.blockSignals(False)

        self.combo_target_language.clear()

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
                layout = self.frame_target_drop.layout()
                if layout is None:
                    raise RuntimeError("Creation slot layout is missing")
                if self.active_creation_panel is not None:
                    previous_adapter = self.active_creation_adapter
                    if previous_adapter is None:
                        raise RuntimeError("Creation panel has no owning adapter")
                    previous_adapter.dispose_creation_panel(self.active_creation_panel)
                if self.creation_context:
                    self.creation_context.active = False
                    self.plugins.bind_creation(self.creation_context.adapter_id, None)
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget() if item is not None else None
                    if widget:
                        widget.hide()
                        widget.deleteLater()
                self.active_adapter = adapter
                self.active_creation_adapter = creation_adapter
                self.creation_context = new_context
                self.active_creation_panel = panel
                layout.addWidget(panel)
                panel.show()

            # 翻訳元言語（原文）: 選択されたゲームのスロットに連動
            with QSignalBlocker(self.combo_source_language):
                current_src = self.combo_source_language.currentData()
                self.combo_source_language.clear()
                self.combo_source_language.addItem(tr("MainWindow", "自動検出 (Auto Detect)"), "auto")
                for slot in game.slots:
                    self.combo_source_language.addItem(slot.name, slot.language_code)
                idx = self.combo_source_language.findData(current_src)
                self.combo_source_language.setCurrentIndex(max(0, idx))

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
        default_slot = game.default_slot_id if game else ""
        self._import_metadata = dict(
            name=self.edit_project_name.text().strip() or "Untitled",
            icon_path=str(self.selected_icon_path or ""),
            game_id=game.id,
            target_language="ja",
            target_file_language=default_slot,
        )
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
        for widget in (self.combo_game, self.combo_source_language,
                       self.edit_project_name, self.list_target_items,
                       self.frame_icon_drop):
            widget.setEnabled(not busy)
        if self.active_creation_panel is not None:
            set_busy = getattr(self.active_creation_panel, "set_busy", None)
            if callable(set_busy):
                set_busy(busy)
            else:
                self.active_creation_panel.setEnabled(not busy)
        self.button_create_project.setEnabled(not busy and self._creation_valid)
        for action in (self.action_new_project, self.action_settings):
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
                    imported.project.target_file_language = game.default_slot_id
        self.load_import(imported)
        self.window.setWindowTitle(f"AutoLingua Desktop - {imported.project.name}")

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
        self.show_list_mode()
        self.action_stop_translation.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_filter.setCurrentText(tr("MainWindow", "未翻訳"))
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
        self._focus_sidebar_visible = layout.sidebar_visible
        if self.stack.currentIndex() == 0:
            self.frame_files.setVisible(False)
            self.action_toggle_file_sidebar.setEnabled(False)
        else:
            self.frame_files.setVisible(self._focus_sidebar_visible)
            self.action_toggle_file_sidebar.setEnabled(True)
            self.action_toggle_file_sidebar.setChecked(self._focus_sidebar_visible)
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
            sidebar_visible=self._focus_sidebar_visible,
            ai_panel_visible=self._ai_dock_workspace_visible,
        ))

    def _on_action_toggle_ai_panel_triggered(self, checked: bool) -> None:
        if self.stack_main.currentIndex() != 0:
            self._ai_dock_workspace_visible = checked
            self.dock_ai_settings.setVisible(checked)

    def _on_dock_ai_visibility_changed(self, visible: bool) -> None:
        if self.stack_main.currentIndex() != 0:
            self._ai_dock_workspace_visible = visible
            self.action_toggle_ai_panel.setChecked(visible)

    def _on_main_page_changed(self, index: int) -> None:
        if index == 0:
            self.dock_ai_settings.setVisible(False)
            self.action_toggle_ai_panel.setEnabled(False)
        else:
            self.action_toggle_ai_panel.setEnabled(True)
            self.action_toggle_ai_panel.setChecked(self._ai_dock_workspace_visible)
            self.dock_ai_settings.setVisible(self._ai_dock_workspace_visible)

    def load_import(self, imported: ImportedTranslation) -> None:
        self.output_path = None
        self.imported = imported
        self.project = imported.project
        self.units = self.project.units
        self._saved_targets = self._target_snapshot()
        self.apply_filter_rules_to_units()
        self.current_unit = self.units[0] if self.units else None
        self.focus_current_page = 1
        self.status_filter.setCurrentText(tr("MainWindow", "未翻訳"))
        self._sync_workspace_language_ui()
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

        src_code = self.project.source_language or "auto"
        src_label = tr("MainWindow", "自動検出") if src_code == "auto" else src_code
        if game:
            for slot in game.slots:
                if slot.language_code == src_code:
                    src_label = slot.name
                    break
        self.label_source_language_work.setText(src_label)

        with QSignalBlocker(self.combo_target_slot):
            self.combo_target_slot.clear()
            if game and game.slots:
                for slot in game.slots:
                    self.combo_target_slot.addItem(f"{slot.slot_id} ({slot.name})", slot.slot_id)
                target_slot = self.project.target_file_language or game.default_slot_id
                idx = self.combo_target_slot.findData(target_slot)
                self.combo_target_slot.setCurrentIndex(max(0, idx))
                self.combo_target_slot.setEnabled(True)
            else:
                self.combo_target_slot.addItem(tr("MainWindow", "該当なし"), "")
                self.combo_target_slot.setEnabled(False)

        with QSignalBlocker(self.combo_target_language):
            if self.project.target_language:
                idx = self.combo_target_language.findData(self.project.target_language)
                if idx >= 0:
                    self.combo_target_language.setCurrentIndex(idx)
                else:
                    self.combo_target_language.setCurrentText(self.project.target_language)

    def _on_target_language_changed(self) -> None:
        data = self.combo_target_language.currentData()
        text = self.combo_target_language.currentText().strip()
        val = str(data) if data else text
        if val:
            self.project.target_language = val

    def _on_target_slot_changed(self) -> None:
        data = self.combo_target_slot.currentData()
        val = str(data) if data else ""
        self.project.target_file_language = val

    def refresh_all(self) -> None:
        self.apply_filters()

    def _ensure_focus_sidebar_minimum_width(self) -> None:
        """ページネーションの桁数に応じてサイドバーの最小幅を更新し、不足していればスプリッターを強制拡張。"""
        btn_w = (
            self.button_focus_first.sizeHint().width()
            + self.button_focus_prev.sizeHint().width()
            + self.button_focus_next.sizeHint().width()
            + self.button_focus_last.sizeHint().width()
        )
        spin_w = max(self.spin_focus_page_size.minimumWidth(), self.spin_focus_page_size.sizeHint().width())
        scrubber_w = self.page_scrubber.minimumWidth()

        layout = self.frame_files.layout()
        if layout is not None:
            margins = layout.contentsMargins()
            margin_w = margins.left() + margins.right()
        else:
            margin_w = 18
        spacing_w = 2 * 5  # layoutFocusPagination spacing=2, 5 gaps

        needed_w = btn_w + spin_w + scrubber_w + spacing_w + margin_w
        self.frame_files.setMinimumWidth(needed_w)

        if self.frame_files.isVisible() and self.frame_files.width() > 0 and self.frame_files.width() < needed_w:
            sizes = self.splitter_main.sizes()
            if sizes:
                diff = needed_w - self.frame_files.width()
                sizes[0] = needed_w
                if len(sizes) > 1:
                    sizes[1] = max(0, sizes[1] - diff)
                self.splitter_main.setSizes(sizes)

    def refresh_focus_unit_list(self) -> None:
        self._syncing_focus_list = True
        try:
            total_pages = self.total_focus_pages()
            self.focus_current_page = max(1, min(total_pages, self.focus_current_page))
            self.page_scrubber.set_pages(self.focus_current_page, total_pages)
            self._ensure_focus_sidebar_minimum_width()

            self.button_focus_first.setEnabled(self.focus_current_page > 1)
            self.button_focus_prev.setEnabled(self.focus_current_page > 1)
            self.button_focus_next.setEnabled(self.focus_current_page < total_pages)
            self.button_focus_last.setEnabled(self.focus_current_page < total_pages)

            self.list_focus_units.clear()
            start = (self.focus_current_page - 1) * self.focus_page_size
            end = min(len(self.filtered_units), start + self.focus_page_size)
            page_units = self.filtered_units[start:end]

            for unit in page_units:
                preview = " ".join(unit.source_text.split())
                if len(preview) > 50:
                    preview = preview[:47] + "..."
                if not preview:
                    preview = f"<{unit.label}>"
                item = QListWidgetItem(preview)
                icon = self._unit_status_icon(unit)
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                source_name = self.source_name_for_unit(unit)
                tooltip = f"キー: {unit.label}\nファイル: {source_name}\n状態: {self.status_text(unit)}\n\n原文:\n{unit.source_text}"
                if unit.target_text:
                    tooltip += f"\n\n訳文:\n{unit.target_text}"
                item.setToolTip(tooltip)
                self.list_focus_units.addItem(item)
            self._sync_focus_list_selection()
        finally:
            self._syncing_focus_list = False

    def total_focus_pages(self) -> int:
        if not self.filtered_units:
            return 1
        return max(1, (len(self.filtered_units) + self.focus_page_size - 1) // self.focus_page_size)

    def set_focus_page(self, page: int) -> None:
        total = self.total_focus_pages()
        new_page = max(1, min(total, page))
        if self.focus_current_page != new_page:
            self.focus_current_page = new_page
            start = (new_page - 1) * self.focus_page_size
            if 0 <= start < len(self.filtered_units):
                self.current_unit = self.filtered_units[start]
                self.refresh_focus(sync_list=False)
            self.refresh_focus_unit_list()

    def first_focus_page(self) -> None:
        self.set_focus_page(1)

    def prev_focus_page(self) -> None:
        self.set_focus_page(self.focus_current_page - 1)

    def next_focus_page(self) -> None:
        self.set_focus_page(self.focus_current_page + 1)

    def last_focus_page(self) -> None:
        self.set_focus_page(self.total_focus_pages())

    def on_focus_page_size_changed(self, size: int) -> None:
        if size > 0 and self.focus_page_size != size:
            self.focus_page_size = size
            if self.current_unit in self.filtered_units:
                idx = self.filtered_units.index(self.current_unit)
                self.focus_current_page = (idx // self.focus_page_size) + 1
            else:
                self.focus_current_page = 1
            self.refresh_focus_unit_list()

    def _unit_status_icon(self, unit: TranslationUnit) -> QIcon | None:
        if unit.hidden or unit.state == UnitState.HIDDEN:
            return self.icon_manager.get_icon("eye-slash")
        if unit.locked or unit.state == UnitState.LOCKED:
            return self.icon_manager.get_icon("lock")
        if unit.issues:
            return self.icon_manager.get_icon("triangle-alert")
        if unit.state == UnitState.DOUBTFUL:
            return self.icon_manager.get_icon("question")
        if unit.state == UnitState.AI_REVIEWED:
            return self.icon_manager.get_icon("robot-check")
        if unit.state == UnitState.HUMAN_REVIEWED:
            return self.icon_manager.get_icon("person-check")
        if unit.state == UnitState.AI_TRANSLATED:
            return self.icon_manager.get_icon("robot-edit")
        if unit.state == UnitState.HUMAN_TRANSLATED:
            return self.icon_manager.get_icon("person-edit-32")
        return self.icon_manager.get_icon("circle")

    def _sync_focus_list_selection(self) -> None:
        if self.current_unit is None or not self.filtered_units:
            self.list_focus_units.clearSelection()
            return
        try:
            global_idx = self.filtered_units.index(self.current_unit)
        except ValueError:
            global_idx = -1
        if global_idx >= 0:
            unit_page = (global_idx // self.focus_page_size) + 1
            if unit_page != self.focus_current_page:
                self.list_focus_units.clearSelection()
                return
            page_idx = global_idx - (self.focus_current_page - 1) * self.focus_page_size
            if self.list_focus_units.currentRow() != page_idx:
                self._syncing_focus_list = True
                try:
                    self.list_focus_units.setCurrentRow(page_idx)
                    item = self.list_focus_units.item(page_idx)
                    if item is not None:
                        self.list_focus_units.scrollToItem(item)
                finally:
                    self._syncing_focus_list = False

    def _on_focus_unit_selected(self, row: int) -> None:
        if self._syncing_focus_list or row < 0:
            return
        global_idx = (self.focus_current_page - 1) * self.focus_page_size + row
        if 0 <= global_idx < len(self.filtered_units):
            unit = self.filtered_units[global_idx]
            if unit is not self.current_unit:
                self.current_unit = unit
                self.refresh_focus(sync_list=False)

    def apply_filters(self) -> None:
        query = self.search.text()
        selected_status = self.status_filter.currentText()

        self.filtered_units = [
            unit
            for unit in self.units
            if unit.matches(query)
            and (selected_status == tr("MainWindow", "すべて") or self.unit_matches_status(unit, selected_status))
        ]
        if self.current_unit in self.filtered_units:
            idx = self.filtered_units.index(self.current_unit)
            self.focus_current_page = (idx // self.focus_page_size) + 1
        else:
            self.focus_current_page = 1
        self.refresh_table()
        self.refresh_focus_unit_list()
        self.refresh_table()
        if self.filtered_units and self.current_unit not in self.filtered_units:
            self.current_unit = self.filtered_units[0]
        elif not self.filtered_units:
            self.current_unit = None
        self.refresh_focus_unit_list()
        self.refresh_focus()

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
        if plugin_id == self.project.adapter_id:
            self._configure_text_presentation()
            self.refresh_focus()
            self.refresh_table()

    def _open_game_color_settings(self) -> None:
        presentation = self._text_presentation
        if presentation is not None and presentation.settings_page_id is not None:
            self.open_settings(presentation.settings_page_id)

    def _expand_display_text(self, text: str) -> str:
        presentation = self._text_presentation
        if self.render_literal_newlines and presentation is not None and presentation.newline_codec is not None:
            return presentation.newline_codec.expand(text)
        return text

    def refresh_table(self) -> None:
        visible_columns = self.visible_columns()
        self.table.clear()
        self.table.setColumnCount(len(visible_columns))
        self.table.setHorizontalHeaderLabels([column.label for column in visible_columns])
        self.table.setRowCount(len(self.filtered_units))
        for row, unit in enumerate(self.filtered_units):
            for column_index, column in enumerate(visible_columns):
                value = column.value_for(unit, self.source_name_for_unit)
                if self.render_literal_newlines and column.id in {"source_text", "target_text"}:
                    value = self._expand_display_text(value)
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, unit)
                self.table.setItem(row, column_index, item)
        self.apply_header_visual_order()
        self.table.resizeColumnsToContents()

    def sync_focus_from_table(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        unit = selected[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(unit, TranslationUnit):
            self.current_unit = unit
            self.refresh_focus()

    def refresh_focus(self, sync_list: bool = True) -> None:
        self._updating_focus = True
        try:
            unit = self.current_unit
            if unit is None:
                self.edit_key.clear()
                self.edit_file.clear()
                self.edit_source.clear()
                self.edit_translation.clear()
                self.label_position.setText("0 / 0")
                if sync_list:
                    self._sync_focus_list_selection()
                return

            position = self.filtered_units.index(unit) + 1 if unit in self.filtered_units else 0
            self.label_position.setText(f"{position} / {len(self.filtered_units)}")
            self.edit_key.setText(unit.label)
            self.edit_file.setText(self.source_name_for_unit(unit))
            source_display = unit.source_text
            target_display = unit.target_text
            source_display = self._expand_display_text(source_display)
            target_display = self._expand_display_text(target_display)
            self.edit_source.setPlainText(source_display)
            self.edit_translation.setPlainText(target_display)
            if sync_list:
                unit_page = ((position - 1) // self.focus_page_size) + 1 if position > 0 else 1
                if unit_page != self.focus_current_page:
                    self.focus_current_page = unit_page
                    self.refresh_focus_unit_list()
                else:
                    self._sync_focus_list_selection()
        finally:
            self._updating_focus = False

    def mark_focus_edited(self) -> None:
        if self._updating_focus or self.current_unit is None:
            return
        new_target = self.edit_translation.toPlainText()
        if new_target == self._expand_display_text(self.current_unit.target_text):
            return  # Syntax formatting also emits textChanged without changing text.
        presentation = self._text_presentation
        if self.render_literal_newlines and presentation is not None and presentation.newline_codec is not None:
            new_target = presentation.newline_codec.collapse(new_target)
        self.current_unit.target_text = new_target
        self.refresh_table()

    def copy_source_to_translation(self) -> None:
        source_text = self.edit_source.toPlainText()
        self.edit_translation.setPlainText(source_text)

    def _setup_save_button_menu(self) -> None:
        menu = QMenu(self.window)

        action_save_next = QAction(self.icon_manager.get_icon("save"), tr("MainWindow", "保存して次へ (人間による翻訳)"), self.window)
        action_save_next.setShortcut("Ctrl+Return")
        action_save_next.triggered.connect(self.save_and_next)
        menu.addAction(action_save_next)

        action_save_stay = QAction(self.icon_manager.get_icon("file"), tr("MainWindow", "保存 (留まる)"), self.window)
        action_save_stay.setShortcut("Ctrl+S")
        action_save_stay.triggered.connect(self.save_stay)
        menu.addAction(action_save_stay)

        menu.addSeparator()

        action_human_trans = QAction(self.icon_manager.get_icon("person-edit-32"), tr("MainWindow", "人間による翻訳として保存"), self.window)
        action_human_trans.triggered.connect(lambda: self.save_with_state(UnitState.HUMAN_TRANSLATED))
        menu.addAction(action_human_trans)

        action_human_rev = QAction(self.icon_manager.get_icon("person-check"), tr("MainWindow", "人間による校閲として保存"), self.window)
        action_human_rev.triggered.connect(lambda: self.save_with_state(UnitState.HUMAN_REVIEWED))
        menu.addAction(action_human_rev)

        action_ai_trans = QAction(self.icon_manager.get_icon("robot-edit"), tr("MainWindow", "AIによる翻訳として保存"), self.window)
        action_ai_trans.triggered.connect(lambda: self.save_with_state(UnitState.AI_TRANSLATED))
        menu.addAction(action_ai_trans)

        action_ai_rev = QAction(self.icon_manager.get_icon("robot-check"), tr("MainWindow", "AIによる校閲として保存"), self.window)
        action_ai_rev.triggered.connect(lambda: self.save_with_state(UnitState.AI_REVIEWED))
        menu.addAction(action_ai_rev)

        action_doubtful = QAction(self.icon_manager.get_icon("question"), tr("MainWindow", "疑問ありとして保存"), self.window)
        action_doubtful.triggered.connect(lambda: self.save_with_state(UnitState.DOUBTFUL))
        menu.addAction(action_doubtful)

        action_locked = QAction(self.icon_manager.get_icon("lock"), tr("MainWindow", "ロックとして保存"), self.window)
        action_locked.triggered.connect(self.save_as_locked)
        menu.addAction(action_locked)

        action_hidden = QAction(self.icon_manager.get_icon("eye-slash"), tr("MainWindow", "非表示として保存"), self.window)
        action_hidden.triggered.connect(self.save_as_hidden)
        menu.addAction(action_hidden)

        menu.addSeparator()

        action_untranslated = QAction(self.icon_manager.get_icon("brush-cleaning"), tr("MainWindow", "未翻訳に戻す"), self.window)
        action_untranslated.triggered.connect(self.save_as_untranslated)
        menu.addAction(action_untranslated)

        self.button_save_split.setMenu(menu)

    def save_and_next(self) -> None:
        self._save_current_unit_changes(next_entry=True)

    def save_stay(self) -> None:
        self._save_current_unit_changes(next_entry=False)

    def save_with_state(self, state: UnitState) -> None:
        if self.current_unit is not None:
            self.current_unit.target_text = self.edit_translation.toPlainText()
            self.current_unit.state = state
            self._after_unit_saved(next_entry=True)

    def save_as_locked(self) -> None:
        if self.current_unit is not None:
            self.current_unit.target_text = self.edit_translation.toPlainText()
            self.current_unit.locked = True
            self.current_unit.state = UnitState.LOCKED
            self._after_unit_saved(next_entry=True)

    def save_as_hidden(self) -> None:
        if self.current_unit is not None:
            self.current_unit.target_text = self.edit_translation.toPlainText()
            self.current_unit.hidden = True
            self.current_unit.state = UnitState.HIDDEN
            self._after_unit_saved(next_entry=True)

    def save_as_untranslated(self) -> None:
        if self.current_unit is not None:
            self.current_unit.state = UnitState.UNTRANSLATED
            self._after_unit_saved(next_entry=True)

    def _save_current_unit_changes(self, next_entry: bool) -> None:
        if self.current_unit is None:
            return
        text = self.edit_translation.toPlainText()
        self.current_unit.target_text = text
        if text.strip():
            self.current_unit.state = UnitState.HUMAN_TRANSLATED
        else:
            self.current_unit.state = UnitState.UNTRANSLATED
        self._after_unit_saved(next_entry=next_entry)

    def _after_unit_saved(self, next_entry: bool) -> None:
        self.refresh_table()
        if self.current_unit in self.filtered_units:
            global_idx = self.filtered_units.index(self.current_unit)
            start = (self.focus_current_page - 1) * self.focus_page_size
            end = start + self.focus_page_size
            if start <= global_idx < end:
                page_idx = global_idx - start
                item = self.list_focus_units.item(page_idx)
                if item is not None:
                    preview = " ".join(self.current_unit.source_text.split())
                    if len(preview) > 50:
                        preview = preview[:47] + "..."
                    if not preview:
                        preview = f"<{self.current_unit.label}>"
                    item.setText(preview)
                    icon = self._unit_status_icon(self.current_unit)
                    if icon is not None and not icon.isNull():
                        item.setIcon(icon)
                    else:
                        item.setIcon(QIcon())
        if next_entry:
            self.next_entry()
        else:
            self.refresh_focus(sync_list=False)

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
        self._animate_segment_indicator(self.button_list_mode)
        # 一覧表示でのファイル表示廃止
        self.frame_files.setVisible(False)
        self.action_toggle_file_sidebar.setEnabled(False)

    def _animate_segment_indicator(self, target_btn: QToolButton) -> None:
        geom = target_btn.geometry()
        if geom.width() <= 0:
            return
        if not self.segment_indicator.isVisible():
            self.segment_indicator.setGeometry(geom)
            self.segment_indicator.show()
            self.segment_indicator.stackUnder(self.button_list_mode)
            return
        self.segment_anim.stop()
        self.segment_anim.setStartValue(self.segment_indicator.geometry())
        self.segment_anim.setEndValue(geom)
        self.segment_anim.start()

    def _sync_segment_indicator_pos(self, animate: bool = True) -> None:
        target_btn = self.button_focus_mode if self.button_focus_mode.isChecked() else self.button_list_mode
        geom = target_btn.geometry()
        if geom.width() <= 0:
            return
        if animate and self.segment_indicator.isVisible():
            self._animate_segment_indicator(target_btn)
        else:
            self.segment_anim.stop()
            self.segment_indicator.setGeometry(geom)
            self.segment_indicator.show()
            self.segment_indicator.stackUnder(self.button_list_mode)

    def _save_display_flags(self) -> None:
        save_ui_display_flags(
            self.render_literal_newlines,
            self.highlight_translation_tags,
            self.apply_color_tags,
        )

    def _on_toggle_render_newlines(self, enabled: bool) -> None:
        self.render_literal_newlines = enabled
        self._save_display_flags()
        self.refresh_focus(sync_list=False)
        self.refresh_table()

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
        if self.current_unit is None and self.filtered_units:
            self.current_unit = self.filtered_units[0]
        self.stack.setCurrentIndex(1)
        self.button_list_mode.setChecked(False)
        self.button_focus_mode.setChecked(True)
        self.action_list_mode.setChecked(False)
        self.action_focus_mode.setChecked(True)
        self._animate_segment_indicator(self.button_focus_mode)
        # 集中表示時は文一覧サイドバーを設定に従って表示
        self.action_toggle_file_sidebar.setEnabled(True)
        self.action_toggle_file_sidebar.setChecked(self._focus_sidebar_visible)
        self.frame_files.setVisible(self._focus_sidebar_visible)
        if self._focus_sidebar_visible:
            self._ensure_focus_sidebar_minimum_width()
        self.refresh_focus()

    def toggle_file_sidebar(self) -> None:
        if self.stack.currentIndex() == 1:
            visible = self.action_toggle_file_sidebar.isChecked()
            self._focus_sidebar_visible = visible
            self.frame_files.setVisible(visible)

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
        if unit.hidden or unit.state == UnitState.HIDDEN:
            return tr("MainWindow", "非表示")
        if unit.locked or unit.state == UnitState.LOCKED:
            return tr("MainWindow", "ロック")
        if unit.issues:
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
            tr("MainWindow", "非表示"): STATUS_MATCHERS["hidden"],
            tr("MainWindow", "ロック"): STATUS_MATCHERS["locked"],
            tr("MainWindow", "問題あり"): STATUS_MATCHERS["has_issues"],
            tr("MainWindow", "疑問あり"): STATUS_MATCHERS["doubtful"],
            tr("MainWindow", "AIによる校閲"): STATUS_MATCHERS["ai_reviewed"],
            tr("MainWindow", "人間による校閲"): STATUS_MATCHERS["human_reviewed"],
            tr("MainWindow", "AIによる翻訳"): STATUS_MATCHERS["ai_translated"],
            tr("MainWindow", "人間による翻訳"): STATUS_MATCHERS["human_translated"],
            tr("MainWindow", "未翻訳"): STATUS_MATCHERS["untranslated"],
        }

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
        self.hide_header_drop_indicator()
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
        if self.table.columnCount() == 0 or header.count() == 0:
            self.hide_header_drop_indicator()
            return

        x = self.header_drop_indicator_x(position)
        h_vp = header.viewport()
        h_height = h_vp.height() if h_vp is not None else header.height()
        self.header_drop_indicator.setGeometry(x - 1, 0, 3, h_height)
        self.header_drop_indicator.raise_()
        self.header_drop_indicator.show()

        t_vp = self.table.viewport()
        if t_vp is not None:
            self.table_drop_indicator.setGeometry(x - 1, 0, 3, t_vp.height())
            self.table_drop_indicator.raise_()
            self.table_drop_indicator.show()

    def hide_header_drop_indicator(self) -> None:
        self._is_header_dragging = False
        self._drag_start_global_pos = None
        if hasattr(self, "header_drop_indicator"):
            self.header_drop_indicator.hide()
        if hasattr(self, "table_drop_indicator"):
            self.table_drop_indicator.hide()

    def header_drop_indicator_x(self, position: QPoint) -> int:
        header = self.table.horizontalHeader()
        x = position.x()
        logical_index = header.logicalIndexAt(x)

        if logical_index < 0:
            if x <= 0:
                first_logical = header.logicalIndex(0)
                return header.sectionViewportPosition(first_logical)
            last_logical = header.logicalIndex(header.count() - 1)
            return header.sectionViewportPosition(last_logical) + header.sectionSize(last_logical)

        section_left = header.sectionViewportPosition(logical_index)
        section_width = header.sectionSize(logical_index)
        section_center = section_left + section_width // 2
        if x < section_center:
            return section_left
        return section_left + section_width
