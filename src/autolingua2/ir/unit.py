from __future__ import annotations

from dataclasses import dataclass, field

from .issue import Issue
from .state import UnitState


@dataclass(slots=True)
class TranslationUnit:
    id: str
    label: str
    source_text: str
    target_text: str = ""
    context: str = ""
    state: UnitState = UnitState.UNTRANSLATED
    issues: list[Issue] = field(default_factory=list)
    hidden: bool = False
    locked: bool = False
    source_changed: bool = False

    def matches(self, query: str) -> bool:
        if not query:
            return True
        text = query.casefold()
        return (
            text in self.label.casefold()
            or text in self.source_text.casefold()
            or text in self.target_text.casefold()
            or text in self.context.casefold()
        )
