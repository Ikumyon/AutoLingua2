from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
import sys

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.ir import TranslationProject
from .base import FileAdapter, PluginAdapter, ImportedTranslation, SourceRef
from .paradox_yaml import ParadoxYamlAdapter


PLUGINS_DIR = PROJECT_ROOT / "plugins"
logger = logging.getLogger(__name__)
_adapters: list[PluginAdapter] | None = None
_errors: list[str] = []


def validate_adapter(adapter: PluginAdapter) -> None:
    for name in ("id", "name", "suffixes", "supported_languages", "supported_games", "default_filter_rules"):
        if not hasattr(adapter, name):
            raise ValueError(f"Missing adapter attribute: {name}")
    if not isinstance(adapter.id, str) or not adapter.id.strip():
        raise ValueError("Adapter ID must be a nonempty string")
    for name in ("can_load", "load", "save", "output_name", "detect_source_language",
                 "filter_source_files", "create_creation_panel", "on_paths_dropped",
                 "on_game_selected", "format_target_path_label", "dispose_creation_panel",
                 "on_ui_language_changed"):
        if not callable(getattr(adapter, name, None)):
            raise ValueError(f"Missing adapter method: {name}")
    language_ids = [code for code, _ in adapter.supported_languages]
    if not language_ids or len(language_ids) != len(set(language_ids)):
        raise ValueError("Invalid supported languages")
    if not adapter.supported_games:
        raise ValueError("At least one game/format profile is required")
    ids: set[str] = set()
    for game in adapter.supported_games:
        if not game.id or game.id in ids:
            raise ValueError(f"Duplicate/empty game ID: {game.id}")
        ids.add(game.id)
        slots = [code for code, _ in game.available_slots]
        if len(slots) != len(set(slots)) or any(not code for code in slots):
            raise ValueError(f"Invalid slots: {game.id}")
        if (slots and game.default_slot not in slots) or (not slots and game.default_slot):
            raise ValueError(f"Invalid default slot: {game.id}")


def discover_external_adapters() -> list[PluginAdapter]:
    """plugins/ ディレクトリ内の外部プラグインを自動検出してインスタンスを返す。"""
    adapters: list[PluginAdapter] = []
    if not PLUGINS_DIR.exists():
        return adapters

    for item in sorted(PLUGINS_DIR.iterdir()):
        if item.name.startswith(("_", ".")) or item.name == "ai_providers":
            continue
        entry_file: Path | None = None
        module_name = f"autolingua2_plugin_{item.stem}"

        if item.is_dir():
            for candidate in ("__init__.py", "plugin.py", "adapter.py"):
                candidate_path = item / candidate
                if candidate_path.is_file():
                    entry_file = candidate_path
                    break
        elif item.is_file() and item.suffix == ".py":
            entry_file = item

        manifest = item / "plugin.json" if item.is_dir() else None
        if entry_file is None and (manifest is None or not manifest.is_file()):
            continue

        try:
            if manifest is not None and manifest.is_file():
                if entry_file is not None:
                    raise ValueError("Pythonエントリーとplugin.jsonは併記できません。")
                from .executable import ExecutableAdapter
                adapter = ExecutableAdapter(manifest)
                validate_adapter(adapter)
                adapters.append(adapter)
                logger.info("plugin=%s operation=describe loaded", adapter.id)
                continue
            spec = importlib.util.spec_from_file_location(
                module_name, entry_file,
                submodule_search_locations=[str(item)] if item.is_dir() else None)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            adapter = module.get_adapter()
            validate_adapter(adapter)
            adapters.append(adapter)
            logger.info("plugin=%s operation=import loaded", adapter.id)
        except Exception as exc:
            _errors.append(f"{item.name}: {exc}")
            logger.exception("plugin=%s operation=import failed", item.name)
            for key in list(sys.modules):
                if key == module_name or key.startswith(module_name + "."):
                    del sys.modules[key]

    return adapters


def get_all_adapters() -> list[PluginAdapter]:
    """標準同梱プラグイン（Paradox YAML）と外部プラグインの全リストを返す。"""
    global _adapters
    if _adapters is None:
        adapters: list[PluginAdapter] = [ParadoxYamlAdapter()]
        validate_adapter(adapters[0])
        ids = {adapters[0].id}
        for adapter in discover_external_adapters():
            if adapter.id in ids:
                message = f"Duplicate adapter ID: {adapter.id}"
                _errors.append(message)
                logger.error(message)
                continue
            ids.add(adapter.id)
            adapters.append(adapter)
        _adapters = adapters
    return list(_adapters)


def plugin_errors() -> list[str]:
    get_all_adapters()
    return list(_errors)


def adapter_by_id(adapter_id: str) -> PluginAdapter:
    for adapter in get_all_adapters():
        if adapter.id == adapter_id:
            return adapter
    raise ValueError(f"Adapter not found: {adapter_id}")


def supported_file_filter(adapter: FileAdapter | None = None) -> str:
    suffixes = sorted({f"*{suffix}" for a in ([adapter] if adapter else get_all_adapters()) for suffix in a.suffixes})
    return f"Supported Text ({' '.join(suffixes)});;All Files (*)"


def load_file(path: Path, adapter: FileAdapter | None = None) -> ImportedTranslation:
    adapter = adapter or adapter_for(path)
    if adapter is None or not adapter.can_load(path):
        raise ValueError(f"対応していないファイルです: {path}")
    imported = adapter.load(path)
    imported.project.adapter_id = adapter.id
    return imported


def load_folder(path: Path, adapter: FileAdapter) -> ImportedTranslation:
    return load_paths([path], adapter)


def load_paths(paths: list[Path], adapter: FileAdapter) -> ImportedTranslation:
    from autolingua2.infrastructure.operations import check_cancelled
    files_to_load: list[Path] = []
    seen: set[Path] = set()

    for p in paths:
        check_cancelled()
        resolved = p.resolve()
        if not resolved.exists():
            raise ValueError(f"対象が見つかりません: {p}")
        if resolved.is_dir():
            for child in sorted(resolved.rglob("*")):
                if child.is_file() and adapter.can_load(child) and child not in seen:
                    seen.add(child)
                    files_to_load.append(child)
        elif resolved.is_file():
            if not adapter.can_load(resolved):
                raise ValueError(f"{adapter.name} で読み込めない対象です: {p}")
            if resolved not in seen:
                seen.add(resolved)
                files_to_load.append(resolved)

    imports = []
    for file in files_to_load:
        check_cancelled()
        imports.append(load_file(file, adapter))
    imported = merge_imports(imports)
    imported.project.adapter_id = adapter.id
    return imported


def adapter_for(path: Path) -> PluginAdapter | None:
    matches = [adapter for adapter in get_all_adapters() if adapter.can_load(path)]
    if len(matches) > 1:
        raise ValueError("複数の形式が対応しています。プロジェクト作成画面で形式を選択してください。")
    return matches[0] if matches else None


def merge_imports(imports: list[ImportedTranslation]) -> ImportedTranslation:
    project = TranslationProject()
    source_refs: dict[str, SourceRef] = {}
    for imported in imports:
        if set(source_refs).intersection(imported.source_refs):
            raise ValueError("Duplicate translation unit IDs")
        project.extend(imported.project)
        source_refs.update(imported.source_refs)
    return ImportedTranslation(project=project, source_refs=source_refs)
