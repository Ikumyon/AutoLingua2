"""Public, UI-independent contracts for voice input plugins.

OS/DE-specific code belongs in the plugin's Rust infrastructure. Providers must
use the public plugin context for settings and register teardown with on_close.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


VoiceInputMode = Literal["external", "transcription"]


@dataclass(frozen=True)
class VoiceInputCallbacks:
    """Thread-safe host notifications; these never expose an input widget.

    text accepts finalized segments only, each exactly once, in order. finished
    and error are terminal: the provider must release its recording/network
    resources before notifying. External-input providers do not use callbacks.
    """

    text: Callable[[str], None]
    finished: Callable[[], None]
    error: Callable[[str], None]


@runtime_checkable
class VoiceInputOperation(Protocol):
    def stop(self) -> None:
        """Request final recognition without blocking; notify finished/error."""
        ...

    def cancel(self) -> None:
        """Cancel and release resources without blocking. Safe after completion."""
        ...


@runtime_checkable
class VoiceInputProvider(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def mode(self) -> VoiceInputMode: ...

    def is_available(self) -> bool:
        """Quick local check only: do not launch, record, or make network calls."""
        ...

    def start(self, callbacks: VoiceInputCallbacks) -> VoiceInputOperation | None:
        """Start without blocking; clean up before raising on startup failure.

        external opens the OS/DE input facility and returns None. transcription
        returns an operation and delivers notifications through callbacks.
        """
        ...
