from __future__ import annotations

import os
from base64 import b64encode
from pathlib import Path

from autolingua2.adapters.base import EmbeddedTranslationAdapter, FileAdapter
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.project import TranslationProject
from autolingua2.ir.state import UnitState
from autolingua2.ir.workspace import TranslationRecord, Workspace
from autolingua2.adapters.io import load_paths, load_file
from autolingua2.infrastructure.operations import check_cancelled
from autolingua2.services.key_conflicts import ConflictConfirmation, resolve_key_conflicts
from autolingua2.services.project_archive import relative_path
from autolingua2.services.source_classification import classify_sources


def read_project_thumbnail(path: Path) -> str:
    """元ファイルの場所に依存しない、保存用の画像データを読み込む。"""
    return b64encode(path.read_bytes()).decode("ascii")


def detect_inherited_language(adapter: FileAdapter, paths: list[Path]) -> str | None:
    """Suggest a single language without overriding the user's explicit choice."""
    try:
        files = _inherited_files(adapter, paths)
        if not files or (isinstance(adapter, EmbeddedTranslationAdapter)
                         and any(adapter.contains_translations(path) for path in files)):
            return None
        languages = {load_file(path, adapter).project.source_language for path in files}
        return next(iter(languages)) if len(languages) == 1 and "" not in languages else None
    except (OSError, ValueError, UnicodeError):
        return None


def apply_inherited_translations(
    imported: ImportedTranslation,
    adapter: FileAdapter,
    inherited_paths: list[Path],
    inherited_language: str,
    inherited_state: UnitState = UnitState.HUMAN_REVIEWED,
) -> None:
    """キーで既存訳を対応付け、明示選択した言語へ引き継ぐ。"""
    if not inherited_paths:
        return

    if not inherited_language:
        raise ValueError("継承する訳文の言語を選択してください。")
    values: dict[str, str] = {}
    slots: set[str] = set()
    for path in _inherited_files(adapter, inherited_paths):
        check_cancelled()
        trans = load_file(path, adapter)
        slots.add(trans.project.source_slot)
        for unit in trans.project.units:
            if not unit.label:
                continue
            if unit.label in values:
                raise ValueError(f"既存訳のキーが競合しています: {inherited_language}: {unit.label}")
            values[unit.label] = trans.embedded_translations.get(unit.id, unit.source_text)
    workspace = imported.inherited_workspaces.setdefault(
        inherited_language, Workspace(inherited_language,
            {unit.id: TranslationRecord() for unit in imported.project.units},
            next(iter(slots)) if len(slots) == 1 else ""))
    for unit in imported.project.units:
        if unit.label in values:
            text = values[unit.label]
            workspace.records[unit.id] = TranslationRecord(
                text, inherited_state if text else UnitState.UNTRANSLATED)


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
    source_slot: str = "",
    inherited_paths: list[Path] | None = None,
    inherited_slot: str = "",
    inherited_language: str = "",
    inherited_state: UnitState = UnitState.HUMAN_REVIEWED,
    inherit_embedded: bool = True,
    confirm_conflict: ConflictConfirmation | None = None,
) -> ImportedTranslation:
    if not source_language or source_language == "auto":
        raise ValueError("原文のワークスペース言語を選択してください。")
    files = adapter.filter_source_files(paths, source_slot)
    if not files:
        if allow_empty and source_root is not None:
            root = source_root.resolve()
            imported = ImportedTranslation(TranslationProject(
                adapter_id=adapter.id, source_language=source_language, source_slot=source_slot,
                game_id=game_id,
                source_root=str(root), loaded_folders=[str(root)],
            ))
            classify_sources(imported, adapter)
            return imported
        raise ValueError("指定された言語スロットに該当する原文ファイルがありません。")
    inherited_files = _inherited_files(adapter, inherited_paths or [])
    if inherited_slot and inherited_files:
        inherited_files = adapter.filter_source_files(inherited_files, inherited_slot)
        if not inherited_files:
            raise ValueError("指定された言語スロットに該当する既存訳ファイルがありません。")
    if inherited_files and not inherited_language:
        raise ValueError("継承する訳文の言語を選択してください。")
    resolve_key_conflicts(adapter, files, inherited_files, confirm_conflict,
                         source_language=source_language, translation_language=inherited_language)
    imported = load_paths(files, adapter)
    if inherit_embedded and imported.embedded_translations and not inherited_language:
        raise ValueError("継承する訳文の言語を選択してください。")
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
    embedded: dict[str, str] = {}
    for unit in imported.project.units:
        ref = imported.source_refs.get(unit.id)
        if ref is None or ref.source_id not in source_ids:
            raise ValueError("原文参照がありません。")
        ref.source_id = source_ids[ref.source_id]
        old_id = unit.id
        unit.id = f"{ref.source_id}#{ref.external_id}"
        if old_id in imported.embedded_translations:
            embedded[unit.id] = imported.embedded_translations[old_id]
        if unit.id in refs:
            raise ValueError("翻訳項目IDが重複しています。")
        refs[unit.id] = ref
    imported.source_refs = refs
    imported.project.source_language = source_language
    imported.project.source_slot = source_slot

    if inherit_embedded and embedded:
        records = {unit.id: TranslationRecord(embedded[unit.id], inherited_state)
                   if embedded.get(unit.id) else TranslationRecord()
                   for unit in imported.project.units}
        imported.inherited_workspaces[inherited_language] = Workspace(
            inherited_language, records, imported.project.source_slot)
    imported.embedded_translations.clear()

    if inherited_files:
        apply_inherited_translations(imported, adapter, inherited_files, inherited_language,
                                     inherited_state=inherited_state)

    classify_sources(imported, adapter)
    return imported


