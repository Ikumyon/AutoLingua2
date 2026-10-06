from __future__ import annotations

import os
from pathlib import Path

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.adapters.io import load_paths
from autolingua2.services.project_archive import relative_path


def import_project(adapter: FileAdapter, paths: list[Path], source_language: str) -> ImportedTranslation:
    files = adapter.filter_source_files(paths, source_language)
    if not files:
        raise ValueError("指定された翻訳元言語に該当するファイルがありません。")
    if source_language == "auto":
        languages = {adapter.detect_source_language(path) for path in files}
        if None in languages or len(languages) != 1:
            raise ValueError("翻訳元言語を選択してください。")
        detected_language = languages.pop()
        if detected_language is None:
            raise ValueError("翻訳元言語を選択してください。")
        source_language = detected_language
    imported = load_paths(files, adapter)
    if not imported.project.sources:
        raise ValueError("読み込み可能な翻訳データがありません。")
    roots = [path.resolve() if path.is_dir() else path.resolve().parent for path in paths]
    root = Path(os.path.commonpath(roots))
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
    return imported


