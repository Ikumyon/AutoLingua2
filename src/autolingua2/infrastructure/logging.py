from __future__ import annotations

from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys
from types import TracebackType

from .platform import log_directory

_SECRET = re.compile(r"(?i)(authorization|api[_-]?key|token|password)(\s*[:=]\s*)([^\s,;]+)")
_current_log_file: Path | None = None


class DiagnosticFormatter(logging.Formatter):
    def formatException(self, ei: tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]) -> str:
        if ei[0] is None:
            return ""
        return super().formatException(ei)

    def format(self, record: logging.LogRecord) -> str:
        return _SECRET.sub(r"\1\2[REDACTED]", super().format(record))


class ApplicationFileHandler(RotatingFileHandler):
    _autolingua = True


class ApplicationConsoleHandler(logging.StreamHandler):
    _autolingua = True
    _console = True


def _clean_old_logs(folder: Path, keep: int = 20) -> None:
    try:
        logs = sorted(folder.glob("app_*.log"))
        if len(logs) > keep:
            for old_log in logs[:-keep]:
                try:
                    old_log.unlink(missing_ok=True)
                except OSError:
                    pass
    except Exception:
        pass


def configure_logging() -> None:
    global _current_log_file
    folder = log_directory()
    folder.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        if getattr(handler, "_autolingua", False):
            root.removeHandler(handler)
            handler.close()

    if _current_log_file is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        _current_log_file = folder / f"app_{timestamp}.log"
        _clean_old_logs(folder, keep=20)

    handler = ApplicationFileHandler(
        _current_log_file,
        maxBytes=5_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(DiagnosticFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)


def connect_console_logging() -> None:
    if sys.stderr is None:
        return
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_console", False):
            root.removeHandler(handler)
            handler.close()
    handler = ApplicationConsoleHandler(sys.stderr)
    handler.setFormatter(DiagnosticFormatter("%(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)


def install_exception_hooks() -> None:
    import threading
    def report(exc_type, exc, tb):
        logging.getLogger("application").error("Unhandled exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)
