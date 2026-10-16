"""GUI-independent output contracts shared through the plugin entrance."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from autolingua2.ir.imported import ImportedTranslation


@dataclass(frozen=True)
class ExportFile:
    relative_path: Path
    content: bytes


@runtime_checkable
class TranslationExporter(Protocol):
    id: str
    name: str

    def plan(self, workspaces: list[ImportedTranslation], settings: dict[str, object]) -> list[ExportFile]:
        """Plan all workspaces together, preserving each workspace's output language."""
        ...
