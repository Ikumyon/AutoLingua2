from __future__ import annotations

from pathlib import Path

from autolingua2.ir import TranslationProject
from autolingua2.ir.imported import ImportedTranslation, SourceRef
from .base import FileAdapter


def supported_file_filter(adapter: FileAdapter) -> str:
    suffixes = sorted(f"*{suffix}" for suffix in adapter.suffixes)
    return f"Supported Text ({' '.join(suffixes)});;All Files (*)"


def load_file(path: Path, adapter: FileAdapter) -> ImportedTranslation:
    if not adapter.can_load(path):
        raise ValueError(f"対応していないファイルです: {path}")
    imported = adapter.load(path)
    imported.project.adapter_id = adapter.id
    return imported


def load_folder(path: Path, adapter: FileAdapter) -> ImportedTranslation:
    return load_paths([path], adapter)


def load_paths(paths: list[Path], adapter: FileAdapter) -> ImportedTranslation:
    from autolingua2.infrastructure.operations import check_cancelled
    files_to_load: list[Path] = []
    seen: set[Path] = set()

    for p in paths:
        check_cancelled()
        resolved = p.resolve()
        if not resolved.exists():
            raise ValueError(f"対象が見つかりません: {p}")
        if resolved.is_dir():
            for child in sorted(resolved.rglob("*")):
                if child.is_file() and adapter.can_load(child) and child not in seen:
                    seen.add(child)
                    files_to_load.append(child)
        elif resolved.is_file():
            if not adapter.can_load(resolved):
                raise ValueError(f"{adapter.name} で読み込めない対象です: {p}")
            if resolved not in seen:
                seen.add(resolved)
                files_to_load.append(resolved)

    imports = []
    for file in files_to_load:
        check_cancelled()
        imports.append(load_file(file, adapter))
    imported = merge_imports(imports)
    imported.project.adapter_id = adapter.id
    return imported


def merge_imports(imports: list[ImportedTranslation]) -> ImportedTranslation:
    project = TranslationProject()
    source_refs: dict[str, SourceRef] = {}
    for imported in imports:
        if set(source_refs).intersection(imported.source_refs):
            raise ValueError("Duplicate translation unit IDs")
        project.extend(imported.project)
        source_refs.update(imported.source_refs)
    return ImportedTranslation(project=project, source_refs=source_refs)
