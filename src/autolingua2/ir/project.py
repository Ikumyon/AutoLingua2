from __future__ import annotations

from dataclasses import dataclass, field

from .issue import Issue
from .unit import TranslationUnit


@dataclass(slots=True)
class TranslationSource:
    id: str
    name: str
    issues: list[Issue] = field(default_factory=list)


@dataclass(slots=True)
class TranslationProject:
    name: str = ""
    icon_path: str = ""
    game_id: str = ""
    source_language: str = ""
    source_slot: str = ""
    source_root: str = ""
    loaded_files: list[str] = field(default_factory=list)
    loaded_folders: list[str] = field(default_factory=list)
    target_language: str = ""
    target_file_language: str = ""
    adapter_id: str = ""
    units: list[TranslationUnit] = field(default_factory=list)
    sources: list[TranslationSource] = field(default_factory=list)

    def extend(self, other: TranslationProject) -> None:
        self.units.extend(other.units)
        self.sources.extend(other.sources)
        if not self.name and other.name:
            self.name = other.name
        if not self.icon_path and other.icon_path:
            self.icon_path = other.icon_path
        if not self.game_id and other.game_id:
            self.game_id = other.game_id
        if not self.source_language and other.source_language:
            self.source_language = other.source_language
        if not self.source_slot and other.source_slot:
            self.source_slot = other.source_slot
        if not self.target_language and other.target_language:
            self.target_language = other.target_language
        if not self.target_file_language and other.target_file_language:
            self.target_file_language = other.target_file_language
        if not self.adapter_id and other.adapter_id:
            self.adapter_id = other.adapter_id
