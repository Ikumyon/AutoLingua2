from pathlib import Path
import logging
from threading import Condition, Event

from PySide6.QtCore import QThread, Signal

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.state import UnitState
from autolingua2.ir.key_conflict import KeyConflict
from autolingua2.services.project_io import import_project
from autolingua2.infrastructure.operations import OperationCancelled, operation_scope


class ImportWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    conflict_requested = Signal(object)

    def __init__(
        self,
        adapter: FileAdapter,
        paths: list[Path],
        language: str,
        parent=None,
        *,
        game_id: str,
        inherited_paths: list[Path] | None = None,
        inherited_state: UnitState = UnitState.HUMAN_REVIEWED,
    ):
        super().__init__(parent)
        self.adapter = adapter
        self.paths = list(paths)
        self.language = language
        self.game_id = game_id
        self.inherited_paths = list(inherited_paths) if inherited_paths else []
        self.inherited_state = inherited_state
        self.cancel_event = Event()
        self._confirmation = Condition()
        self._pending_conflict: KeyConflict | None = None
        self._conflict_answer: tuple[int, ...] | None = None
        self._answered = False

    def requestInterruption(self) -> None:
        self.cancel_event.set()
        with self._confirmation:
            self._confirmation.notify_all()
        super().requestInterruption()

    def confirm_conflict(self, conflict: KeyConflict) -> tuple[int, ...] | None:
        with self._confirmation:
            if self.cancel_event.is_set():
                return None
            self._pending_conflict = conflict
            self._conflict_answer = None
            self._answered = False
            self.conflict_requested.emit(conflict)
            self._confirmation.wait_for(lambda: self._answered or self.cancel_event.is_set())
            self._pending_conflict = None
            return None if self.cancel_event.is_set() else self._conflict_answer

    def answer_conflict(self, conflict: KeyConflict, answer: tuple[int, ...] | None) -> None:
        with self._confirmation:
            if self._pending_conflict is not conflict:
                return
            self._conflict_answer = answer
            self._answered = True
            self._confirmation.notify_all()

    def run(self) -> None:
        try:
            with operation_scope(self.cancel_event, self.progress.emit):
                imported = import_project(
                    self.adapter, self.paths, self.language,
                    game_id=self.game_id,
                    inherited_paths=self.inherited_paths,
                    inherited_state=self.inherited_state,
                    confirm_conflict=self.confirm_conflict,
                )
            if not self.isInterruptionRequested():
                self.loaded.emit(imported)
        except OperationCancelled:
            self.progress.emit("読み込みを中止しました。確定済みのファイル修正は保持されます。")
        except Exception as exc:
            logging.getLogger(__name__).exception("plugin=%s operation=import failed", self.adapter.id)
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
