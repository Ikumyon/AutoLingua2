"""Export a project through its registered parser, one source at a time."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from autolingua2.adapters.base import FileAdapter
from autolingua2.infrastructure.operations import check_cancelled, report_progress
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.services.project_archive import relative_path


def export_translation(imported: ImportedTranslation, adapter: FileAdapter, directory: Path) -> list[Path]:
    if imported.project.adapter_id != adapter.id:
        raise ValueError("プロジェクトと保存パーサーが一致しません。")
    if not imported.project.sources:
        raise ValueError("保存する原文がありません。")
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError("出力先フォルダがありません。")
    source_ids = {source.id for source in imported.project.sources}
    if len(source_ids) != len(imported.project.sources):
        raise ValueError("原文IDが重複しています。")
    unit_ids = {unit.id for unit in imported.project.units}
    if len(unit_ids) != len(imported.project.units) or unit_ids != set(imported.source_refs):
        raise ValueError("翻訳項目IDが重複または原文参照と一致しません。")
    if any(unit.id not in imported.source_refs for unit in imported.project.units):
        raise ValueError("訳文の原文参照がありません。")
    if any(ref.source_id not in source_ids for ref in imported.source_refs.values()):
        raise ValueError("存在しない原文への参照があります。")

    outputs: list[tuple[Path, ImportedTranslation]] = []
    destinations: set[Path] = set()
    for source in imported.project.sources:
        check_cancelled()
        refs = {key: ref for key, ref in imported.source_refs.items() if ref.source_id == source.id}
        project = replace(
            imported.project, sources=[source],
            units=[unit for unit in imported.project.units if unit.id in refs],
        )
        source_path = Path(relative_path(source.id))
        name = adapter.output_name(source_path, project)
        if not name or Path(name).name != name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("出力ファイル名が不正です。")
        path = (directory / source_path.parent / name).resolve()
        if not path.is_relative_to(directory) or path in destinations:
            raise ValueError(f"出力先が重複または不正です: {name}")
        if path.exists():
            raise ValueError(f"出力先に同名ファイルがあります。別のフォルダを選択してください: {name}")
        destinations.add(path)
        outputs.append((path, ImportedTranslation(project, refs)))

    for path, source in outputs:
        check_cancelled()
        report_progress(f"保存しています: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        adapter.save(path, source, source.project)
    check_cancelled()
    return [path for path, _ in outputs]
