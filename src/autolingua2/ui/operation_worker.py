import logging
from threading import Event
from typing import Any

from PySide6.QtCore import QThread, Signal
from autolingua2.infrastructure.operations import operation_scope, OperationCancelled


class OperationWorker(QThread):
    progress = Signal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.cancel_event = Event()
        self.result: Any = None
        self.error: Exception | None = None

    def requestInterruption(self):
        self.cancel_event.set()
        super().requestInterruption()

    def run(self):
        try:
            with operation_scope(self.cancel_event, self.progress.emit):
                self.result = self.operation()
        except Exception as exc:
            self.error = exc
            if not isinstance(exc, OperationCancelled):
                logging.getLogger(__name__).exception("Plugin operation failed")
