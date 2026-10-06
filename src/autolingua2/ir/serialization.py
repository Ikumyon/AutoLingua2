"""Restore translation data without IO, services, or UI dependencies."""
from __future__ import annotations

from .imported import ImportedTranslation, SourceRef
from .issue import Issue
from .project import TranslationProject, TranslationSource
from .state import UnitState
from .unit import TranslationUnit
from .validation import array, boolean, record, required, string_field, text


def _issues(value: object) -> list[Issue]:
    result: list[Issue] = []
    for item in array(value):
        data = record(item)
        result.append(Issue(text(required(data, "message")), string_field(data, "kind", "syntax")))
    return result


def imported_from_dict(value: object) -> ImportedTranslation:
    data = record(value)
    project_data = record(required(data, "project"))
    sources: list[TranslationSource] = []
    source_ids: set[str] = set()
    for item in array(required(project_data, "sources")):
        source = record(item)
        source_id = text(required(source, "id"), nonempty=True)
        if source_id in source_ids:
            raise ValueError(f"Duplicate source ID: {source_id}")
        source_ids.add(source_id)
        sources.append(TranslationSource(
            id=source_id, name=text(required(source, "name")),
            issues=_issues(source.get("issues", [])),
        ))

    units: list[TranslationUnit] = []
    unit_ids: set[str] = set()
    for item in array(required(project_data, "units")):
        unit = record(item)
        unit_id = text(required(unit, "id"), nonempty=True)
        if unit_id in unit_ids:
            raise ValueError(f"Duplicate unit ID: {unit_id}")
        unit_ids.add(unit_id)
        units.append(TranslationUnit(
            id=unit_id,
            label=text(required(unit, "label")),
            source_text=text(required(unit, "source_text")),
            target_text=string_field(unit, "target_text"),
            context=string_field(unit, "context"),
            state=UnitState(string_field(unit, "state", UnitState.UNTRANSLATED.value)),
            issues=_issues(unit.get("issues", [])),
            hidden=boolean(unit.get("hidden", False)),
            locked=boolean(unit.get("locked", False)),
        ))

    refs: dict[str, SourceRef] = {}
    for unit_id, item in record(required(data, "source_refs")).items():
        ref = record(item)
        source_id = text(required(ref, "source_id"), nonempty=True)
        if source_id not in source_ids:
            raise ValueError(f"Unknown source ID: {source_id}")
        refs[unit_id] = SourceRef(
            source_id=source_id,
            external_id=text(required(ref, "external_id"), nonempty=True),
            location=string_field(ref, "location"),
            data={key: text(item) for key, item in record(ref.get("data", {})).items()},
        )
    if set(refs) != unit_ids:
        raise ValueError("Source references must match translation unit IDs exactly")

    project = TranslationProject(
        name=string_field(project_data, "name"),
        icon_path=string_field(project_data, "icon_path"),
        game_id=string_field(project_data, "game_id"),
        source_language=string_field(project_data, "source_language"),
        source_slot=string_field(project_data, "source_slot"),
        target_language=string_field(project_data, "target_language"),
        target_file_language=string_field(project_data, "target_file_language"),
        adapter_id=string_field(project_data, "adapter_id"),
        units=units, sources=sources,
    )
    return ImportedTranslation(project, refs)
