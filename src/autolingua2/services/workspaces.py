from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
import re

from PySide6.QtCore import QLocale

from autolingua2.ir import UnitState
from autolingua2.ir.classification import SourceCategory
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.workspace import TranslationRecord, UnitView, Workspace, WorkspaceUnit
from autolingua2.services.settings_store import load_custom_languages, save_custom_languages
from autolingua2.services.translation_memory import TranslationMemoryError, TranslationMemoryStore


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str


def normalize_language_code(value: str) -> str:
    match = re.fullmatch(r"([A-Za-z]{2,3})-([A-Za-z]{2}|[0-9]{3})", value.strip())
    if match is None:
        raise ValueError("言語コードは ja-JP のような言語-地域形式で入力してください。")
    return f"{match[1].lower()}-{match[2].upper()}"


class WorkspaceService:
    def __init__(self, imported: ImportedTranslation) -> None:
        self.imported = imported
        self.translation_memory = TranslationMemoryStore()
        self.workspaces: dict[str, Workspace] = {}
        self._pending_targets: dict[tuple[str, str], str] = {}
        self.languages: dict[str, Language] = {}
        for locale in QLocale.matchingLocales(QLocale.Language.AnyLanguage,
                                             QLocale.Script.AnyScript,
                                             QLocale.Country.AnyCountry):
            if locale.language() == QLocale.Language.C or locale.country() == QLocale.Country.AnyCountry:
                continue
            try:
                code = normalize_language_code(locale.name().replace("_", "-"))
            except ValueError:
                continue
            name = f"{locale.nativeLanguageName()}（{locale.nativeCountryName()}）"
            self.languages.setdefault(code, Language(code, name))
        self.custom_languages = load_custom_languages()
        for code, name in self.custom_languages.items():
            self.languages[code] = Language(code, name)
        if imported.project.sources:
            self.add(imported.project.source_language)
        for code, workspace in imported.inherited_workspaces.items():
            if code not in self.languages:
                self.languages[code] = Language(code, code)
            self.workspaces[code] = replace(workspace, records={
                unit_id: replace(record) for unit_id, record in workspace.records.items()
            })
        imported.inherited_workspaces.clear()

    def register(self, name: str, code: str) -> str:
        name = name.strip()
        code = normalize_language_code(code)
        if not name:
            raise ValueError("表示名を入力してください。")
        if code in self.languages:
            raise ValueError("この言語コードは登録済みです。言語一覧から追加してください。")
        updated = {**self.custom_languages, code: name}
        save_custom_languages(updated)
        self.custom_languages = updated
        self.languages[code] = Language(code, name)
        return code

    def add(self, code: str) -> Workspace:
        if code not in self.languages or code in self.workspaces:
            raise ValueError("未登録または追加済みの言語です。")
        workspace = Workspace(code, {unit.id: TranslationRecord() for unit in self.imported.project.units},
                              self.imported.project.source_slot)
        self.workspaces[code] = workspace
        return workspace

    def source_units(self) -> list[WorkspaceUnit]:
        return [WorkspaceUnit(unit, TranslationRecord(state=unit.state), self.imported.excluded_unit_ids)
                for unit in self.imported.project.units]

    def remove(self, code: str) -> None:
        project = self.imported.project
        self.translation_memory.record_snapshots(
            project.adapter_id, project.game_id, project.source_root,
            project.source_language, {code: []},
        )
        del self.workspaces[code]
        self._pending_targets = {identity: text for identity, text in self._pending_targets.items()
                                 if identity[0] != code}

    def units(self, workspace: Workspace) -> list[WorkspaceUnit]:
        return [WorkspaceUnit(unit, workspace.records[unit.id], self.imported.excluded_unit_ids)
                for unit in self.imported.project.units]

    def exact_peers(self, workspace: Workspace, unit_id: str) -> list[WorkspaceUnit]:
        """Return other members of the existing exact group in this language."""
        classification = self.imported.classification
        if classification is None:
            return []
        group = next((group for group in classification.groups
                      if group.category == SourceCategory.EXACT
                      and any(element.unit_id == unit_id for element in group.elements)), None)
        if group is None:
            return []
        member_ids = {element.unit_id for element in group.elements if element.unit_id != unit_id}
        return [WorkspaceUnit(unit, workspace.records[unit.id], self.imported.excluded_unit_ids)
                for unit in self.imported.project.units if unit.id in member_ids]

    def share_translation(
        self, workspace: Workspace, unit_id: str, states: set[UnitState], *, manual: bool,
    ) -> list[WorkspaceUnit]:
        """Share text with selected states; review remains an individual action."""
        source = workspace.records[unit_id]
        shared_state = UnitState.HUMAN_TRANSLATED if manual else UnitState.AI_TRANSLATED
        changed: list[WorkspaceUnit] = []
        for unit in self.exact_peers(workspace, unit_id):
            if unit.state in states:
                unit.target_text = source.target_text
                unit.state = shared_state
                changed.append(unit)
        return changed

    def begin_translation_edit(self, workspace: Workspace, unit_id: str) -> None:
        """Keep the last confirmed text while the focus editor updates the live model."""
        self._pending_targets.setdefault((workspace.language_code, unit_id), workspace.records[unit_id].target_text)

    def record_translations(self, workspace: Workspace, units: Sequence[UnitView]) -> None:
        """Synchronize a complete workspace, including removed or cleared translations."""
        if self.workspaces.get(workspace.language_code) is not workspace:
            raise TranslationMemoryError("記録先の翻訳ワークスペースが見つかりません。")
        for unit in units:
            if unit.id not in workspace.records:
                raise TranslationMemoryError("記録する翻訳項目が見つかりません。")
            self._pending_targets.pop((workspace.language_code, unit.id), None)
        self._record_workspaces({workspace.language_code: workspace})

    def record_all_translations(self) -> None:
        self._record_workspaces(self.workspaces)

    def _record_workspaces(self, workspaces: dict[str, Workspace]) -> None:
        snapshots = {code: self._translation_pairs(workspace) for code, workspace in workspaces.items()}
        project = self.imported.project
        self.translation_memory.record_snapshots(
            project.adapter_id, project.game_id, project.source_root,
            project.source_language, snapshots,
        )

    def _translation_pairs(self, workspace: Workspace) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for unit in self.imported.project.units:
            record = workspace.records.get(unit.id)
            if record is None:
                raise TranslationMemoryError("記録する翻訳項目が見つかりません。")
            target = self._pending_targets.get((workspace.language_code, unit.id), record.target_text)
            pairs.append((unit.source_text, target))
        return pairs

    def export_data(self) -> list[ImportedTranslation]:
        outputs: list[ImportedTranslation] = []
        for workspace in self.workspaces.values():
            units = [replace(unit, target_text=workspace.records[unit.id].target_text,
                             state=workspace.records[unit.id].state,
                             source_changed=workspace.records[unit.id].source_changed)
                     for unit in self.imported.project.units]
            outputs.append(ImportedTranslation(
                replace(self.imported.project, units=units,
                        target_language=workspace.language_code,
                        target_file_language=workspace.output_slot),
                self.imported.source_refs,
            ))
        return outputs
