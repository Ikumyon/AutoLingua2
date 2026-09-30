from pathlib import Path
import logging
from threading import Event

from PySide6.QtCore import QThread, Signal

from autolingua2.adapters.base import FileAdapter
from autolingua2.services.project_io import import_project
from autolingua2.infrastructure.operations import operation_scope


class ImportWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, adapter: FileAdapter, paths: list[Path], language: str, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.paths = list(paths)
        self.language = language
        self.cancel_event = Event()

    def requestInterruption(self) -> None:
        self.cancel_event.set()
        super().requestInterruption()

    def run(self) -> None:
        try:
            with operation_scope(self.cancel_event, self.progress.emit):
                imported = import_project(self.adapter, self.paths, self.language)
            if not self.isInterruptionRequested():
                self.loaded.emit(imported)
        except Exception as exc:
            logging.getLogger(__name__).exception("plugin=%s operation=import failed", self.adapter.id)
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
