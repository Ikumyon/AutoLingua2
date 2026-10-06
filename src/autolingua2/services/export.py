"""Write the output layout planned by a registered exporter."""
from __future__ import annotations

from pathlib import Path

from autolingua2.infrastructure.operations import check_cancelled, report_progress
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.services.export_contract import TranslationExporter


def export_translation(workspaces: list[ImportedTranslation], exporter: TranslationExporter,
                       directory: Path, settings: dict[str, object]) -> list[Path]:
    if not workspaces:
        raise ValueError("出力するワークスペースがありません。")
    if any(not workspace.project.sources for workspace in workspaces):
        raise ValueError("保存する原文がありません。")
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError("出力先フォルダがありません。")
    check_cancelled()
    files = exporter.plan(workspaces, settings)
    if not files:
        raise ValueError("出力するファイルがありません。")
    outputs: list[tuple[Path, bytes]] = []
    destinations: set[Path] = set()
    for file in files:
        check_cancelled()
        relative = file.relative_path
        path = (directory / relative).resolve()
        if (relative.is_absolute() or ".." in relative.parts or path == directory
                or not path.is_relative_to(directory) or path in destinations):
            raise ValueError(f"出力先が重複または不正です: {relative}")
        if path.exists():
            raise ValueError(f"出力先に同名ファイルがあります。別のフォルダを選択してください: {relative}")
        destinations.add(path)
        outputs.append((path, file.content))
    for path in destinations:
        if any(parent in destinations or (parent.exists() and not parent.is_dir())
               for parent in path.parents if parent.is_relative_to(directory)):
            raise ValueError(f"出力ファイルとフォルダが競合しています: {path}")

    for path, content in outputs:
        check_cancelled()
        report_progress(f"保存しています: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    check_cancelled()
    return [path for path, _ in outputs]
