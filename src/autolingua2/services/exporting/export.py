"""Write the output layout planned by a registered exporter."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from autolingua2.infrastructure.operations import check_cancelled, report_progress
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.state import UnitState
from autolingua2.services.exporting.export_contract import TranslationExporter


DEFAULT_TRANSLATION_STATES = frozenset({
    UnitState.AI_TRANSLATED, UnitState.HUMAN_TRANSLATED,
    UnitState.AI_REVIEWED, UnitState.HUMAN_REVIEWED, UnitState.LOCKED,
})


def plan_export_translation(workspaces: list[ImportedTranslation], exporter: TranslationExporter,
                            directory: Path, settings: dict[str, object]) -> list[tuple[Path, bytes]]:
    if not workspaces:
        raise ValueError("出力するワークスペースがありません。")
    if any(not workspace.project.sources for workspace in workspaces):
        raise ValueError("保存する原文がありません。")
    directory = directory.resolve()
    if not directory.is_dir():
        raise ValueError("出力先フォルダがありません。")
    check_cancelled()
    plugin_settings = dict(settings)
    selected = plugin_settings.pop("translation_states", [state.value for state in DEFAULT_TRANSLATION_STATES])
    if not isinstance(selected, list) or any(not isinstance(state, str) for state in selected):
        raise ValueError("出力する訳文のステータスが不正です。")
    states = {UnitState(state) for state in selected}
    prepared = [replace(workspace,
        project=replace(workspace.project, units=[
            replace(unit, target_text=unit.target_text
                    if unit.state in states and unit.target_text.strip() else unit.source_text)
            for unit in workspace.project.units
        ]),
    ) for workspace in workspaces]
    files = exporter.plan(prepared, plugin_settings)
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

    return outputs


def export_translation(workspaces: list[ImportedTranslation], exporter: TranslationExporter,
                       directory: Path, settings: dict[str, object]) -> list[Path]:
    outputs = plan_export_translation(workspaces, exporter, directory, settings)
    for path, content in outputs:
        check_cancelled()
        report_progress(f"保存しています: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    check_cancelled()
    return [path for path, _ in outputs]
