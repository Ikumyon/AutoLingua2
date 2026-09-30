from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import re
import sys
import traceback
from types import TracebackType

from .platform import log_directory

_SECRET = re.compile(r"(?i)(authorization|api[_-]?key|token|password)(\s*[:=]\s*)([^\s,;]+)")


class DiagnosticFormatter(logging.Formatter):
    def formatException(self, ei: tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]) -> str:
        # Do not print source lines or exception messages that may embed payloads.
        if ei[0] is None:
            return ""
        frames = traceback.extract_tb(ei[2])
        return "\n".join(["Traceback (most recent call last):",
            *(f'  File "{f.filename}", line {f.lineno}, in {f.name}' for f in frames),
            ei[0].__name__])

    def format(self, record):
        return _SECRET.sub(r"\1\2[REDACTED]", super().format(record))


class ApplicationFileHandler(RotatingFileHandler):
    _autolingua = True


class ApplicationConsoleHandler(logging.StreamHandler):
    _autolingua = True
    _console = True


def configure_logging() -> None:
    folder = log_directory()
    folder.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        if getattr(handler, "_autolingua", False):
            root.removeHandler(handler)
            handler.close()
    handler = ApplicationFileHandler(folder / "application.log", maxBytes=2_000_000,
                                 backupCount=3, encoding="utf-8")
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
