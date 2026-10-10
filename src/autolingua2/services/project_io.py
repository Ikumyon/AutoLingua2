from __future__ import annotations

import os
from pathlib import Path

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.project import TranslationProject
from autolingua2.ir.state import UnitState
from autolingua2.ir.workspace import TranslationRecord, Workspace
from autolingua2.adapters.io import load_paths, load_file
from autolingua2.infrastructure.operations import check_cancelled
from autolingua2.services.key_conflicts import ConflictConfirmation, resolve_key_conflicts
from autolingua2.services.project_archive import relative_path
from autolingua2.services.source_classification import classify_sources


def apply_inherited_translations(
    imported: ImportedTranslation,
    adapter: FileAdapter,
    inherited_paths: list[Path],
    inherited_state: UnitState = UnitState.HUMAN_REVIEWED,
) -> None:
    """言語とキーで既存訳を対応付け、言語別ワークスペースへ引き継ぐ。"""
    if not inherited_paths:
        return

    inherited: dict[str, dict[str, str]] = {}
    slots: dict[str, str] = {}
    for path in _inherited_files(adapter, inherited_paths):
        check_cancelled()
        trans = load_file(path, adapter)
        language = trans.project.source_language or adapter.detect_source_language(path)
        if language is None or not language:
            raise ValueError(f"既存訳の言語を検出できません: {path}")
        values = inherited.setdefault(language, {})
        slots.setdefault(language, trans.project.source_slot)
        for unit in trans.project.units:
            if not unit.label:
                continue
            if unit.label in values:
                raise ValueError(f"既存訳のキーが競合しています: {language}: {unit.label}")
            values[unit.label] = unit.source_text
    for language, values in inherited.items():
        records = {unit.id: TranslationRecord(values[unit.label], inherited_state)
                   if unit.label in values else TranslationRecord()
                   for unit in imported.project.units}
        imported.inherited_workspaces[language] = Workspace(language, records, slots[language])


def _inherited_files(adapter: FileAdapter, paths: list[Path]) -> list[Path]:
    files: dict[Path, None] = {}
    for path in paths:
        check_cancelled()
        resolved = path.resolve()
        if not resolved.exists():
            raise ValueError(f"既存訳の対象が見つかりません: {path}")
        for child in sorted(resolved.rglob("*")) if resolved.is_dir() else [resolved]:
            if adapter.can_load(child):
                files[child.resolve()] = None
    return list(files)


def import_project(
    adapter: FileAdapter, paths: list[Path], source_language: str,
    *, source_root: Path | None = None, allow_empty: bool = False,
    game_id: str = "",
    inherited_paths: list[Path] | None = None,
    inherited_state: UnitState = UnitState.HUMAN_REVIEWED,
    confirm_conflict: ConflictConfirmation | None = None,
) -> ImportedTranslation:
    files = adapter.filter_source_files(paths, source_language)
    if not files:
        if allow_empty and source_root is not None:
            root = source_root.resolve()
            imported = ImportedTranslation(TranslationProject(
                adapter_id=adapter.id, source_language=source_language,
                game_id=game_id,
                source_root=str(root), loaded_folders=[str(root)],
            ))
            classify_sources(imported, adapter)
            return imported
        raise ValueError("指定された翻訳元言語に該当するファイルがありません。")
    if source_language == "auto":
        languages = {adapter.detect_source_language(path) for path in files}
        if None in languages or len(languages) != 1:
            raise ValueError("翻訳元言語を選択してください。")
        detected_language = languages.pop()
        if detected_language is None:
            raise ValueError("翻訳元言語を選択してください。")
        source_language = detected_language
    inherited_files = _inherited_files(adapter, inherited_paths or [])
    resolve_key_conflicts(adapter, files, inherited_files, confirm_conflict)
    imported = load_paths(files, adapter)
    if game_id:
        imported.project.game_id = game_id
    if not imported.project.sources and not allow_empty:
        raise ValueError("読み込み可能な翻訳データがありません。")
    roots = [path.resolve() if path.is_dir() else path.resolve().parent for path in paths]
    root = source_root.resolve() if source_root is not None else Path(os.path.commonpath(roots))
    imported.project.source_root = str(root)
    imported.project.loaded_files = [str(Path(source.id).resolve()) for source in imported.project.sources]
    folders = set(roots)
    for filename in imported.project.loaded_files:
        parent = Path(filename).parent
        while parent.is_relative_to(root):
            folders.add(parent)
            if parent == root:
                break
            parent = parent.parent
    imported.project.loaded_folders = sorted(str(folder) for folder in folders)
    source_ids: dict[str, str] = {}
    for source in imported.project.sources:
        relative = relative_path(Path(source.id).resolve().relative_to(root).as_posix())
        if relative in source_ids.values() or source.id in source_ids:
            raise ValueError("原文IDが重複しています。")
        source_ids[source.id] = relative
        source.id = relative
    refs = {}
    for unit in imported.project.units:
        ref = imported.source_refs.get(unit.id)
        if ref is None or ref.source_id not in source_ids:
            raise ValueError("原文参照がありません。")
        ref.source_id = source_ids[ref.source_id]
        unit.id = f"{ref.source_id}#{ref.external_id}"
        if unit.id in refs:
            raise ValueError("翻訳項目IDが重複しています。")
        refs[unit.id] = ref
    imported.source_refs = refs
    imported.project.source_language = source_language

    if inherited_files:
        apply_inherited_translations(imported, adapter, inherited_files, inherited_state=inherited_state)

    classify_sources(imported, adapter)
    return imported


