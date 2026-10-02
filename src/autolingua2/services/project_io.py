from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.adapters.io import load_paths
from autolingua2.infrastructure.operations import check_cancelled


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
    imported.project.source_language = source_language
    return imported


@dataclass(frozen=True)
class OutputFile:
    path: Path
    imported: ImportedTranslation


def plan_output(adapter: FileAdapter, imported: ImportedTranslation, destination: Path,
                existing: ImportedTranslation | None = None) -> list[OutputFile]:
    sources = imported.project.sources
    if not sources:
        raise ValueError("保存対象がありません。")
    source_ids = {source.id for source in sources}
    if len(source_ids) != len(sources):
        raise ValueError("ソースIDが重複しています。")
    unit_ids = [unit.id for unit in imported.project.units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("翻訳項目IDが重複しています。")
    for unit in imported.project.units:
        ref = imported.source_refs.get(unit.id)
        if ref is None or ref.source_id not in source_ids:
            raise ValueError(f"保存に必要な参照情報がありません: {unit.id}")
    protected = {Path(source.id).resolve() for source in sources}
    if existing:
        protected.update(Path(source.id).resolve() for source in existing.project.sources)
    root = Path(os.path.commonpath([str(Path(s.id).resolve().parent) for s in sources]))
    outputs: list[OutputFile] = []
    used: set[Path] = set()
    for source in sources:
        check_cancelled()
        source_path = Path(source.id).resolve()
        name = adapter.output_name(source_path, imported.project)
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"不正な出力名: {name}")
        path = destination if len(sources) == 1 else destination / source_path.parent.relative_to(root) / name
        path = path.resolve()
        if len(sources) > 1 and not path.is_relative_to(destination.resolve()):
            raise ValueError("出力先が選択フォルダの外側です。")
        if path in protected or path in used:
            raise ValueError(f"原文・既存訳または他の出力と保存先が重複しています: {path}")
        used.add(path)
        refs = {key: ref for key, ref in imported.source_refs.items() if ref.source_id == source.id}
        units = [unit for unit in imported.project.units if unit.id in refs]
        project = replace(imported.project, sources=[source], units=units)
        outputs.append(OutputFile(path, ImportedTranslation(project, refs)))
    return outputs


def write_output(adapter: FileAdapter, outputs: list[OutputFile],
                 existing: ImportedTranslation | None = None) -> None:
    for output in outputs:
        check_cancelled()
        try:
            output.path.parent.mkdir(parents=True, exist_ok=True)
            adapter.save(output.path, output.imported, output.imported.project, existing)
        except Exception as exc:
            raise RuntimeError(f"保存に失敗しました: {output.path}\n{exc}") from exc
