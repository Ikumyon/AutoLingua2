from __future__ import annotations

import base64
from dataclasses import asdict
import json
from pathlib import Path
from threading import local

from autolingua2.services.export_contract import ExportFile
from autolingua2.ir.filter_rules import FilterRule
from autolingua2.ir.imported import GameProfile, GameSlot, ImportedTranslation
from autolingua2.ir.serialization import imported_from_dict
from autolingua2.ir.validation import array, record, required, string_field, text
from autolingua2.infrastructure.platform import current_platform
from autolingua2.infrastructure.platform.base import PlatformDriver
from autolingua2.infrastructure.plugin_rpc import PluginRPC, PluginRPCError


class _OperationState(local):
    def __init__(self) -> None:
        self.languages: dict[Path, str] = {}


class ExecutableAdapter:
    def __init__(self, manifest: Path, platform: PlatformDriver = current_platform) -> None:
        data = record(json.loads(manifest.read_text(encoding="utf-8")))
        version = required(data, "protocol_version")
        if type(version) is not int or version != 1:
            raise ValueError("Invalid plugin manifest version")
        self.id = text(required(data, "id"), nonempty=True)
        root = manifest.parent.resolve()
        executables = record(required(data, "executables"))
        entry_value = executables.get(platform.plugin_platform_key())
        if entry_value is None:
            raise ValueError("現在のOSには未対応です")
        entry = record(entry_value)
        relative = Path(text(required(entry, "path"), nonempty=True))
        executable = (root / relative).resolve()
        if relative.is_absolute() or not executable.is_relative_to(root) or not executable.is_file():
            raise ValueError("実行ファイルはプラグインフォルダ内に配置してください。")
        args = [text(arg) for arg in array(required(entry, "args"))]
        self.rpc = PluginRPC(self.id, executable, args, root, platform)
        registration = record(self.rpc.call("register", {}))
        self.exporters = [ExecutableExporter(self.rpc, record(item))
                          for item in array(registration.get("exporters", []))]
        if text(required(registration, "id"), nonempty=True) != self.id:
            raise ValueError("Executable registration ID does not match its manifest")
        description = record(required(registration, "parser"))
        self.name = text(required(description, "name"), nonempty=True)
        self.suffixes = {text(s, nonempty=True) for s in array(required(description, "suffixes"))}
        if not self.suffixes or any(not s.startswith(".") for s in self.suffixes):
            raise ValueError("Invalid plugin suffixes")

        self.supported_languages: list[tuple[str, str]] = []
        codes: set[str] = set()
        for item in array(required(description, "supported_languages")):
            pair = array(item)
            if len(pair) != 2:
                raise ValueError("Languages must contain [code, name] pairs")
            code, name = (text(value, nonempty=True) for value in pair)
            if code in codes:
                raise ValueError(f"Duplicate language: {code}")
            codes.add(code)
            self.supported_languages.append((code, name))
        if not codes:
            raise ValueError("At least one supported language is required")

        self.supported_games: list[GameProfile] = []
        game_ids: set[str] = set()
        for item in array(required(description, "supported_games")):
            game = record(item)
            game_id = text(required(game, "id"), nonempty=True)
            if game_id in game_ids:
                raise ValueError(f"Duplicate game ID: {game_id}")
            game_ids.add(game_id)
            slots: list[GameSlot] = []
            slot_ids: set[str] = set()
            for slot_value in array(required(game, "slots")):
                slot = record(slot_value)
                slot_id = text(required(slot, "slot_id"), nonempty=True)
                language = text(required(slot, "language_code"), nonempty=True)
                if slot_id in slot_ids or language not in codes:
                    raise ValueError("Invalid slot ID or language")
                slot_ids.add(slot_id)
                slots.append(GameSlot(slot_id, text(required(slot, "name"), nonempty=True), language))
            default_slot = string_field(game, "default_slot_id")
            if (slots and default_slot not in slot_ids) or (not slots and default_slot):
                raise ValueError("Invalid default slot")
            self.supported_games.append(GameProfile(
                game_id, text(required(game, "name"), nonempty=True), slots, default_slot,
            ))
        if not self.supported_games:
            raise ValueError("At least one game/format profile is required")
        self.default_filter_rules: list[FilterRule] = [
            FilterRule.from_dict(item) for item in array(description.get("default_filter_rules", []))
        ]
        self._operation = _OperationState()
        self.suggestions: dict[str, str] = {}

    def can_load(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in self.suffixes

    def filter_source_files(self, paths: list[Path], current_source_lang: str) -> list[Path]:
        self._operation.languages.clear()
        self.suggestions = {}
        result = record(self.rpc.call("inspect_paths", {
            "paths": [str(p.resolve()) for p in paths], "source_language": current_source_lang,
        }))
        files = [Path(text(p, nonempty=True)).resolve() for p in array(required(result, "files"))]
        if any(not self.can_load(p) for p in files):
            raise ValueError("解析結果に非対応または存在しないファイルが含まれています。")
        language = text(required(result, "source_language"), nonempty=True)
        if language not in dict(self.supported_languages) or (current_source_lang != "auto" and language != current_source_lang):
            raise ValueError("解析結果の翻訳元言語が不正です。")
        suggestions = {
            key: text(value) for key, value in record(result.get("suggestions", {})).items()
        }
        if any(key not in {"project_name", "game_id"} for key in suggestions):
            raise ValueError("解析結果の提案が不正です。")
        if suggestions.get("game_id") and suggestions["game_id"] not in {g.id for g in self.supported_games}:
            raise ValueError("提案されたゲームIDが未登録です。")
        self._operation.languages = {p: language for p in files}
        self.suggestions = suggestions
        return list(dict.fromkeys(files))

    def detect_source_language(self, path: Path) -> str | None:
        return self._operation.languages.get(path.resolve())

    def load(self, path: Path) -> ImportedTranslation:
        result = imported_from_dict(self.rpc.call("load", {"path": str(path.resolve())}))
        if len(result.project.sources) != 1 or result.project.sources[0].id != str(path.resolve()):
            raise PluginRPCError("protocol", "ソースIDは読み込んだファイルの絶対パスにしてください。")
        return result

class ExecutableExporter:
    def __init__(self, rpc: PluginRPC, description: dict[str, object]) -> None:
        self.rpc = rpc
        self.id = text(required(description, "id"), nonempty=True)
        self.name = text(required(description, "name"), nonempty=True)

    def plan(self, workspaces: list[ImportedTranslation], settings: dict[str, object]) -> list[ExportFile]:
        result = array(self.rpc.call("export_plan", {
            "exporter_id": self.id,
            "workspaces": [{"project": asdict(item.project),
                            "source_refs": {key: asdict(ref) for key, ref in item.source_refs.items()}}
                           for item in workspaces],
            "settings": settings,
        }))
        files: list[ExportFile] = []
        for value in result:
            item = record(value)
            path = Path(text(required(item, "relative_path"), nonempty=True))
            content = base64.b64decode(text(required(item, "content_base64")), validate=True)
            files.append(ExportFile(path, content))
        return files
