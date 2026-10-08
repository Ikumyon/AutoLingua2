from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable, Mapping
from functools import partial
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, Qt, Signal, QTimer
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.source_watch import WatchTarget
from autolingua2.services.settings_store import SettingsSaveError, load_watch_settings
from autolingua2.services.source_updates import (
    SourceUpdate, apply_watch_settings, register_target, watch_status,
    notifications_available, preview_notification_sound, validate_notification_file,
)
from autolingua2.infrastructure.filesystem import ASSETS_DIR
from autolingua2.ui.operation_worker import OperationWorker
from autolingua2.ui.resource_api import IconAPI
from autolingua2.ui.i18n import tr
from .base import SimpleDialogController, require_child


def notification_pixmap(path: str) -> QPixmap:
    return QPixmap(path or str(ASSETS_DIR / "images/app.png")).scaled(
        48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class SourceWatchTargetDialog(SimpleDialogController):
    def __init__(self, target: WatchTarget, targets: list[WatchTarget], editing: bool, parent: QWidget, icons: IconAPI) -> None:
        super().__init__("dialogs/SourceWatchTargetDialog.ui", parent)
        self.target = deepcopy(target)
        self.original = target
        self.targets = targets
        self.name = require_child(self.dialog, QLineEdit, "editTargetName")
        self.root = require_child(self.dialog, QLineEdit, "editSourceRoot")
        self.name.setText(target.name)
        self.root.setText(target.source_root)
        self.icon = require_child(self.dialog, QLabel, "labelNotificationIcon")
        self.sound = require_child(self.dialog, QLabel, "labelNotificationSound")
        self.dialog.setWindowTitle(tr("SourceWatchTargetDialog", "監視対象を編集" if editing else "監視対象を追加"))
        submit = require_child(self.dialog, QPushButton, "buttonSubmit")
        submit.setText(tr("SourceWatchTargetDialog", "保存" if editing else "追加"))
        submit.clicked.connect(self.accept)
        require_child(self.dialog, QPushButton, "buttonBrowseSourceRoot").clicked.connect(self.browse)
        for name, callback in (
            ("IconChoose", partial(self.choose_file, False)),
            ("IconReset", partial(self.reset_file, False)),
            ("SoundChoose", partial(self.choose_file, True)),
            ("SoundReset", partial(self.reset_file, True)),
            ("SoundPlay", self.play_sound),
        ):
            require_child(self.dialog, QPushButton, "buttonNotification" + name).clicked.connect(callback)
        require_child(self.dialog, QPushButton, "buttonNotificationSoundPlay").setIcon(icons.get_icon("play"))
        try:
            supported = notifications_available()
        except (OSError, ImportError, AttributeError):
            supported = False
        require_child(self.dialog, QGroupBox, "groupNotification").setEnabled(supported)
        self.refresh_notification()

    def browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self.dialog, tr("SourceWatchTargetDialog", "翻訳元フォルダ"), self.root.text())
        if selected:
            self.root.setText(selected)
            if not self.name.text().strip():
                self.name.setText(Path(selected).name)

    def refresh_notification(self) -> None:
        self.icon.setPixmap(notification_pixmap(self.target.icon_path))
        self.icon.setToolTip(self.target.icon_path)
        self.sound.setText(tr("SourceWatchTargetDialog", "通知音：{name}").format(
            name=Path(self.target.sound_path).name if self.target.sound_path else tr("SourceWatchTargetDialog", "標準")))
        self.sound.setToolTip(self.target.sound_path)

    def choose_file(self, sound: bool) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self.dialog, tr("SourceWatchTargetDialog", "通知音" if sound else "通知画像"),
            self.target.sound_path if sound else self.target.icon_path,
            "WAV (*.wav)" if sound else "Images (*.png *.jpg *.jpeg)")
        if not selected:
            return
        try:
            path = validate_notification_file(selected, sound=sound)
            if sound:
                self.target.sound_path = path
            else:
                if QPixmap(path).isNull():
                    raise ValueError("通知画像を読み込めません。")
                self.target.icon_path = path
            self.refresh_notification()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.dialog, tr("SourceWatchTargetDialog", "通知設定エラー"), str(exc))

    def reset_file(self, sound: bool) -> None:
        if sound:
            self.target.sound_path = ""
        else:
            self.target.icon_path = ""
        self.refresh_notification()

    def play_sound(self) -> None:
        try:
            preview_notification_sound(self.target.sound_path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.dialog, tr("SourceWatchTargetDialog", "通知音エラー"), str(exc))

    def accept(self) -> None:
        try:
            if not self.root.text().strip() or not self.name.text().strip():
                raise ValueError("名前と翻訳元フォルダを指定してください。")
            root = Path(self.root.text().strip()).resolve()
            if any(entry is not self.original and entry.source_root == str(root) for entry in self.targets):
                raise ValueError("この翻訳元フォルダは登録済みです。")
            validated = register_target(root, self.name.text().strip(), self.target.suffixes)
            self.target.name = validated.name
            self.target.source_root = validated.source_root
            if self.target.source_root != self.original.source_root:
                self.target.project_path = ""
            self.dialog.accept()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.dialog, tr("SourceWatchTargetDialog", "監視設定エラー"), str(exc))


class WatchPageController(QObject):
    update_requested = Signal(str)

    def __init__(self, dialog: QDialog, parsers: Mapping[str, FileAdapter], icons: IconAPI) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.parsers = parsers
        self.icons = icons
        self.settings = load_watch_settings()
        self.worker: OperationWorker | None = None
        self.cards: dict[str, QWidget] = {}
        self.targets_widget = require_child(dialog, QWidget, "widgetSourceWatchTargets")
        self.targets_layout = require_child(dialog, QVBoxLayout, "layoutSourceWatchTargets")
        self.label = require_child(dialog, QLabel, "labelSourceWatchStatus")
        self.toggle = require_child(dialog, QPushButton, "buttonSourceWatchToggle")
        self.toggle.clicked.connect(self.toggle_enabled)
        require_child(dialog, QPushButton, "buttonSourceWatchAdd").clicked.connect(self.add)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        dialog.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.dialog and self.worker is not None and isinstance(event, QCloseEvent):
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def refresh(self) -> None:
        if self.worker is not None:
            return
        while self.targets_layout.count():
            item = self.targets_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.hide()
                    widget.deleteLater()
        self.cards.clear()
        running = False
        state: dict[str, object] = {}
        status_error = ""
        try:
            running, state = watch_status()
        except (OSError, ImportError, AttributeError, ValueError) as exc:
            status_error = str(exc)
        self.label.setText(status_error or tr("SettingsDialog", "監視状態：{state}").format(
            state=tr("SettingsDialog", "監視中" if running else "停止中")))
        indicator = require_child(self.dialog, QLabel, "labelSourceWatchIndicator")
        indicator.setProperty("watchState", "error" if status_error else "running" if running else "stopped")
        indicator.setText("!" if status_error else "")
        style = indicator.style()
        if style is None:
            raise RuntimeError("監視状態のスタイルを取得できません。")
        style.unpolish(indicator)
        style.polish(indicator)
        indicator.update()
        self.toggle.setText(tr("SettingsDialog", "監視を停止" if self.settings.enabled else "監視を開始"))
        self.toggle.setIcon(self.icons.get_icon("stop" if self.settings.enabled else "play"))
        errors = 0
        pending_count = 0
        for target in self.settings.targets:
            value = state.get(target.source_root)
            data = value if isinstance(value, dict) else {}
            error = str(data.get("error") or data.get("notification_error") or "")
            pending = data.get("current") is not None and data.get("current") != data.get("baseline")
            errors += bool(error)
            pending_count += pending
            card = QFrame(self.targets_widget)
            card.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QGridLayout(card)
            icon = QLabel(card)
            icon.setPixmap(notification_pixmap(target.icon_path))
            icon.setFixedSize(48, 48)
            layout.addWidget(icon, 0, 0, 2, 1)
            name = QLabel(target.name, card)
            name.setObjectName("sourceWatchTitle")
            name.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(name, 0, 1)
            status = tr("SettingsDialog", "エラー" if error else "監視中" if running else "停止中")
            status_widget = QWidget(card)
            status_layout = QHBoxLayout(status_widget)
            status_layout.setContentsMargins(0, 0, 0, 0)
            status_layout.setSpacing(6)
            status_indicator = QLabel(status_widget)
            status_indicator.setObjectName("sourceWatchIndicator")
            status_indicator.setFixedSize(14, 14)
            status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_indicator.setProperty("watchState", "error" if error else "running" if running else "stopped")
            status_indicator.setText("!" if error else "")
            status_layout.addWidget(status_indicator)
            status_layout.addWidget(QLabel(status, status_widget))
            layout.addWidget(status_widget, 0, 2)
            path = QLabel(target.source_root, card)
            path.setTextFormat(Qt.TextFormat.PlainText)
            path.setWordWrap(True)
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(path, 1, 1, 1, 2)
            if error:
                message = QLabel(error, card)
                message.setTextFormat(Qt.TextFormat.PlainText)
                message.setWordWrap(True)
                layout.addWidget(message, 2, 1, 1, 2)
            actions = QHBoxLayout()
            actions.addStretch()
            if error:
                details = QPushButton(tr("SettingsDialog", "詳細を見る"), card)
                details.clicked.connect(partial(self.show_error, error))
                actions.addWidget(details)
            if pending and self.settings.enabled:
                update = QPushButton(tr("SettingsDialog", "更新内容を確認"), card)
                update.clicked.connect(partial(self.request_update, target.source_root))
                actions.addWidget(update)
            for title, icon_name, callback in (
                ("編集", "pencil", partial(self.edit, target)),
                ("削除", "trash", partial(self.remove, target)),
            ):
                button = QPushButton(tr("SettingsDialog", title), card)
                button.setIcon(self.icons.get_icon(icon_name))
                button.clicked.connect(callback)
                actions.addWidget(button)
            layout.addLayout(actions, 3, 0, 1, 3)
            layout.setColumnStretch(1, 1)
            self.targets_layout.addWidget(card)
            self.cards[target.source_root] = card
        if not self.settings.targets:
            self.targets_layout.addWidget(QLabel(tr("SettingsDialog", "監視対象は登録されていません。"), self.targets_widget))
        for name, text, count in (
            ("Target", "登録対象：{count}件", len(self.settings.targets)),
            ("Error", "エラー：{count}件", errors),
            ("Pending", "未反映の更新：{count}件", pending_count),
        ):
            require_child(self.dialog, QLabel, "labelSourceWatch" + name + "Count").setText(
                tr("SettingsDialog", text).format(count=count))

    def show_error(self, error: str) -> None:
        QMessageBox.warning(self.dialog, tr("SettingsDialog", "監視・通知エラー"), error)

    def request_update(self, project: str) -> None:
        def requested() -> None:
            self.update_requested.emit(project)
            self.dialog.reject()
        self.save(requested)

    def toggle_enabled(self) -> None:
        self.settings.enabled = not self.settings.enabled
        self.persist()

    def persist(self) -> None:
        self.save(self.refresh)

    def select_project(self, project: str) -> None:
        card = self.cards.get(project)
        if card is not None:
            card.setFocus()
            from PySide6.QtWidgets import QScrollArea
            page = require_child(self.dialog, QScrollArea, "SettingsFilePage")
            page.ensureWidgetVisible(card)

    def add(self) -> None:
        suffixes = sorted({suffix for adapter in self.parsers.values() for suffix in adapter.suffixes})
        self.edit_target(WatchTarget("", "", "", suffixes), False)

    def edit(self, target: WatchTarget) -> None:
        self.edit_target(target, True)

    def edit_target(self, target: WatchTarget, editing: bool) -> None:
        controller = SourceWatchTargetDialog(target, self.settings.targets, editing, self.dialog, self.icons)
        try:
            if controller.exec() != QDialog.DialogCode.Accepted:
                return
            if editing:
                self.settings.targets[self.settings.targets.index(target)] = controller.target
            else:
                self.settings.targets.append(controller.target)
            self.persist()
        finally:
            controller.dialog.deleteLater()

    def remove(self, target: WatchTarget) -> None:
        self.settings.targets.remove(target)
        self.persist()

    def save(self, accepted: Callable[[], None]) -> None:
        if self.worker is not None:
            return
        settings = deepcopy(self.settings)
        if settings == load_watch_settings():
            accepted()
            return
        self.dialog.setEnabled(False)
        worker = OperationWorker(lambda: apply_watch_settings(settings), self.dialog)
        self.worker = worker

        def completed() -> None:
            self.worker = None
            self.dialog.setEnabled(True)
            if worker.error is not None:
                error = worker.error
                logging.getLogger(__name__).error("Watcher operation failed", exc_info=(type(error), error, error.__traceback__))
                message = (
                    tr("SettingsDialog", "設定ファイルを保存できませんでした。\n保存先：{path}").format(path=error.path)
                    if isinstance(error, SettingsSaveError) else
                    tr("SettingsDialog", "監視設定を反映できませんでした。ネイティブモジュールとデーモンのビルドを確認してください。")
                )
                QMessageBox.warning(self.dialog, tr("SettingsDialog", "監視設定エラー"), message)
                self.settings = load_watch_settings()
                self.refresh()
            else:
                accepted()

        worker.finished.connect(completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()



class SourceUpdateDialog(SimpleDialogController):
    def __init__(self, update: SourceUpdate, parent: QWidget) -> None:
        super().__init__("dialogs/SourceUpdateDialog.ui", parent)
        self.update = update
        self.visible_changes = list(update.changes)
        require_child(self.dialog, QLabel, "labelProject").setText(update.target.name)
        # The watcher has no persisted detection timestamp.
        require_child(self.dialog, QLabel, "labelDetectedAt").hide()
        self.list = require_child(self.dialog, QListWidget, "listChanges")
        self.list.currentRowChanged.connect(self.select_change)
        for name, kind in (("All", ""), ("Added", "追加"), ("Modified", "変更"), ("Deleted", "削除")):
            count = len(update.changes) if not kind else sum(change.kind == kind for change in update.changes)
            button = require_child(self.dialog, QPushButton, "buttonFilter" + name)
            title = tr("SourceUpdateDialog", kind or "すべて")
            button.setText(f"{title} {count}")
            button.clicked.connect(partial(self.filter_changes, kind))
        require_child(self.dialog, QPushButton, "buttonApply").clicked.connect(self.dialog.accept)
        self.filter_changes("")

    def filter_changes(self, kind: str) -> None:
        self.visible_changes = [change for change in self.update.changes if not kind or change.kind == kind]
        self.list.clear()
        for change in self.visible_changes:
            self.list.addItem(f"{tr('SourceUpdateDialog', change.kind)}  {change.unit_id}")
        if self.visible_changes:
            self.list.setCurrentRow(0)
        else:
            self.select_change(-1)

    def select_change(self, row: int) -> None:
        change = self.visible_changes[row] if 0 <= row < len(self.visible_changes) else None
        require_child(self.dialog, QLabel, "labelChangeId").setText(
            f"ID：{change.unit_id}" if change is not None else "ID：—")
        require_child(self.dialog, QPlainTextEdit, "textBefore").setPlainText(change.before if change is not None else "")
        require_child(self.dialog, QPlainTextEdit, "textAfter").setPlainText(change.after if change is not None else "")
        require_child(self.dialog, QLabel, "labelBeforeTitle").setText(tr(
            "SourceUpdateDialog", "削除前の原文" if change is not None and change.kind == "削除" else "変更前"))
        require_child(self.dialog, QLabel, "labelAfterTitle").setText(tr(
            "SourceUpdateDialog", "原文" if change is not None and change.kind == "追加" else "変更後"))
