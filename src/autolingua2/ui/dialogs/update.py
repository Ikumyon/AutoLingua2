from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def find_updater_executable() -> Path | None:
    exe_name = "autolingua-updater.exe" if sys.platform == "win32" else "autolingua-updater"
    candidates = [
        PROJECT_ROOT / "core" / exe_name,
        PROJECT_ROOT / "target" / "release" / exe_name,
        PROJECT_ROOT / "target" / "debug" / exe_name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


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
        updater_exe = find_updater_executable()
        if updater_exe is None:
            self.failed_check.emit("アップデーター実行ファイル (autolingua-updater) が見つかりません。")
            return

        cmd = [str(updater_exe), "check", "--project-root", str(PROJECT_ROOT),
               "--current-version", __version__]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                creationflags=creationflags,
                cwd=str(PROJECT_ROOT),
            )
            stdout = result.stdout.strip()
            if not stdout:
                self.failed_check.emit(result.stderr.strip() or "更新確認からの応答がありません。")
                return

            data = json.loads(stdout)
            if not isinstance(data, dict):
                self.failed_check.emit("更新確認からの応答がJSONオブジェクトではありません。")
                return
            error = data.get("error")
            if result.returncode != 0 or error:
                detail = error if isinstance(error, str) and error else result.stderr.strip()
                self.failed_check.emit(detail or f"更新確認に失敗しました（終了コード: {result.returncode}）。")
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

    def start_check(self) -> None:
        self.stack_update.setCurrentWidget(self.page_checking)
        self._worker = UpdateCheckWorker(self)
        self._worker.finished_check.connect(self._on_check_finished)
        self._worker.failed_check.connect(self._on_check_failed)
        self._worker.start()

    def _on_check_finished(self, data: dict) -> None:
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

    def _on_check_failed(self, error_message: str) -> None:
        self.text_error_detail.setPlainText(error_message)
        self.stack_update.setCurrentWidget(self.page_error)

    def _on_download_clicked(self) -> None:
        updater_exe = find_updater_executable()
        if updater_exe is None:
            self._on_check_failed("アップデーター実行ファイルが見つかりません。")
            return

        cmd = [
            str(updater_exe),
            "gui",
            "--project-root",
            str(PROJECT_ROOT),
            "--parent-pid",
            str(os.getpid()),
        ]

        if self._update_data:
            if url := self._update_data.get("download_url"):
                cmd.extend(["--download-url", str(url)])
            if cur_ver := self._update_data.get("current_version"):
                cmd.extend(["--current-version", str(cur_ver)])
            if new_ver := self._update_data.get("latest_version"):
                cmd.extend(["--new-version", str(new_ver)])
            if sha := self._update_data.get("sha256"):
                cmd.extend(["--sha256", str(sha)])

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

        # アップデーターを別プロセスとして起動
        subprocess.Popen(
            cmd,
            creationflags=creationflags,
            cwd=str(PROJECT_ROOT),
            close_fds=True,
        )

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
