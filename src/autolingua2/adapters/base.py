from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from autolingua2.ir.imported import GameProfile, ImportedTranslation
from autolingua2.ir.filter_rules import FilterRule
from autolingua2.ir.key_conflict import KeyFile
from autolingua2.ir.translation import TranslationTextRules


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

    def detect_source_language(self, path: Path) -> str | None:
        ...

    def filter_source_files(self, paths: list[Path], source_slot: str) -> list[Path]:
        ...


@runtime_checkable
class EmbeddedTranslationAdapter(Protocol):
    """Optional capability for input files containing both source and translation."""

    def contains_translations(self, path: Path) -> bool:
        ...


@runtime_checkable
class KeyConflictAdapter(Protocol):
    """Optional parser capability for formats with unique language/key pairs."""

    def inspect_key_file(self, path: Path) -> KeyFile:
        ...

    def remove_key_lines(self, snapshot: KeyFile, lines: set[int]) -> bytes:
        ...


@runtime_checkable
class TranslationTextAdapter(Protocol):
    """Optional public game-specific sentence boundaries and exceptions."""
    translation_text_rules: TranslationTextRules

