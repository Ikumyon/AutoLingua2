from __future__ import annotations

from enum import Enum


class UnitState(str, Enum):
    UNTRANSLATED = "untranslated"
    AI_TRANSLATED = "ai_translated"
    HUMAN_TRANSLATED = "human_translated"
    AI_REVIEWED = "ai_reviewed"
    HUMAN_REVIEWED = "human_reviewed"
    REVIEW_ISSUES = "review_issues"
    TRANSLATION_ERROR = "translation_error"
    REVIEW_ERROR = "review_error"
    DOUBTFUL = "doubtful"
    LOCKED = "locked"
    HIDDEN = "hidden"
