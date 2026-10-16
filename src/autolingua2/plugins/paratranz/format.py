"""ParaTranz JSON conversion without game-specific rules or hidden metadata."""
from __future__ import annotations

import json
from pathlib import Path

from autolingua2.plugins.contracts import (
    ExportFile, FilterRule, GameProfile, ImportedTranslation, SourceRef,
    TranslationProject, TranslationRecord, TranslationSource, TranslationUnit, UnitState,
)


FROM_STAGE = {
    0: UnitState.UNTRANSLATED, 1: UnitState.HUMAN_TRANSLATED,
    2: UnitState.DOUBTFUL, 3: UnitState.HUMAN_REVIEWED, 5: UnitState.HUMAN_REVIEWED,
    9: UnitState.LOCKED, -1: UnitState.HIDDEN,
}
TO_STAGE = {
    UnitState.UNTRANSLATED: 0, UnitState.AI_TRANSLATED: 1, UnitState.HUMAN_TRANSLATED: 1,
    UnitState.AI_REVIEWED: 3, UnitState.HUMAN_REVIEWED: 3,
    UnitState.REVIEW_ISSUES: 2, UnitState.DOUBTFUL: 2,
    UnitState.TRANSLATION_ERROR: 0, UnitState.REVIEW_ERROR: 0,
    UnitState.LOCKED: 9, UnitState.HIDDEN: -1,
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"ParaTranz JSONの項目が重複しています: {key}")
        result[key] = value
    return result


class ParaTranzAdapter:
    id = "paratranz"
    name = "ParaTranz JSON"
    suffixes = {".json"}
    supported_games = [GameProfile("generic", "汎用", [])]
    supported_languages: list[tuple[str, str]] = []
    default_filter_rules: list[FilterRule] = []

    def can_load(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() == ".json"

    def contains_translations(self, path: Path) -> bool:
        if path.is_dir():
            return any(self.can_load(child) for child in path.rglob("*.json"))
        return self.can_load(path)

    def detect_source_language(self, path: Path) -> str | None:
        return None

    def filter_source_files(self, paths: list[Path], source_slot: str) -> list[Path]:
        files: dict[Path, None] = {}
        for path in paths:
            if not path.exists():
                raise ValueError(f"対象が見つかりません: {path}")
            if path.is_file() and not self.can_load(path):
                raise ValueError(f"ParaTranz JSONファイルではありません: {path}")
            for child in sorted(path.rglob("*.json")) if path.is_dir() else [path]:
                if self.can_load(child):
                    files[child.resolve()] = None
        return list(files)

    def load(self, path: Path) -> ImportedTranslation:
        rows = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
        if not isinstance(rows, list):
            raise ValueError("ParaTranz JSONは配列で指定してください。")
        source_id = str(path.resolve())
        imported = ImportedTranslation(TranslationProject(
            sources=[TranslationSource(source_id, path.name)], adapter_id=self.id, game_id="generic",
        ))
        seen: set[str] = set()
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f"ParaTranz JSONの{index}件目はオブジェクトが必要です。")
            key, original, translation = row.get("key"), row.get("original"), row.get("translation")
            if not isinstance(key, str) or not isinstance(original, str) or not isinstance(translation, str):
                raise ValueError(f"ParaTranz JSONの{index}件目: key・original・translationは文字列が必要です。")
            if not key.strip() or key in seen:
                raise ValueError(f"ParaTranz JSONのキーが空または重複しています: {key}")
            seen.add(key)
            stage = row.get("stage", 0)
            if type(stage) is not int or stage not in FROM_STAGE:
                raise ValueError(f"ParaTranz JSONのstageが不正です: {key}")
            context = row.get("context")
            if context is None:
                context = ""
            if not isinstance(context, str):
                raise ValueError(f"ParaTranz JSONのcontextは文字列またはnullが必要です: {key}")
            unit_id = f"{source_id}#{index}"
            imported.project.units.append(TranslationUnit(unit_id, key, original, context=context))
            imported.source_refs[unit_id] = SourceRef(source_id, key, str(index))
            imported.embedded_translations[unit_id] = TranslationRecord(translation, FROM_STAGE[stage])
        return imported


class ParaTranzExporter:
    id = "json"
    name = "ParaTranz JSON (*.json)"
    exchange = True

    def plan(self, workspaces: list[ImportedTranslation], settings: dict[str, object]) -> list[ExportFile]:
        outputs: list[ExportFile] = []
        for imported in workspaces:
            language = imported.project.target_language
            if not language or Path(language).name != language or language in {".", ".."}:
                raise ValueError("出力する訳文の言語が不正です。")
            source_ids = {source.id for source in imported.project.sources}
            unit_ids = {unit.id for unit in imported.project.units}
            if (len(source_ids) != len(imported.project.sources)
                    or len(unit_ids) != len(imported.project.units) or unit_ids != set(imported.source_refs)
                    or any(ref.source_id not in source_ids for ref in imported.source_refs.values())):
                raise ValueError("原文・翻訳項目のIDまたは参照が不正です。")
            for source in imported.project.sources:
                path = Path(source.id)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("原文の相対パスが不正です。")
                if path.suffix.lower() != ".json":
                    path = path.with_name(f"{path.name}.json")
                entries: list[dict[str, object]] = []
                seen: set[str] = set()
                for unit in imported.project.units:
                    ref = imported.source_refs[unit.id]
                    if ref.source_id != source.id:
                        continue
                    if not ref.external_id.strip() or ref.external_id in seen:
                        raise ValueError(f"ParaTranz JSONのキーが空または重複しています: {ref.external_id}")
                    seen.add(ref.external_id)
                    entries.append({"key": ref.external_id, "original": unit.source_text,
                                    "translation": unit.target_text, "context": unit.context,
                                    "stage": TO_STAGE[unit.state]})
                content = (json.dumps(entries, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                outputs.append(ExportFile(Path(language) / path, content))
        return outputs
