from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QTextBrowser, QWidget

from autolingua2.services.updates import UpdateDownloader, UpdateInfo
from autolingua2.ui.i18n import tr
from .base import SimpleDialogController, require_child


class UpdateDialogController(SimpleDialogController):
    """更新ダイアログの表示・ダウンロード進捗・終了時適用の制御。"""

    def __init__(
        self,
        info: UpdateInfo,
        parent: QWidget | None = None,
        on_restart_requested: Callable[[], None] | None = None,
    ) -> None:
        super().__init__("dialogs/UpdateDialog.ui", parent)
        self.info = info
        self.on_restart_requested = on_restart_requested
        self.downloader = UpdateDownloader(self.dialog)
        self.downloaded_zip: Path | None = None

        self.label_title = require_child(self.dialog, QLabel, "labelTitle")
        self.label_version = require_child(self.dialog, QLabel, "labelVersion")
        self.text_notes = require_child(self.dialog, QTextBrowser, "textReleaseNotes")
        self.label_progress = require_child(self.dialog, QLabel, "labelProgress")
        self.progress_bar = require_child(self.dialog, QProgressBar, "progressBar")
        self.label_status = require_child(self.dialog, QLabel, "labelStatus")
        self.button_cancel = require_child(self.dialog, QPushButton, "buttonCancel")
        self.button_action = require_child(self.dialog, QPushButton, "buttonAction")

        self.button_cancel.clicked.connect(self._on_cancel_clicked)
        self.button_action.clicked.connect(self._on_action_clicked)

        self.downloader.progress_changed.connect(self._on_download_progress)
        self.downloader.download_completed.connect(self._on_download_completed)
        self.downloader.download_failed.connect(self._on_download_failed)

        self._setup_view()

    def _setup_view(self) -> None:
        self.progress_bar.hide()
        self.label_progress.hide()
        self.label_status.hide()

        if self.info.state == "available":
            self.label_title.setText(tr("UpdateDialog", "新しいバージョンが利用可能です！"))
            current_v = self.info.current_version or "0.1.0"
            latest_v = self.info.latest_version
            self.label_version.setText(
                tr("UpdateDialog", "現在のバージョン: v{current} ──▶ 最新バージョン: v{latest}").format(
                    current=current_v, latest=latest_v
                )
            )
            self.text_notes.setPlainText(self.info.release_notes or tr("UpdateDialog", "リリースノートはありません。"))
            self.text_notes.show()
            self.button_cancel.setText(tr("UpdateDialog", "後で"))
            self.button_action.setText(tr("UpdateDialog", "ダウンロード"))
            self.button_action.setEnabled(bool(self.info.download_url))
            self.button_action.show()
            self.button_cancel.show()

        elif self.info.state == "up_to_date":
            self.label_title.setText(tr("UpdateDialog", "最新バージョンです"))
            current_v = self.info.current_version or "0.1.0"
            self.label_version.setText(
                tr("UpdateDialog", "お使いの AUTOlingua2 (v{current}) は最新バージョンです。").format(
                    current=current_v
                )
            )
            self.text_notes.hide()
            self.button_cancel.hide()
            self.button_action.setText(tr("UpdateDialog", "OK"))
            self.button_action.setEnabled(True)
            self.button_action.show()

        else:
            self.label_title.setText(tr("UpdateDialog", "更新の確認"))
            self.label_version.setText(self.info.message or tr("UpdateDialog", "更新情報の取得に失敗しました。"))
            self.text_notes.hide()
            self.button_cancel.hide()
            self.button_action.setText(tr("UpdateDialog", "OK"))
            self.button_action.setEnabled(True)
            self.button_action.show()

    def _on_action_clicked(self) -> None:
        if self.info.state == "available" and self.downloaded_zip is None:
            # ダウンロード開始
            self.label_title.setText(tr("UpdateDialog", "更新パッケージをダウンロード中…"))
            self.text_notes.hide()
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.label_progress.setText(tr("UpdateDialog", "準備中…"))
            self.label_progress.show()
            self.button_action.hide()
            self.button_cancel.setText(tr("UpdateDialog", "キャンセル"))
            self.downloader.start_download(self.info.download_url)
        elif self.downloaded_zip is not None:
            # 今すぐ終了して更新
            self.downloader.schedule_on_exit(self.downloaded_zip)
            self.dialog.accept()
            if callable(self.on_restart_requested):
                self.on_restart_requested()
            else:
                app = QCoreApplication.instance()
                if app is not None:
                    app.quit()
        else:
            self.dialog.accept()

    def _on_cancel_clicked(self) -> None:
        if self.downloaded_zip is None and self.downloader._reply is not None:
            self.downloader.cancel()
        elif self.downloaded_zip is not None:
            # 作業を続ける: バックグラウンドで終了時更新をスケジュールしておく
            self.downloader.schedule_on_exit(self.downloaded_zip)
        self.dialog.reject()

    def _on_download_progress(self, received: int, total: int) -> None:
        if total > 0:
            percent = int((received / total) * 100)
            self.progress_bar.setValue(percent)
            received_mb = received / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.label_progress.setText(f"{received_mb:.1f} MB / {total_mb:.1f} MB ({percent}%)")
        else:
            received_mb = received / (1024 * 1024)
            self.label_progress.setText(f"{received_mb:.1f} MB")

    def _on_download_completed(self, zip_path: Path) -> None:
        self.downloaded_zip = zip_path
        self.label_title.setText(tr("UpdateDialog", "✔ ダウンロードが完了しました"))
        self.label_progress.hide()
        self.progress_bar.setValue(100)
        self.label_status.setText(
            tr(
                "UpdateDialog",
                "更新パッケージのダウンロードが完了しました。\nアプリを終了した際に自動的に解凍・更新が適用されます。\nこのまま作業を続けても問題ありません。",
            )
        )
        self.label_status.show()
        self.button_cancel.setText(tr("UpdateDialog", "作業を続ける"))
        self.button_cancel.show()
        self.button_action.setText(tr("UpdateDialog", "今すぐ終了して更新"))
        self.button_action.show()

    def _on_download_failed(self, error: str) -> None:
        self.label_title.setText(tr("UpdateDialog", "ダウンロードに失敗しました"))
        self.progress_bar.hide()
        self.label_progress.hide()
        self.label_status.setText(error)
        self.label_status.show()
        self.button_cancel.hide()
        self.button_action.setText(tr("UpdateDialog", "閉じる"))
        self.button_action.show()
