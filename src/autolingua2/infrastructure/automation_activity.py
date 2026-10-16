"""Explicit correlation of script operations and their asynchronous work."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from itertools import count
from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QDialog, QProgressDialog, QWidget
from shiboken6 import isValid

from autolingua2.ir.automation_script import Step

_current: ContextVar[AutomationAction | None] = ContextVar("automation_action", default=None)
_ids = count(1)


@dataclass(eq=False)
class AutomationAction:
    session: AutomationSession
    step: Step
    window: QWidget
    id: int = field(default_factory=lambda: next(_ids))

    @contextmanager
    def scope(self) -> Iterator[None]:
        token = _current.set(self if self.session.active else None)
        try:
            yield
        finally:
            _current.reset(token)


class AutomationActivity:
    def __init__(self, label: str, action: AutomationAction | None, owner: QWidget | None) -> None:
        self.id = next(_ids)
        self.label, self.action = label, action
        self.owner = owner if owner is not None else action.window if action is not None else None
        self.state, self.error = "running", ""
        self.callbacks = 0
        self.timer: QTimer | None = None
        self.connections: list[tuple[Any, Callable]] = []
        if action is not None:
            action.session.activities.append(self)

    @contextmanager
    def scope(self) -> Iterator[None]:
        action = self.action
        token = _current.set(action if action is not None and action.session.active else None)
        try:
            yield
        finally:
            _current.reset(token)

    def callback(self, callback: Callable) -> Callable:
        @wraps(callback)
        def scoped(*args, **kwargs):
            with self.scope():
                self.callbacks += 1
                try:
                    return callback(*args, **kwargs)
                except Exception as exc:
                    self.finish("failed", str(exc))
                    raise
                finally:
                    self.callbacks -= 1
        return scoped

    def finish(self, outcome: str = "succeeded", error: str = "") -> None:
        if self.state in {"succeeded", "failed", "cancelled"}:
            return
        self.state = outcome
        self.error = error or ("処理がキャンセルされました。" if outcome == "cancelled" else "")
        self.detach()

    def detach(self) -> None:
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        for signal, callback in self.connections:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass
        self.connections.clear()

    def watch(self, busy: Callable[[], bool], *, errors: tuple = (), cancelled: tuple = ()) -> None:
        """Observe completion after existing signal handlers have applied results."""
        if self.action is None or not self.action.session.active:
            return
        def failed(*args) -> None:
            self.error = next((arg for arg in args if isinstance(arg, str)), "処理に失敗しました。")
        def stopped(*_args) -> None:
            self.finish("cancelled")
        for signal, callback in [(s, failed) for s in errors] + [(s, stopped) for s in cancelled]:
            signal.connect(callback)
            self.connections.append((signal, callback))
        timer = self.timer = QTimer(self.action.session)
        timer.setSingleShot(True)
        def check() -> None:
            try:
                if self.callbacks or busy():
                    timer.start(25)
                else:
                    self.finish("failed" if self.error else "succeeded", self.error)
            except (RuntimeError, ValueError) as exc:
                self.finish("failed", str(exc))
        timer.timeout.connect(check)
        timer.start(0)


class AutomationSession(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.active = True
        self.activities: list[AutomationActivity] = []

    def action(self, step: Step, window: QWidget) -> AutomationAction:
        return AutomationAction(self, step, window)

    def blocking(self, active: QWidget | None, *, final: bool = False) -> list[AutomationActivity]:
        pending = []
        for activity in self.activities:
            if activity.state not in {"running", "awaiting_input"}:
                continue
            owner = activity.owner
            # Let the script answer a worker's nested confirmation dialog.
            input_ready = (
                not final and isinstance(active, QDialog) and not isinstance(active, QProgressDialog)
                and owner is not None and isValid(owner) and isValid(active)
                and active is not owner and self._descendant(active, owner)
            )
            activity.state = "awaiting_input" if input_ready else "running"
            if not input_ready:
                pending.append(activity)
        return pending

    @staticmethod
    def _descendant(widget: QWidget, owner: QWidget) -> bool:
        # QWidget.isAncestorOf stops at a top-level window boundary. Dialogs
        # deliberately have that boundary, while retaining a parentWidget.
        current = widget.parentWidget()
        while current is not None:
            if current is owner:
                return True
            current = current.parentWidget()
        return False

    def failure(self) -> AutomationActivity | None:
        return next((a for a in self.activities if a.error or a.state in {"failed", "cancelled"}), None)

    def close(self) -> None:
        self.active = False
        for activity in self.activities:
            activity.detach()


def begin_activity(label: str, *, owner: QWidget | None = None) -> AutomationActivity:
    action = _current.get()
    if action is not None and not action.session.active:
        action = None
    return AutomationActivity(label, action, owner)


@contextmanager
def background_activity() -> Iterator[None]:
    """Exclude periodic work even when called inside a modal event loop."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)


def observe_async(label: str, busy: Callable, *, errors: tuple[str, ...] = (),
                  cancelled: tuple[str, ...] = (), owner: Callable | None = None):
    """Attach the existing lifecycle of a service to the current script action."""
    def decorate(method: Callable) -> Callable:
        @wraps(method)
        def observed(instance, *args, **kwargs):
            activity = begin_activity(label, owner=owner(instance) if owner is not None else None)
            instance._automation_activity = activity
            activity.watch(lambda: busy(instance), errors=tuple(getattr(instance, name) for name in errors),
                           cancelled=tuple(getattr(instance, name) for name in cancelled))
            return activity.callback(lambda: method(instance, *args, **kwargs))()
        return observed
    return decorate


def activity_callback(method: Callable) -> Callable:
    """Carry the originating action across a queued signal or timer callback."""
    @wraps(method)
    def scoped(instance, *args, **kwargs):
        activity = getattr(instance, "_automation_activity", None)
        if activity is None:
            with background_activity():
                return method(instance, *args, **kwargs)
        return activity.callback(lambda: method(instance, *args, **kwargs))()
    return scoped


def track_worker(worker: Any, label: str) -> AutomationActivity:
    """Wait for the queued finished signal, not merely QThread.isRunning()."""
    activity = begin_activity(label)
    reported = [False]
    def finished() -> None:
        reported[0] = True
        error = getattr(worker, "error", None)
        if worker.cancel_event.is_set():
            activity.finish("cancelled")
        elif error is not None:
            activity.finish("failed", str(error))
    worker.finished.connect(finished)
    activity.watch(lambda: not reported[0])
    return activity


def deferred_callback(callback: Callable, label: str = "画面の更新") -> Callable:
    activity = begin_activity(label)
    def apply() -> None:
        try:
            activity.callback(callback)()
        finally:
            activity.finish("failed" if activity.error else "succeeded", activity.error)
    return apply


def background_callback(callback: Callable) -> Callable:
    @wraps(callback)
    def apply(*args, **kwargs):
        with background_activity():
            return callback(*args, **kwargs)
    return apply
