"""Cancellable service work on immutable snapshots, shared with UI operations."""
import logging
from collections.abc import Callable
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from autolingua2.infrastructure.operations import operation_scope, OperationCancelled
from autolingua2.infrastructure.automation_activity import track_worker


class OperationWorker(QThread):
    progress = Signal(str)

    def __init__(self, operation: Callable[[], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.operation = operation
        self.cancel_event = Event()
        self.result: Any = None
        self.error: Exception | None = None
        self.automation_activity = track_worker(self, "読み込み・保存・出力")

    def requestInterruption(self) -> None:
        self.cancel_event.set()
        super().requestInterruption()

    def run(self) -> None:
        try:
            with operation_scope(self.cancel_event, self.progress.emit):
                self.result = self.operation()
        except Exception as exc:
            self.error = exc
            if not isinstance(exc, OperationCancelled):
                logging.getLogger(__name__).exception("Plugin operation failed")
