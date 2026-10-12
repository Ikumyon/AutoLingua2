from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
import re


class SourceCategory(str, Enum):
    EXACT = "exact"
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
    category: SourceCategory
    representative_id: str
    elements: tuple[ClassifiedElement, ...]


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Representatives may belong to multiple categories; OTHER is ungrouped only."""

    threshold: float
    groups: tuple[SourceGroup, ...]


def translation_changes(source: str, target: str) -> tuple[tuple[str, str], ...]:
    """Describe changed word fragments without sending the whole reference source."""
    before = re.findall(r"\w+|\s+|[^\w\s]", source)
    after = re.findall(r"\w+|\s+|[^\w\s]", target)
    return tuple(
        ("".join(before[start:end]), "".join(after[target_start:target_end]))
        for kind, start, end, target_start, target_end
        in SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
        if kind != "equal"
    )
