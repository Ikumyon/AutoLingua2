from __future__ import annotations

from pathlib import Path

from autolingua2.adapters.base import ImportedTranslation
from autolingua2.infrastructure.encoding import read_text_lossless
from autolingua2.ir import TranslationProject, TranslationUnit

from .reader import ENTRY_RE, LANGUAGE_HEADER_RE, split_inline_comment


def render_translation_file(
    source: ImportedTranslation,
    project: TranslationProject,
    existing: ImportedTranslation | None = None,
) -> str:
    if len(source.project.sources) != 1 or (existing is not None and len(existing.project.sources) != 1):
        raise ValueError("保存できるのは原文1ファイルと既存訳1ファイルの組だけです")
    base = existing or source
    template = read_text_lossless(Path(base.project.sources[0].id))
    newline = "\r\n" if "\r\n" in template else "\n"
    source_units = _units_by_key(source, project)
    base_keys = {ref.external_id for ref in base.source_refs.values()}
    lines: list[str] = []
    header_written = False

    for line in template.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if not header_written and LANGUAGE_HEADER_RE.match(body):
            target_header = project.target_file_language
            if not target_header:
                raise ValueError("出力言語スロットを選択してください。")
            lines.append(f"{target_header}:{ending}")
            header_written = True
            continue
        match = ENTRY_RE.match(body)
        if match is None or match.group("key") not in source_units:
            lines.append(line)
            continue

        unit = source_units[match.group("key")]
        if existing is None and not unit.target_text.strip():
            lines.append(line)
            continue
        value = unit.target_text if existing is not None or unit.target_text.strip() else unit.source_text
        _, inline_comment = split_inline_comment(match.group("value"))
        if existing is not None and value == base_value_for_key(base, match.group("key")):
            lines.append(line)
            continue
        prefix = body[: match.start("value")]
        comment = f" # {inline_comment}" if inline_comment else ""
        lines.append(f'{prefix}"{_escape_value(value)}"{comment}{ending}')

    if not header_written:
        raise ValueError("言語ヘッダが見つかりません")

    for key, unit in source_units.items():
        if key in base_keys:
            continue
        if lines and not lines[-1].endswith(("\r", "\n")):
            lines.append(newline)
        value = unit.target_text if unit.target_text.strip() else unit.source_text
        lines.append(f' {key}: "{_escape_value(value)}"{newline}')
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


def base_value_for_key(imported: ImportedTranslation, key: str) -> str:
    for unit in imported.project.units:
        ref = imported.source_refs.get(unit.id)
        if ref is not None and ref.external_id == key:
            return unit.source_text
    return ""


def _escape_value(value: str) -> str:
    return value.replace('"', '\\"').replace("\r\n", "\\n").replace("\n", "\\n")
