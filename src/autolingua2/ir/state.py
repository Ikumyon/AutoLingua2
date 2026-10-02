from __future__ import annotations

from enum import Enum


class UnitState(str, Enum):
    UNTRANSLATED = "untranslated"
    AI_TRANSLATED = "ai_translated"
    HUMAN_TRANSLATED = "human_translated"
    AI_REVIEWED = "ai_reviewed"
    HUMAN_REVIEWED = "human_reviewed"
    DOUBTFUL = "doubtful"
    LOCKED = "locked"
    HIDDEN = "hidden"
