from __future__ import annotations

from autolingua2.infrastructure.automation_activity import activity_callback, observe_async

import json

from autolingua2_native import platform as native_platform

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from autolingua2 import __version__
from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.ui.dialogs import load_ui, require_child


def format_bytes_human(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024 * 1024):.1f} GB"
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


class UpdateCheckWorker(QThread):
    finished_check = Signal(dict)
    failed_check = Signal(str)

    def run(self) -> None:
        try:
            returncode, stdout, stderr = native_platform.check_update(str(PROJECT_ROOT), __version__)
            stdout = stdout.strip()
            if not stdout:
                self.failed_check.emit(stderr.strip() or "更新確認からの応答がありません。")
                return

            data = json.loads(stdout)
            if not isinstance(data, dict):
                self.failed_check.emit("更新確認からの応答がJSONオブジェクトではありません。")
                return
            error = data.get("error")
            if returncode != 0 or error:
                detail = error if isinstance(error, str) and error else stderr.strip()
                self.failed_check.emit(detail or f"更新確認に失敗しました（終了コード: {returncode}）。")
                return
            if not isinstance(data.get("has_update"), bool) or not isinstance(data.get("current_version"), str):
                self.failed_check.emit("更新確認からの応答に必要なバージョン情報がありません。")
                return
            self.finished_check.emit(data)
        except Exception as e:
            self.failed_check.emit(f"更新確認処理の実行に失敗しました: {e}")


class UpdateDialogController(QObject):
    def __init__(self, parent: QWidget | None = None, initial_data: dict | None = None) -> None:
        super().__init__(parent)
        widget = load_ui("dialogs/UpdateDialog.ui")
        if not isinstance(widget, QDialog):
            raise TypeError("UpdateDialog.ui は QDialog ではありません")

        self.dialog = widget
        self._initial_data = initial_data
        self._update_data: dict | None = initial_data
        self._worker: UpdateCheckWorker | None = None

        # ウィジェットの取得
        self.stack_update = require_child(self.dialog, QStackedWidget, "stackUpdate")
        self.page_checking = require_child(self.dialog, QWidget, "pageChecking")
        self.label_checking_version = require_child(self.dialog, QLabel, "labelCheckingVersion")
        self.button_close_checking = require_child(self.dialog, QPushButton, "buttonCloseChecking")

        self.page_available = require_child(self.dialog, QWidget, "pageAvailable")
        self.label_current_version = require_child(self.dialog, QLabel, "labelCurrentVersion")
        self.label_latest_version = require_child(self.dialog, QLabel, "labelLatestVersion")
        self.label_published_at = require_child(self.dialog, QLabel, "labelPublishedAt")
        self.label_download_size = require_child(self.dialog, QLabel, "labelDownloadSize")
        self.text_release_notes = require_child(self.dialog, QPlainTextEdit, "textReleaseNotes")
        self.button_later = require_child(self.dialog, QPushButton, "buttonLater")
        self.button_download = require_child(self.dialog, QPushButton, "buttonDownload")

        self.page_latest = require_child(self.dialog, QWidget, "pageLatest")
        self.label_installed_version = require_child(self.dialog, QLabel, "labelInstalledVersion")
        self.button_close_latest = require_child(self.dialog, QPushButton, "buttonCloseLatest")

        self.page_error = require_child(self.dialog, QWidget, "pageError")
        self.text_error_detail = require_child(self.dialog, QPlainTextEdit, "textErrorDetail")
        self.button_close_error = require_child(self.dialog, QPushButton, "buttonCloseError")
        self.button_retry = require_child(self.dialog, QPushButton, "buttonRetry")

        self._connect_signals()

    def _connect_signals(self) -> None:
        self.button_close_checking.clicked.connect(self.dialog.reject)
        self.button_close_latest.clicked.connect(self.dialog.reject)
        self.button_close_error.clicked.connect(self.dialog.reject)
        self.button_later.clicked.connect(self.dialog.reject)
        self.button_retry.clicked.connect(self.start_check)
        self.button_download.clicked.connect(self._on_download_clicked)

    @observe_async("アプリの更新確認", lambda self: self._checking, owner=lambda self: self.dialog)
    def start_check(self) -> None:
        self._checking = True
        self.stack_update.setCurrentWidget(self.page_checking)
        self._worker = UpdateCheckWorker(self)
        self._worker.finished_check.connect(self._on_check_finished)
        self._worker.failed_check.connect(self._on_check_failed)
        self._worker.start()

    @activity_callback
    def _on_check_finished(self, data: dict) -> None:
        self._checking = False
        self._update_data = data
        has_update = data.get("has_update", False)
        current_version = data.get("current_version", "—")
        self.label_checking_version.setText(current_version)

        if has_update:
            self.label_current_version.setText(current_version)
            self.label_latest_version.setText(data.get("latest_version", "—"))
            self.label_published_at.setText(data.get("published_at") or "—")
            download_size = data.get("download_size")
            size_str = format_bytes_human(download_size) if isinstance(download_size, int) else "—"
            self.label_download_size.setText(size_str)
            self.text_release_notes.setPlainText(data.get("release_notes") or "")
            self.stack_update.setCurrentWidget(self.page_available)
        else:
            self.label_installed_version.setText(current_version)
            self.stack_update.setCurrentWidget(self.page_latest)

    @activity_callback
    def _on_check_failed(self, error_message: str) -> None:
        self._checking = False
        activity = getattr(self, "_automation_activity", None)
        if activity is not None:
            activity.finish("failed", error_message)
        self.text_error_detail.setPlainText(error_message)
        self.stack_update.setCurrentWidget(self.page_error)

    def _on_download_clicked(self) -> None:
        cmd: list[str] = []

        if self._update_data:
            if url := self._update_data.get("download_url"):
                cmd.extend(["--download-url", str(url)])
            if cur_ver := self._update_data.get("current_version"):
                cmd.extend(["--current-version", str(cur_ver)])
            if new_ver := self._update_data.get("latest_version"):
                cmd.extend(["--new-version", str(new_ver)])
            if sha := self._update_data.get("sha256"):
                cmd.extend(["--sha256", str(sha)])

        try:
            native_platform.start_update(str(PROJECT_ROOT), cmd)
        except Exception as error:
            self._on_check_failed(f"アップデーターの起動に失敗しました: {error}")
            return

        # 本体側ダイアログを閉じてアプリを終了
        self.dialog.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def exec(self) -> int:
        if self._initial_data is not None:
            self._on_check_finished(self._initial_data)
        else:
            self.start_check()
        return self.dialog.exec()
