from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceCategory(str, Enum):
    EXACT = "exact"
    NON_LANGUAGE = "non_language"
    SIMILAR = "similar"
    OTHER = "other"


class DifferenceKind(str, Enum):
    REPLACE = "replace"
    DELETE = "delete"
    INSERT = "insert"


@dataclass(frozen=True, slots=True)
class TextDifference:
    kind: DifferenceKind
    source_start: int
    source_end: int
    target_start: int
    target_end: int
    source_text: str
    target_text: str


@dataclass(frozen=True, slots=True)
class ClassifiedElement:
    unit_id: str
    distance_to_representative: int
    similarity_to_representative: float
    differences: tuple[TextDifference, ...]


@dataclass(frozen=True, slots=True)
class SourceGroup:
    id: str
    category: SourceCategory
    representative_id: str
    elements: tuple[ClassifiedElement, ...]


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    threshold: float
    groups: tuple[SourceGroup, ...]
