"""Paradox YAML output layouts, independent of the import adapter."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

from autolingua2.plugins.contracts import ExportFile, ImportedTranslation
from .eu4_encoding import encode_eu4_escape
from .reader import PARADOX_GAMES, SLOT_LANGUAGE
from .writer import render_translation_file


class ParadoxYamlExporter:
    id = "yaml"
    name = "Paradox YAML (*.yml)"

    def plan(self, workspaces: list[ImportedTranslation], settings: dict[str, object]) -> list[ExportFile]:
        layout = settings.get("layout")
        if layout not in {"language", "mixed"}:
            raise ValueError("出力フォルダ構成を選択してください。")
        encoding = settings.get("eu4_encoding", "utf8")
        if encoding not in {"utf8", "escaped"}:
            raise ValueError("エンコード方式が不正です。")
        outputs: list[ExportFile] = []
        for workspace in workspaces:
            outputs.extend(self._workspace_files(workspace, layout, encoding == "escaped"))
        return outputs

    def _workspace_files(self, imported: ImportedTranslation, layout: object,
                         eu4_escape: bool) -> list[ExportFile]:
        slot = imported.project.target_file_language
        if slot not in SLOT_LANGUAGE:
            raise ValueError(f"ワークスペースの出力言語スロットが不正です: {imported.project.target_language}")
        game = next((game for game in PARADOX_GAMES if game.id == imported.project.game_id), None)
        if game is not None and slot not in {item.slot_id for item in game.slots}:
            raise ValueError("このゲームに対応していない出力言語スロットです。")
        root = "localization" if imported.project.game_id in {"ck3", "vic3"} else "localisation"
        language = slot.removeprefix("l_")
        known_languages = {item.removeprefix("l_") for item in SLOT_LANGUAGE}
        outputs: list[ExportFile] = []
        source_ids = {source.id for source in imported.project.sources}
        if len(source_ids) != len(imported.project.sources):
            raise ValueError("原文IDが重複しています。")
        if any(ref.source_id not in source_ids for ref in imported.source_refs.values()):
            raise ValueError("存在しない原文への参照があります。")
        unit_ids = {unit.id for unit in imported.project.units}
        if len(unit_ids) != len(imported.project.units) or unit_ids != set(imported.source_refs):
            raise ValueError("翻訳項目IDが重複または原文参照と一致しません。")
        for source in imported.project.sources:
            path = Path(source.id)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("原文の相対パスが不正です。")
            folders = list(path.parent.parts)
            root_index = next((index for index, part in enumerate(folders)
                               if part.lower() in {"localisation", "localization"}), None)
            if root_index is not None:
                folders = folders[root_index + 1:]
            if folders and folders[0] in known_languages:
                folders.pop(0)
            stem = re.sub(r"l_[A-Za-z_]+$", slot, path.stem)
            if not stem.endswith(slot):
                stem = f"{stem}_{slot}"
            destination = Path(root)
            if layout == "language":
                destination /= language
            destination = destination.joinpath(*folders, f"{stem}.yml")
            refs = {key: ref for key, ref in imported.source_refs.items() if ref.source_id == source.id}
            project = replace(imported.project, sources=[source],
                              units=[unit for unit in imported.project.units if unit.id in refs])
            document = ImportedTranslation(project, refs)
            rendered = render_translation_file(document, project)
            if eu4_escape and project.game_id == "eu4":
                try:
                    content = encode_eu4_escape(rendered)
                except ValueError as exc:
                    raise ValueError(f"{destination}: {exc}") from exc
            else:
                content = rendered.encode("utf-8")
            outputs.append(ExportFile(destination, b"\xef\xbb\xbf" + content))
        return outputs
