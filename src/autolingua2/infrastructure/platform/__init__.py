from __future__ import annotations

import atexit
import os
from pathlib import Path
import subprocess
import sys

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from .base import ConsoleResult, PlatformDriver, ProcessGuard


def _native():
    # One canonical namespace. No Python reimplementation of Win32 APIs.
    from autolingua2_native import platform
    return platform


def log_directory() -> Path:
    return PROJECT_ROOT / "logs"


class SystemPlatformDriver:
    def __init__(self) -> None:
        self._console = ConsoleResult("unavailable")
        self._restarting = False
        self._pause_registered = False

    def allocate_debug_console(self) -> ConsoleResult:
        if self._console.state != "unavailable":
            return self._console
        try:
            state, error = _native().allocate_debug_console()
            if state not in {"owned", "attached", "existing", "unavailable"}:
                raise RuntimeError("Invalid native console state")
            result = ConsoleResult(state, error)
            if state != "unavailable" and sys.platform == "win32":
                # AllocConsole does not recreate CPython's windowed streams.
                streams = []
                try:
                    streams.append(open("CONIN$", "r", encoding="utf-8"))
                    streams.append(open("CONOUT$", "w", encoding="utf-8", buffering=1))
                    streams.append(open("CONOUT$", "w", encoding="utf-8", buffering=1))
                except Exception:
                    for stream in streams:
                        stream.close()
                    raise
                sys.stdin, sys.stdout, sys.stderr = streams
            self._console = result
        except Exception as exc:
            self._console = ConsoleResult("unavailable", f"{type(exc).__name__}: {exc}")
        if self._console.state == "owned" and not self._pause_registered:
            atexit.register(self.pause_console_on_exit)
            self._pause_registered = True
        return self._console

    def pause_console_on_exit(self) -> None:
        if self._console.state == "owned" and not self._restarting:
            try:
                input("\nEnterを押すと終了します...")
            except (EOFError, OSError, RuntimeError):
                pass

    def restart_process(self, debug: bool) -> None:
        from ..bootstrap import restart
        restart(debug)
        self._restarting = True

    def open_folder(self, path: Path) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            raise OSError(f"フォルダを開けません: {path}")

    def plugin_platform_key(self) -> str:
        if sys.platform == "win32":
            return "windows"
        if sys.platform.startswith("linux"):
            return "linux"
        raise OSError("このOSの実行ファイル型プラグインには未対応です")

    def configure_desktop_integration(self, app_id: str) -> None:
        try:
            _native().configure_desktop_integration(app_id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("デスクトップ統合の設定に失敗しました: %s", exc)

    def start_plugin(self, executable: Path, args: list[str], cwd: Path) -> tuple[subprocess.Popen[bytes], ProcessGuard]:
        native = _native()
        if not native.is_executable_plugin(str(executable)):
            raise OSError("プラグインの実行ファイルを実行できません")
        is_windows = self.plugin_platform_key() == "windows"
        process = subprocess.Popen([str(executable), *args], cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=native.plugin_creation_flags() if is_windows else 0,
            start_new_session=not is_windows, text=False)
        try:
            # Windows process is suspended until assigned to its kill-on-close job.
            guard = native.ProcessGroup(process.pid)
        except Exception:
            process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
            raise
        return process, guard


current_platform: PlatformDriver = SystemPlatformDriver()
