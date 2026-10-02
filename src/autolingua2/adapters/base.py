from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from autolingua2.ir import TranslationProject
from autolingua2.ir.imported import GameProfile, ImportedTranslation
from autolingua2.ir.filter_rules import FilterRule


@runtime_checkable
class FileAdapter(Protocol):
    id: str
    name: str
    suffixes: set[str]
    default_filter_rules: list[FilterRule]
    supported_games: list[GameProfile]
    supported_languages: list[tuple[str, str]]

    def can_load(self, path: Path) -> bool:
        ...

    def load(self, path: Path) -> ImportedTranslation:
        ...

    def save(self, path: Path, imported: ImportedTranslation, project: TranslationProject,
             existing: ImportedTranslation | None = None) -> None:
        ...

    def output_name(self, path: Path, project: TranslationProject) -> str:
        ...

    def detect_source_language(self, path: Path) -> str | None:
        ...

    def filter_source_files(self, paths: list[Path], current_source_lang: str) -> list[Path]:
        ...

