"""Generate localisation from workspace entries, without source-file IO."""
from __future__ import annotations

from autolingua2.plugins.contracts import ImportedTranslation, TranslationProject, TranslationUnit


def render_translation_file(
    source: ImportedTranslation,
    project: TranslationProject,
) -> str:
    if len(source.project.sources) != 1:
        raise ValueError("出力対象は原文1ファイルにしてください。")
    if not project.target_file_language:
        raise ValueError("出力言語スロットを選択してください。")
    units = _units_by_key(source, project)
    lines = [f"{project.target_file_language}:\n"]
    for key, unit in units.items():
        value = unit.target_text if unit.target_text.strip() else unit.source_text
        lines.append(f' {key}:0 "{_escape_value(value)}"\n')
    return "".join(lines)


def _units_by_key(source: ImportedTranslation, project: TranslationProject) -> dict[str, TranslationUnit]:
    result: dict[str, TranslationUnit] = {}
    for unit in project.units:
        ref = source.source_refs.get(unit.id)
        if ref is None:
            raise ValueError(f"キーの参照情報がありません: {unit.label}")
        if ref.external_id in result:
            raise ValueError(f"同じキーが複数あります: {ref.external_id}")
        result[ref.external_id] = unit
    return result


def _escape_value(value: str) -> str:
    return value.replace('"', '\\"').replace("\r\n", "\\n").replace("\n", "\\n")
