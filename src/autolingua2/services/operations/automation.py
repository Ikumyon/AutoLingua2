"""Cooperative script execution; screen operations are delegated to the UI."""
from __future__ import annotations

from collections.abc import Generator

from PySide6.QtCore import QObject, QTimer, Signal

from autolingua2.ir.automation_script import ReadValue, Script, ScriptError, Step


class AutomationRunner(QObject):
    action_requested = Signal(object)
    line_changed = Signal(int)
    finished = Signal(str, bool)
    completion_requested = Signal()

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._advance)
        self.iterator: Generator[Step, ReadValue, None] | None = None
        self.result: ReadValue = None
        self.pending: Step | None = None
        self.running = False
        self.current: Step | None = None

    def start(self, script: Script) -> None:
        if self.running:
            raise RuntimeError("自動化はすでに実行中です。")
        self.iterator = script.steps()
        self.result = None
        self.pending = None
        self.current = None
        self.running = True
        self.timer.start(0)

    def _advance(self) -> None:
        iterator = self.iterator
        if not self.running or iterator is None or self.pending is not None:
            return
        try:
            # Yield regularly even when the script performs no screen operations.
            for _ in range(50):
                result, self.result = self.result, None
                step = iterator.send(result)
                self.current = step
                self.line_changed.emit(step.token.line)
                if step.target is not None:
                    self.pending = step
                    self.action_requested.emit(step)
                    return
        except StopIteration:
            self.timer.stop()
            self.iterator = None
            self.completion_requested.emit()
            return
        except (ScriptError, ArithmeticError, RecursionError, ValueError) as exc:
            self.fail(str(exc))
            return
        self.timer.start(0)

    def acknowledge(self, step: Step, result: ReadValue = None) -> None:
        if self.running and self.pending is step:
            self.result = result
            self.pending = None
            self.timer.start(0)

    def fail(self, reason: str, *, step: Step | None = None) -> None:
        step = step if step is not None else self.current
        if step is not None:
            prefix = f"{step.token.line}行 {step.token.column}列: "
            if not reason.startswith(prefix):
                reason = prefix + reason
        self.stop(reason, error=True)

    def stop(self, message: str = "停止しました。", *, error: bool = False) -> None:
        if not self.running:
            return
        self.timer.stop()
        self.running = False
        self.pending = None
        self.result = None
        iterator, self.iterator = self.iterator, None
        if iterator is not None:
            iterator.close()
        self.finished.emit(message, error)
