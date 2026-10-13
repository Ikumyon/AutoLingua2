from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QLocale

from autolingua2.ir import UnitState
from autolingua2.ir.classification import SourceCategory
from autolingua2.ir.tone import ToneItem
from autolingua2.ir.filter_rules import TagRules
from autolingua2.ir.translation import protect_group, protect_edited_group
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.workspace import ConfirmedTranslation, TranslationRecord, UnitView, Workspace, WorkspaceSummary, WorkspaceUnit, is_pending_translation
from autolingua2.services.settings_store import load_custom_languages, save_custom_languages
from autolingua2.services.language_tags import normalize_language
TranslationPair = tuple[str, str, ToneItem | None]


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str


def normalize_language_code(value: str) -> str:
    return normalize_language(value)


class WorkspaceService:
    def __init__(self, imported: ImportedTranslation) -> None:
        self.imported = imported
        self.workspaces: dict[str, Workspace] = {}
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
        del self.workspaces[code]

    def units(self, workspace: Workspace) -> list[WorkspaceUnit]:
        return [WorkspaceUnit(unit, workspace.records[unit.id], self.imported.excluded_unit_ids)
                for unit in self.imported.project.units]

    def summaries(self) -> list[WorkspaceSummary]:
        """Snapshot every language independently of the editor's active filters."""
        unit_ids = tuple(unit.id for unit in self.imported.project.units
                         if unit.id not in self.imported.excluded_unit_ids)
        summaries: list[WorkspaceSummary] = []
        for workspace in self.workspaces.values():
            counts = dict.fromkeys(UnitState, 0)
            source_changed = 0
            for unit_id in unit_ids:
                record = workspace.records[unit_id]
                counts[record.state] += 1
                source_changed += int(record.source_changed)
            reviewed = counts[UnitState.AI_REVIEWED] + counts[UnitState.HUMAN_REVIEWED]
            translated = reviewed + counts[UnitState.AI_TRANSLATED] + counts[UnitState.HUMAN_TRANSLATED]
            eligible = len(unit_ids) - counts[UnitState.LOCKED] - counts[UnitState.HIDDEN]
            summaries.append(WorkspaceSummary(
                workspace.language_code, counts, len(unit_ids), reviewed,
                translated / eligible if eligible else 0.0, source_changed,
            ))
        return summaries

    def exact_peers(self, workspace: Workspace, unit_id: str) -> list[WorkspaceUnit]:
        """Return exact-group peers, including differing display-control tags."""
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
                for unit in self.imported.project.units
                if unit.id in member_ids]

    def similar_peers(self, workspace: Workspace, unit_id: str) -> list[WorkspaceUnit]:
        """Include exact-group members of the other entries in a similar group."""
        classification = self.imported.classification
        if classification is None:
            return []
        source_ids = {unit_id}
        for group in classification.groups:
            if group.category == SourceCategory.EXACT and any(
                element.unit_id == unit_id for element in group.elements
            ):
                source_ids.update(element.unit_id for element in group.elements)
        member_ids: set[str] = set()
        for group in classification.groups:
            if group.category == SourceCategory.SIMILAR and any(
                element.unit_id in source_ids for element in group.elements
            ):
                member_ids.update(element.unit_id for element in group.elements)
        for group in classification.groups:
            if group.category == SourceCategory.EXACT and group.representative_id in member_ids:
                member_ids.update(element.unit_id for element in group.elements)
        return [WorkspaceUnit(unit, workspace.records[unit.id], self.imported.excluded_unit_ids)
                for unit in self.imported.project.units if unit.id in member_ids - source_ids]

    def share_translation(
        self, workspace: Workspace, unit_id: str, states: set[UnitState], *, manual: bool, rules: TagRules,
        eligible_ids: set[str] | None = None,
    ) -> list[WorkspaceUnit]:
        """Share text with selected states; review remains an individual action."""
        source = workspace.records[unit_id]
        source_unit = next((unit for unit in self.imported.project.units if unit.id == unit_id), None)
        if source_unit is None:
            raise ValueError("共有元の翻訳項目がありません。")
        peers = [unit for unit in self.exact_peers(workspace, unit_id)
                 if not unit.locked and not unit.hidden and not unit.record.translating and not is_pending_translation(unit)
                 and unit.state in states and (eligible_ids is None or unit.id in eligible_ids)]
        if not peers:
            return []
        protected = protect_group({unit_id: source_unit.source_text, **{unit.id: unit.source_text for unit in peers}}, rules)
        edited = protect_edited_group(protected, unit_id, source.target_text)
        if rules.spans(edited):
            raise ValueError("原文にないタグが訳文に追加されているため、同じ文へ適用できません。")
        translations = {unit.id: protected.restore(edited, unit.id) for unit in peers}
        changed: list[WorkspaceUnit] = []
        for unit in peers:
            if (not unit.locked and not unit.hidden and not is_pending_translation(unit)
                    and unit.state in states and (eligible_ids is None or unit.id in eligible_ids)):
                unit.target_text = translations[unit.id]
                unit.state = UnitState.HUMAN_TRANSLATED if manual else UnitState.AI_TRANSLATED
                unit.record.tone = replace(source.tone) if source.tone is not None else None
                unit.record.pending_confirmation = None
                changed.append(unit)
        return changed

    def update_translation_draft(self, workspace: Workspace, unit_id: str, target_text: str) -> bool:
        """Keep confirmed content intact while either editor updates a draft."""
        if self.workspaces.get(workspace.language_code) is not workspace:
            raise ValueError("編集先の翻訳ワークスペースが見つかりません。")
        record = workspace.records[unit_id]
        if record.translating:
            return False
        if record.target_text == target_text:
            return False
        if record.pending_confirmation is None:
            record.pending_confirmation = ConfirmedTranslation(
                record.target_text, replace(record.tone) if record.tone is not None else None,
            )
        record.target_text = target_text
        return True

    def discard_translation_draft(self, workspace: Workspace, unit_id: str) -> bool:
        if self.workspaces.get(workspace.language_code) is not workspace:
            raise ValueError("編集先の翻訳ワークスペースが見つかりません。")
        record = workspace.records[unit_id]
        confirmed = record.pending_confirmation
        if confirmed is None:
            return False
        record.target_text = confirmed.target_text
        record.tone = replace(confirmed.tone) if confirmed.tone is not None else None
        record.pending_confirmation = None
        return True

    def confirm_translation(self, workspace: Workspace, unit_id: str,
                            target_text: str, state: UnitState, tone: ToneItem) -> None:
        if self.workspaces.get(workspace.language_code) is not workspace:
            raise ValueError("確定先の翻訳ワークスペースが見つかりません。")
        if not tone.id or not tone.name.strip() or not tone.prompt.strip():
            raise ValueError("口調を指定してください。")
        record = workspace.records[unit_id]
        record.target_text = target_text
        record.state = state
        record.tone = replace(tone)
        record.pending_confirmation = None
        if state in {UnitState.HUMAN_REVIEWED, UnitState.AI_REVIEWED}:
            record.source_changed = False

    @staticmethod
    def _translation_pair(source_text: str, record: TranslationRecord) -> TranslationPair:
        confirmed = record.pending_confirmation
        target, tone = ((confirmed.target_text, confirmed.tone) if confirmed is not None
                        else (record.target_text, record.tone))
        return source_text, target, replace(tone) if tone is not None else None

    def export_data(self) -> list[ImportedTranslation]:
        outputs: list[ImportedTranslation] = []
        for workspace in self.workspaces.values():
            units = [replace(unit, target_text=self._translation_pair(unit.source_text, workspace.records[unit.id])[1],
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
