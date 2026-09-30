from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event
from typing import Callable


class OperationCancelled(RuntimeError):
    pass


_cancel: ContextVar[Event | None] = ContextVar("operation_cancel", default=None)
_progress: ContextVar[Callable[[str], None] | None] = ContextVar("operation_progress", default=None)


def check_cancelled() -> None:
    event = _cancel.get()
    if event is not None and event.is_set():
        raise OperationCancelled("キャンセルしました。")


def report_progress(message: str) -> None:
    callback = _progress.get()
    if callback:
        callback(message)


@contextmanager
def operation_scope(cancel: Event, progress: Callable[[str], None]):
    token = _cancel.set(cancel)
    progress_token = _progress.set(progress)
    try:
        check_cancelled()
        yield
    finally:
        _progress.reset(progress_token)
        _cancel.reset(token)
