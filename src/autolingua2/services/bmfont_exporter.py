"""Builtin BMFont character list exporter."""
from __future__ import annotations

from pathlib import Path

from autolingua2.ir.imported import ImportedTranslation
from autolingua2.services.export_contract import ExportFile


def _filter_and_sort_chars(texts: list[str]) -> str:
    """Extract unique characters, exclude whitespace/controls, and sort by Unicode code point."""
    chars: set[str] = set()
    for text in texts:
        for char in text:
            # 除外: 空白・改行 (isspace), ASCII制御文字 (< 32), 特殊なフォーマット制御文字 (BOM, ゼロ幅スペース等)
            if (
                not char.isspace()
                and ord(char) >= 32
                and char not in {"\ufeff", "\u200b", "\u200c", "\u200d", "\x7f"}
            ):
                chars.add(char)
    sorted_chars = sorted(chars, key=ord)
    return "".join(sorted_chars)


class BmFontCharListExporter:
    """Exporter that plans a single-line Unicode-sorted character list text file for BMFont."""

    id = "bmfont_chars"
    name = "BMFont 使用文字一覧 (*.txt)"

    def plan(self, workspaces: list[ImportedTranslation], settings: dict[str, object]) -> list[ExportFile]:
        if not workspaces:
            raise ValueError("出力するワークスペースがありません。")

        target_mode = str(settings.get("target_mode", "target"))
        if target_mode not in {"target", "source"}:
            target_mode = "target"

        outputs: list[ExportFile] = []

        if target_mode == "source":
            # 原文抽出: 全ワークスペースの原文テキストから抽出
            source_texts: list[str] = []
            for ws in workspaces:
                for unit in ws.project.units:
                    if unit.source_text:
                        source_texts.append(unit.source_text)

            char_list = _filter_and_sort_chars(source_texts)
            content = b"\xef\xbb\xbf" + char_list.encode("utf-8")
            file_name = Path("characters_source.txt") if len(workspaces) > 1 else Path("characters.txt")
            outputs.append(ExportFile(file_name, content))
        else:
            # 訳文抽出: 各ワークスペース（言語）ごとに出力
            multiple = len(workspaces) > 1
            for index, ws in enumerate(workspaces):
                target_texts: list[str] = []
                for unit in ws.project.units:
                    if unit.target_text:
                        target_texts.append(unit.target_text)

                char_list = _filter_and_sort_chars(target_texts)
                content = b"\xef\xbb\xbf" + char_list.encode("utf-8")
                if multiple:
                    lang = (ws.project.target_file_language or ws.project.target_language or f"lang_{index}").strip()
                    safe_lang = "".join(c for c in lang if c.isalnum() or c in ("-", "_")) or f"lang_{index}"
                    file_name = Path(f"characters_{safe_lang}.txt")
                else:
                    file_name = Path("characters.txt")
                outputs.append(ExportFile(file_name, content))

        return outputs
