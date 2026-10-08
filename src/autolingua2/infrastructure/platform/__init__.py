from __future__ import annotations

import atexit
from pathlib import Path

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from .base import ConsoleResult, PlatformDriver, PluginProcess


def _native():
    # One canonical namespace. No Python reimplementation of Win32 APIs.
    from autolingua2_native import platform
    return platform


def log_directory() -> Path:
    return PROJECT_ROOT / "logs"


def qt_file_path(path: Path) -> str:
    return _native().qt_file_path(str(path))


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
        _native().open_folder(str(path.resolve()))

    def plugin_platform_key(self) -> str:
        return _native().plugin_platform_key()

    def configure_desktop_integration(self, app_id: str) -> None:
        try:
            _native().configure_desktop_integration(app_id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("デスクトップ統合の設定に失敗しました: %s", exc)

    def start_plugin(self, executable: Path, args: list[str], cwd: Path) -> PluginProcess:
        return _native().start_plugin(str(executable), args, str(cwd))

    def system_voice_input_available(self) -> bool:
        return _native().system_voice_input_available()

    def start_system_voice_input(self) -> None:
        _native().start_system_voice_input()


current_platform: PlatformDriver = SystemPlatformDriver()
