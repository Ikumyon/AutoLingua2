from __future__ import annotations

from dataclasses import dataclass, field

from .project import TranslationProject
from .classification import ClassificationResult
from .workspace import Workspace


@dataclass(slots=True)
class SourceRef:
    source_id: str
    external_id: str
    location: str = ""
    data: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ImportedTranslation:
    project: TranslationProject
    source_refs: dict[str, SourceRef] = field(default_factory=dict)
    classification: ClassificationResult | None = None
    excluded_unit_ids: set[str] = field(default_factory=set)
    inherited_workspaces: dict[str, Workspace] = field(default_factory=dict)


@dataclass(slots=True)
class GameSlot:
    slot_id: str
    name: str
    language_code: str


@dataclass(slots=True)
class GameProfile:
    id: str
    name: str
    slots: list[GameSlot]
    default_slot_id: str = ""
