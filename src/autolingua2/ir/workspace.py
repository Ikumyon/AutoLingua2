from __future__ import annotations

from dataclasses import dataclass, field

from .state import UnitState
from .unit import TranslationUnit
from .issue import Issue


@dataclass(slots=True)
class TranslationRecord:
    target_text: str = ""
    state: UnitState = UnitState.UNTRANSLATED


@dataclass(slots=True)
class Workspace:
    language_code: str
    records: dict[str, TranslationRecord] = field(default_factory=dict)
    output_slot: str = ""


@dataclass(slots=True, eq=False)
class WorkspaceUnit:
    """A reference to shared source data and one language's translation."""

    source: TranslationUnit
    record: TranslationRecord

    @property
    def id(self) -> str:
        return self.source.id

    @property
    def label(self) -> str:
        return self.source.label

    @property
    def source_text(self) -> str:
        return self.source.source_text

    @property
    def context(self) -> str:
        return self.source.context

    @property
    def issues(self) -> list[Issue]:
        return self.source.issues

    @property
    def target_text(self) -> str:
        return self.record.target_text

    @target_text.setter
    def target_text(self, value: str) -> None:
        self.record.target_text = value

    @property
    def state(self) -> UnitState:
        return self.record.state

    @state.setter
    def state(self, value: UnitState) -> None:
        self.record.state = value

    @property
    def hidden(self) -> bool:
        return self.state == UnitState.HIDDEN

    @hidden.setter
    def hidden(self, value: bool) -> None:
        if value:
            self.state = UnitState.HIDDEN
        elif self.state == UnitState.HIDDEN:
            self.state = UnitState.UNTRANSLATED

    @property
    def locked(self) -> bool:
        return self.state == UnitState.LOCKED

    @locked.setter
    def locked(self, value: bool) -> None:
        if value:
            self.state = UnitState.LOCKED
        elif self.state == UnitState.LOCKED:
            self.state = UnitState.UNTRANSLATED

    def matches(self, query: str) -> bool:
        return not query or any(query.casefold() in value.casefold() for value in (
            self.label, self.source_text, self.target_text, self.context))


UnitView = TranslationUnit | WorkspaceUnit
