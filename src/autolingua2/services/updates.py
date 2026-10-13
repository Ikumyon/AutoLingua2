"""Both automatic and manual checks use the native update entry point."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Literal

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.infrastructure.platform import current_platform

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    state: Literal["available", "up_to_date", "unavailable"]
    current_version: str
    latest_version: str
    download_url: str
    release_notes: str
    message: str


UpdateStatus = UpdateInfo


def _parse_update_payload(payload: str) -> UpdateInfo:
    try:
        data = json.loads(payload)
        state = data.get("state", "unavailable")
        if state not in ("available", "up_to_date", "unavailable"):
            state = "unavailable"
        return UpdateInfo(
            state=state,
            current_version=str(data.get("current_version", "")),
            latest_version=str(data.get("latest_version", "")),
            download_url=str(data.get("download_url", "")),
            release_notes=str(data.get("release_notes", "")),
            message=str(data.get("message", "")),
        )
    except Exception as exc:
        logger.warning("更新情報の解析に失敗しました: %s", exc)
        return UpdateInfo(
            state="unavailable",
            current_version="",
            latest_version="",
            download_url="",
            release_notes="",
            message="更新情報の解析に失敗しました。",
        )


def check_for_updates() -> UpdateInfo:
    """単一のネイティブ確認窓口を呼び出し、最新の更新状態を取得する。"""
    from autolingua2_native import bootstrap
    raw_status = bootstrap.update_status()
    return _parse_update_payload(raw_status)


def get_startup_update_info() -> UpdateInfo | None:
    """ランチャーから渡された起動時更新情報を取得する。"""
    raw = os.environ.get("AUTOLINGUA_UPDATE_INFO")
    if not raw:
        return None
    info = _parse_update_payload(raw)
    return info if info.state == "available" else None


class UpdateDownloader(QObject):
    """QNetworkAccessManager を用いた非同期更新パッケージダウンロード管理。"""

    progress_changed = Signal(int, int)  # (received_bytes, total_bytes)
    download_completed = Signal(Path)    # (local_zip_path)
    download_failed = Signal(str)        # (error_message)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._output_file: Path | None = None
        self._file_handle = None

    def start_download(self, url_str: str) -> None:
        if self._reply is not None:
            return

        temp_dir = Path(tempfile.gettempdir()) / "autolingua2_update"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self._output_file = temp_dir / "update.zip"

        try:
            self._file_handle = open(self._output_file, "wb")
        except OSError as exc:
            self.download_failed.emit(f"一時ファイルの作成に失敗しました: {exc}")
            return

        request = QNetworkRequest(QUrl(url_str))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, True)
        request.setRawHeader(b"User-Agent", b"AUTOlingua2-Updater")

        reply = self._nam.get(request)
        self._reply = reply
        reply.downloadProgress.connect(self._on_progress)
        reply.readyRead.connect(self._on_ready_read)
        reply.finished.connect(self._on_finished)

    def cancel(self) -> None:
        if self._reply is not None:
            self._reply.abort()
            self._cleanup_file()

    def schedule_on_exit(self, zip_path: Path) -> None:
        """アプリ終了時に新バージョンを解凍・上書き・再起動するよう OS 層へ委譲する。"""
        current_platform.schedule_update_on_exit(zip_path, PROJECT_ROOT)

    def _on_progress(self, received: int, total: int) -> None:
        self.progress_changed.emit(received, total)

    def _on_ready_read(self) -> None:
        if self._reply is not None and self._file_handle is not None:
            data = self._reply.readAll().data()
            if data:
                self._file_handle.write(data)

    def _on_finished(self) -> None:
        if self._reply is None:
            return

        reply = self._reply
        self._reply = None

        if self._file_handle is not None:
            self._file_handle.flush()
            self._file_handle.close()
            self._file_handle = None

        error = reply.error()
        if error != QNetworkReply.NetworkError.NoError:
            self._cleanup_file()
            self.download_failed.emit(reply.errorString())
        else:
            if self._output_file is not None and self._output_file.is_file():
                self.download_completed.emit(self._output_file)
            else:
                self.download_failed.emit("ダウンロードしたファイルが見つかりません。")

        reply.deleteLater()

    def _cleanup_file(self) -> None:
        if self._file_handle is not None:
            try:
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None
        if self._output_file is not None and self._output_file.is_file():
            try:
                self._output_file.unlink(missing_ok=True)
            except Exception:
                pass

