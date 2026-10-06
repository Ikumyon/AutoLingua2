"""Generate localisation from workspace entries, without source-file IO."""
from __future__ import annotations

from pathlib import Path

from autolingua2.plugins.contracts import ImportedTranslation, TranslationProject, TranslationUnit


def render_translation_file(
    source: ImportedTranslation,
    project: TranslationProject,
    existing: ImportedTranslation | None = None,
) -> str:
    if len(source.project.sources) != 1 or (existing is not None and len(existing.project.sources) != 1):
        raise ValueError("出力対象は原文1ファイルと既存訳1ファイルの組にしてください。")
    if not project.target_file_language:
        raise ValueError("出力言語スロットを選択してください。")
    units = _units_by_key(source, project)
    if existing is not None:
        previous = _units_by_key(existing, existing.project)
        previous.update(units)
        units = previous
    lines = [f"{project.target_file_language}:\n"]
    for key, unit in units.items():
        value = unit.target_text if unit.target_text.strip() else unit.source_text
        lines.append(f' {key}:0 "{_escape_value(value)}"\n')
    return "".join(lines)


def save_translation_file(path: Path, rendered: str) -> None:
    path.write_bytes(b"\xef\xbb\xbf" + rendered.encode("utf-8"))


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
