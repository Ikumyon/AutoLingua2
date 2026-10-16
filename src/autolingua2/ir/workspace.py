from __future__ import annotations

from dataclasses import dataclass, field

from .state import UnitState
from .unit import TranslationUnit
from .issue import Issue
from .tone import ToneItem


@dataclass(frozen=True, slots=True)
class ConfirmedTranslation:
    target_text: str
    tone: ToneItem | None


@dataclass(slots=True)
class TranslationNotes:
    rationale: str = ""
    sources: list[str] = field(default_factory=list)
    review: str = ""


@dataclass(slots=True)
class TranslationRecord:
    target_text: str = ""
    state: UnitState = UnitState.UNTRANSLATED
    source_changed: bool = False
    tone: ToneItem | None = None
    pending_confirmation: ConfirmedTranslation | None = None
    translating: bool = False
    notes: TranslationNotes = field(default_factory=TranslationNotes)
    generation: int = 0


@dataclass(slots=True)
class Workspace:
    language_code: str
    records: dict[str, TranslationRecord] = field(default_factory=dict)
    output_slot: str = ""
    glossary_id: str = ""
    tone_id: str = ""
    generation: int = 0


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    language_code: str
    counts: dict[UnitState, int]
    total: int
    reviewed: int
    progress: float
    source_changed: int


@dataclass(slots=True, eq=False)
class WorkspaceUnit:
    """A reference to shared source data and one language's translation."""

    source: TranslationUnit
    record: TranslationRecord
    excluded_unit_ids: set[str] = field(default_factory=set, repr=False)

    @property
    def source_changed(self) -> bool:
        return self.record.source_changed

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
        if self.record.target_text != value:
            self.record.generation += 1
        self.record.target_text = value

    @property
    def state(self) -> UnitState:
        return self.record.state

    @state.setter
    def state(self, value: UnitState) -> None:
        if self.record.state != value:
            self.record.generation += 1
        self.record.state = value
        if value in {UnitState.HUMAN_REVIEWED, UnitState.AI_REVIEWED}:
            self.record.source_changed = False

    @property
    def hidden(self) -> bool:
        return self.id in self.excluded_unit_ids or self.state == UnitState.HIDDEN

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


def is_pending_translation(unit: UnitView) -> bool:
    return isinstance(unit, WorkspaceUnit) and unit.record.pending_confirmation is not None


def is_translating(unit: UnitView) -> bool:
    return isinstance(unit, WorkspaceUnit) and unit.record.translating
