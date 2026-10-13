from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LanguageInfo:
    code: str
    name: str
    folder: Path
    flag_path: Path | None
    qm_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class UiMessage:
    context: str
    source: str
    original: str
    comment: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return self.context, self.source, self.comment


@dataclass(frozen=True, slots=True)
class TranslationCoverage:
    tag: str
    total: int
    missing: int

