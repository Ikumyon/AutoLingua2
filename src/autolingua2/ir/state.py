from __future__ import annotations

from enum import Enum


class UnitState(str, Enum):
    UNTRANSLATED = "untranslated"
    TRANSLATED = "translated"
    DOUBTFUL = "doubtful"
