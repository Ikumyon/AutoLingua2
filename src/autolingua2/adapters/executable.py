from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from threading import local

from .base import GameProfile
from autolingua2.infrastructure.platform import current_platform
from autolingua2.infrastructure.plugin_rpc import PluginRPC, PluginRPCError
from autolingua2.services.project_store import imported_from_dict


class ExecutableAdapter:
    default_filter_rules = []

    def __init__(self, manifest: Path, platform=current_platform):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("protocol_version") != 1 or not isinstance(data.get("id"), str) or not data["id"]:
            raise ValueError("Invalid plugin manifest version/id")
        self.id = data["id"]
        root = manifest.parent.resolve()
        entry = data["executables"].get(platform.plugin_platform_key())
        if entry is None:
            raise ValueError("現在のOSには未対応です")
        relative = Path(entry["path"])
        executable = (root / relative).resolve()
        if relative.is_absolute() or not executable.is_relative_to(root) or not executable.is_file():
            raise ValueError("実行ファイルはプラグインフォルダ内に配置してください。")
        args = entry["args"]
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise ValueError("Plugin arguments must be a list of strings")
        self.rpc = PluginRPC(self.id, executable, args, root, platform)
        description = self.rpc.call("describe", {})
        self.name = description["name"]
        self.suffixes = set(description["suffixes"])
        if not isinstance(self.name, str) or not self.name or not self.suffixes or any(
                not isinstance(s, str) or not s.startswith(".") for s in self.suffixes):
            raise ValueError("Invalid plugin description")
        self.supported_languages = [tuple(item) for item in description["supported_languages"]]
        self.supported_games = [GameProfile(**game) for game in description["supported_games"]]
        self._operation = local()
        self.suggestions = {}

    def can_load(self, path):
        return path.is_file() and path.suffix.lower() in self.suffixes

    def filter_source_files(self, paths, current_source_lang):
        result = self.rpc.call("inspect_paths", {"paths": [str(p.resolve()) for p in paths],
                                                "source_language": current_source_lang})
        files = [Path(p).resolve() for p in result["files"]]
        if any(not self.can_load(p) for p in files):
            raise ValueError("解析結果に非対応または存在しないファイルが含まれています。")
        language = result["source_language"]
        if language not in dict(self.supported_languages) or (current_source_lang != "auto" and language != current_source_lang):
            raise ValueError("解析結果の翻訳元言語が不正です。")
        self._operation.languages = {p: language for p in files}
        suggestions = result.get("suggestions", {})
        if not isinstance(suggestions, dict) or any(k not in {"project_name", "game_id"} for k in suggestions):
            raise ValueError("解析結果の提案が不正です。")
        if any(not isinstance(v, str) for v in suggestions.values()):
            raise ValueError("提案は文字列で指定してください。")
        if suggestions.get("game_id") and suggestions["game_id"] not in {g.id for g in self.supported_games}:
            raise ValueError("提案されたゲームIDが未登録です。")
        self.suggestions = suggestions
        return list(dict.fromkeys(files))

    def detect_source_language(self, path):
        return getattr(self._operation, "languages", {}).get(path.resolve())

    def load(self, path):
        result = imported_from_dict(self.rpc.call("load", {"path": str(path.resolve())}))
        if len(result.project.sources) != 1 or result.project.sources[0].id != str(path.resolve()):
            raise PluginRPCError("protocol", "ソースIDは読み込んだファイルの絶対パスにしてください。")
        ids = [unit.id for unit in result.project.units]
        if len(ids) != len(set(ids)) or set(ids) != set(result.source_refs) or any(
                ref.source_id != str(path.resolve()) for ref in result.source_refs.values()):
            raise PluginRPCError("protocol", "翻訳項目のIDまたは参照情報が不正です。")
        return result

    def output_name(self, path, project):
        result = self.rpc.call("output_name", {"path": str(path), "project": asdict(project)})
        if not isinstance(result, str) or not result or Path(result).name != result:
            raise PluginRPCError("protocol", "出力ファイル名が不正です。")
        return result

    def save(self, path, imported, project, existing=None):
        result = self.rpc.call("save", {"path": str(path), "imported": asdict(imported),
            "project": asdict(project), "existing": asdict(existing) if existing else None})
        if result is not True:
            raise PluginRPCError("protocol", "保存完了応答が不正です。")

    def create_creation_panel(self, context):
        from autolingua2.ui.creation_panel import CommonCreationPanel
        return CommonCreationPanel(context)

    def on_paths_dropped(self, paths, context):
        return paths

    def on_game_selected(self, game_id, context):
        pass

    def format_target_path_label(self, path: Path, current_source_lang: str) -> tuple[str, str, str]:
        return path.name, "", str(path)

    def dispose_creation_panel(self, panel):
        pass

    def on_ui_language_changed(self, language_code, context):
        pass
