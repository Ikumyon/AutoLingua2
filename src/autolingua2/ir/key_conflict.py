"""File snapshots and key candidates exposed through the parser contract."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class KeyEntry:
    key: str
    language_code: str
    text: str
    line_number: int


@dataclass(frozen=True, slots=True)
class KeyFile:
    path: Path
    content: bytes
    encoding: str
    bom: bytes
    entries: tuple[KeyEntry, ...]


@dataclass(frozen=True, slots=True)
class KeyCandidate:
    file: KeyFile
    entry: KeyEntry


@dataclass(frozen=True, slots=True)
class KeyConflictSide:
    role: Literal["source", "translation"]
    language_code: str
    candidates: tuple[KeyCandidate, ...]


@dataclass(frozen=True, slots=True)
class KeyConflict:
    key: str
    position: int
    total: int
    sides: tuple[KeyConflictSide, ...]
