from __future__ import annotations

from dataclasses import dataclass, replace
import re

from PySide6.QtCore import QLocale

from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.workspace import TranslationRecord, Workspace, WorkspaceUnit
from autolingua2.services.settings_store import load_custom_languages, save_custom_languages


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
        return [WorkspaceUnit(unit, TranslationRecord(state=unit.state))
                for unit in self.imported.project.units]

    def remove(self, code: str) -> None:
        del self.workspaces[code]

    def units(self, workspace: Workspace) -> list[WorkspaceUnit]:
        return [WorkspaceUnit(unit, workspace.records[unit.id]) for unit in self.imported.project.units]

    def export_data(self) -> list[ImportedTranslation]:
        outputs: list[ImportedTranslation] = []
        for workspace in self.workspaces.values():
            units = [replace(unit, target_text=workspace.records[unit.id].target_text,
                             state=workspace.records[unit.id].state)
                     for unit in self.imported.project.units]
            outputs.append(ImportedTranslation(
                replace(self.imported.project, units=units,
                        target_language=workspace.language_code,
                        target_file_language=workspace.output_slot),
                self.imported.source_refs,
            ))
        return outputs
