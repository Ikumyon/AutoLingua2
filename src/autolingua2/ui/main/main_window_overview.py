from __future__ import annotations

from autolingua2.ui.resources.i18n import translation_source

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QGroupBox, QHeaderView, QLabel, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from autolingua2.ir import UnitState
from autolingua2.ui.components.status_donut import STATUS_LABELS, StatusDonut
from autolingua2.ui.dialogs.base import require_child
from autolingua2.ui.resources.i18n import tr
from autolingua2.ui.main.language_names import workspace_language_name

if TYPE_CHECKING:
    from autolingua2.ui.main.main_window import MainWindowController


class OverviewController(QObject):
    """Display workspace snapshots and select the active workspace."""

    def __init__(self, host: MainWindowController) -> None:
        super().__init__(host)
        self.host = host
        window = host.window
        self.workspaces = require_child(window, QTableWidget, "tableDashboardWorkspaces")
        self.statuses = require_child(window, QTableWidget, "tableDashboardStatuses")
        self.project_name = require_child(window, QLabel, "labelDashboardProjectName")
        self.source_language = require_child(window, QLabel, "labelDashboardSourceLanguage")
        self.file_count = require_child(window, QLabel, "labelDashboardFileCount")
        self.source_count = require_child(window, QLabel, "labelDashboardSourceUnitCount")
        self.selected_workspace = require_child(window, QLabel, "labelDashboardSelectedWorkspace")
        self.detail = require_child(window, QGroupBox, "groupDashboardWorkspaceDetail")
        self.source_changed = require_child(window, QLabel, "labelDashboardSourceChanged")
        chart_area = require_child(window, QWidget, "widgetDashboardStatusChart")
        chart_layout = chart_area.layout()
        if not isinstance(chart_layout, QVBoxLayout):
            raise TypeError("Overview chart requires its vertical layout")
        self.chart = StatusDonut(chart_area)
        chart_layout.insertWidget(1, self.chart, 0, Qt.AlignmentFlag.AlignCenter)
        self.workspaces.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.workspaces.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            self.workspaces.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.statuses.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.statuses.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._dirty = True
        self._selected_state: UnitState | None = None
        self._selection_workspace: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self.refresh)
        self.workspaces.currentCellChanged.connect(self._workspace_selected)
        self.statuses.cellClicked.connect(self._status_clicked)
        self.chart.state_clicked.connect(self._chart_clicked)
        require_child(window, QPushButton, "buttonDashboardAddLanguage").clicked.connect(host._open_workspace_languages)

    def _visible(self) -> bool:
        return (self.host.stack.currentWidget() is self.host.page_dashboard
                and self.host.stack_main.currentWidget() is self.host.page_workspace)

    def invalidate(self) -> None:
        self._dirty = True
        if self._visible() and not self._timer.isActive():
            self._timer.start()

    def enter(self) -> None:
        self._timer.stop()
        self.refresh(reveal=True)

    def leave(self) -> None:
        self._timer.stop()
        self._set_selected_state(None, animate=False)
        self.chart.stop_animation()

    def refresh(self, *, reveal: bool = False) -> None:
        if not self._visible() or (not self._dirty and not reveal):
            return
        self._dirty = False
        host = self.host
        service = host.workspace_service
        project = service.imported.project
        summaries = service.summaries()
        self.project_name.setText(project.name or tr("MainWindow", "名称未設定"))
        language = workspace_language_name(service, project.source_language) if project.source_language in service.languages else project.source_language
        self.source_language.setText(tr("MainWindow", "原文：{language}").format(language=language or "—"))
        self.file_count.setText(tr("MainWindow", "ファイル：{count}").format(count=f"{len(project.sources):,}"))
        source_count = sum(unit.id not in service.imported.excluded_unit_ids for unit in project.units)
        self.source_count.setText(tr("MainWindow", "原文件数：{count}").format(count=f"{source_count:,}"))
        self.workspaces.setHorizontalHeaderLabels([tr("MainWindow", label) for label in
                                                  (translation_source('MainWindow', "言語"), translation_source('MainWindow', "翻訳進捗"), translation_source('MainWindow', "未翻訳"), translation_source('MainWindow', "確認済み"), translation_source('MainWindow', "要確認"))])
        active_code = host.active_workspace.language_code if host.active_workspace is not None else None
        if active_code != self._selection_workspace:
            self._selection_workspace = active_code
            self._set_selected_state(None, animate=False)
        selected_row = -1
        with QSignalBlocker(self.workspaces):
            self.workspaces.setRowCount(len(summaries))
            for row, summary in enumerate(summaries):
                item = QTableWidgetItem(f"{workspace_language_name(service, summary.language_code)} ({summary.language_code})")
                item.setData(Qt.ItemDataRole.UserRole, summary.language_code)
                self.workspaces.setItem(row, 0, item)
                progress = QProgressBar(self.workspaces)
                progress.setRange(0, 1000)
                progress.setValue(round(summary.progress * 1000))
                progress.setFormat(f"{summary.progress * 100:.1f}%")
                self.workspaces.setCellWidget(row, 1, progress)
                for column, count in enumerate((summary.counts[UnitState.UNTRANSLATED], summary.reviewed,
                                                 summary.counts[UnitState.DOUBTFUL]), start=2):
                    self.workspaces.setItem(row, column, QTableWidgetItem(f"{count:,}"))
                if summary.language_code == active_code:
                    selected_row = row
            self.workspaces.setCurrentCell(selected_row, 0)
        selected = next((summary for summary in summaries if summary.language_code == active_code), None)
        self.detail.setEnabled(selected is not None)
        self.selected_workspace.setText(tr("MainWindow", "ワークスペースを選択してください") if selected is None else
                                        workspace_language_name(service, selected.language_code))
        counts = selected.counts if selected is not None else dict.fromkeys(UnitState, 0)
        total = selected.total if selected is not None else 0
        self.statuses.setHorizontalHeaderLabels([tr("MainWindow", label) for label in (translation_source('MainWindow', "ステータス"), translation_source('MainWindow', "件数"), translation_source('MainWindow', "割合"))])
        for row, state in enumerate(UnitState):
            name = QTableWidgetItem("● " + tr("MainWindow", STATUS_LABELS[state]))
            name.setForeground(QBrush(self.chart.state_color(state)))
            self.statuses.setItem(row, 0, name)
            self.statuses.setItem(row, 1, QTableWidgetItem(f"{counts[state]:,}"))
            self.statuses.setItem(row, 2, QTableWidgetItem(f"{counts[state] / total * 100 if total else 0:.1f}%"))
        changed = selected.source_changed if selected is not None else 0
        self.source_changed.setText(tr("MainWindow", "原文更新：{count}件").format(count=f"{changed:,}"))
        self.chart.set_counts(counts, reveal=reveal)
        self._sync_selected_row()

    def _sync_selected_row(self) -> None:
        with QSignalBlocker(self.statuses):
            self.statuses.clearSelection()
            if self._selected_state is None:
                self.statuses.setCurrentCell(-1, -1)
            else:
                row = tuple(UnitState).index(self._selected_state)
                self.statuses.setCurrentCell(row, 0)
                self.statuses.selectRow(row)

    def _set_selected_state(self, state: UnitState | None, *, animate: bool = True) -> None:
        self._selected_state = state
        self.chart.set_selected_state(state, animate=animate)
        self._sync_selected_row()

    def _status_clicked(self, row: int, column: int) -> None:
        self._chart_clicked(tuple(UnitState)[row])

    def _chart_clicked(self, state: object) -> None:
        if state is not None and not isinstance(state, UnitState):
            raise TypeError("Overview chart selection must be a translation state")
        if self.host.active_workspace is None or not self.detail.isEnabled():
            return
        self._set_selected_state(None if state == self._selected_state else state)

    def _workspace_selected(self, row: int, column: int, previous_row: int, previous_column: int) -> None:
        if row < 0:
            return
        item = self.workspaces.item(row, 0)
        if item is None:
            raise RuntimeError("Overview workspace row has no language")
        code = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(code, str):
            raise TypeError("Overview workspace language must be a string")
        if self.host.active_workspace is not None and self.host.active_workspace.language_code == code:
            return
        self.host._select_workspace(code)
        self.host._refresh_workspace_selection()
        self.refresh()

