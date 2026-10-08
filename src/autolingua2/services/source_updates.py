from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import json
import logging
from pathlib import Path

from autolingua2.adapters.base import FileAdapter
from autolingua2.infrastructure import source_watch
from autolingua2.ir.imported import ImportedTranslation
from autolingua2.ir.project import TranslationProject
from autolingua2.ir.source_watch import WatchSettings, WatchTarget
from autolingua2.ir.validation import record
from autolingua2.ir.workspace import TranslationRecord
from autolingua2.services.project_archive import save_project
from autolingua2.services.project_io import import_project
from autolingua2.services.settings_store import load_watch_settings, save_watch_settings, settings_path
from autolingua2.services.workspaces import WorkspaceService


@dataclass(frozen=True, slots=True)
class SourceChange:
    kind: str
    unit_id: str
    before: str
    after: str


@dataclass(slots=True)
class SourceUpdate:
    target: WatchTarget
    observed: str
    imported: ImportedTranslation
    changes: list[SourceChange]


@dataclass(slots=True)
class AppliedUpdate:
    service: WorkspaceService
    acknowledgment_error: str = ""


def apply_watch_settings(settings: WatchSettings) -> None:
    old = load_watch_settings()
    save_watch_settings(settings)
    try:
        retained = {entry.source_root for entry in settings.targets}
        for entry in old.targets:
            if entry.source_root not in retained:
                source_watch.forget_target(settings_path(), entry.source_root)
        if settings.enabled != old.enabled:
            source_watch.configure(settings_path(), settings.enabled)
    except (OSError, ImportError, AttributeError) as exc:
        logging.getLogger(__name__).exception("Watcher settings update failed")
        save_watch_settings(old)
        try:
            source_watch.configure(settings_path(), old.enabled)
        except (OSError, ImportError, AttributeError):
            logging.getLogger(__name__).exception("Watcher state rollback failed")
        raise OSError("監視設定を反映できませんでした。ネイティブモジュールとデーモンのビルドを確認してください。") from exc


def notifications_available() -> bool:
    return source_watch.notifications_available()


def set_project_notification(project: TranslationProject, path: Path | None, registered: bool, adapter: FileAdapter | None = None) -> None:
    if not notifications_available():
        raise ValueError("この環境では更新通知を利用できません。")
    settings = load_watch_settings()
    if not project.source_root:
        raise ValueError("翻訳元フォルダが指定されていません。")
    root = str(Path(project.source_root).resolve())
    existing = next((entry for entry in settings.targets if entry.source_root == root), None)
    if registered and existing is not None:
        existing.project_path = str(path.resolve()) if path is not None else existing.project_path
        if adapter is not None:
            existing.adapter_id = adapter.id
            existing.source_language = project.source_language
        apply_watch_settings(settings)
        return
    settings.targets = [entry for entry in settings.targets if entry.source_root != root]
    if registered:
        if adapter is None:
            raise ValueError("このプロジェクトの読み込み方式がありません。")
        target = register_target(Path(root), project.name, sorted(adapter.suffixes))
        target.project_path = str(path.resolve()) if path is not None else ""
        target.adapter_id = adapter.id
        target.source_language = project.source_language
        settings.targets.append(target)
    apply_watch_settings(settings)


def validate_notification_file(path: str, *, sound: bool) -> str:
    candidate = Path(path).resolve()
    suffixes = {".wav"} if sound else {".png", ".jpg", ".jpeg"}
    if not candidate.is_file() or candidate.suffix.lower() not in suffixes:
        raise ValueError("通知音はWAV、画像はPNG/JPEGのファイルを指定してください。")
    return str(candidate)


def preview_notification_sound(path: str) -> None:
    source_watch.preview_sound(validate_notification_file(path, sound=True) if path else "")


def notification_target(path: Path) -> WatchTarget:
    settings = load_watch_settings()
    project = str(path.resolve())
    if not settings.enabled:
        raise ValueError("このプロジェクトは現在の通知対象ではありません。")
    target = next((target for target in settings.targets if target.source_root == project), None)
    if target is None:
        raise ValueError("このプロジェクトは監視対象ではありません。")
    return target


def import_notification_target(target: WatchTarget, adapter: FileAdapter) -> ImportedTranslation:
    root = Path(target.source_root)
    return import_project(adapter, [root], target.source_language, source_root=root, allow_empty=True)


def ensure_watcher() -> None:
    settings = load_watch_settings()
    if settings.enabled:
        save_watch_settings(settings)
        source_watch.configure(settings_path(), True)


def watch_status() -> tuple[bool, dict[str, object]]:
    return source_watch.running(settings_path()), record(json.loads(source_watch.status(settings_path())))


def register_target(root: Path, name: str, suffixes: list[str]) -> WatchTarget:
    if not root.is_dir():
        raise ValueError("翻訳元フォルダがありません。")
    return WatchTarget("", name or root.name, str(root.resolve()), sorted(suffixes))


def pending_target(path: Path) -> tuple[WatchTarget | None, str]:
    settings = load_watch_settings()
    if not settings.enabled:
        return None, ""
    name = str(path.resolve())
    target = next((target for target in settings.targets if target.source_root == name), None)
    if target is None:
        return None, ""
    _, state = watch_status()
    data = state.get(name)
    if data is None:
        return None, ""
    entry = record(data)
    error = entry.get("error")
    if isinstance(error, str) and error:
        raise OSError(error)
    current = entry.get("current")
    if current is None or current == entry.get("baseline"):
        return None, ""
    return target, json.dumps(current, sort_keys=True)


def prepare_update(service: WorkspaceService, target: WatchTarget, adapter: FileAdapter) -> SourceUpdate:
    path = Path(target.source_root)
    observed = source_watch.snapshot(settings_path(), path)
    root = Path(target.source_root)
    imported = import_project(adapter, [root], service.imported.project.source_language,
                              source_root=root, allow_empty=True)
    if source_watch.snapshot(settings_path(), path) != observed:
        raise ValueError("読み込み中に翻訳元が変更されました。もう一度確認してください。")
    old = {unit.id: unit for unit in service.imported.project.units}
    new = {unit.id: unit for unit in imported.project.units}
    changes: list[SourceChange] = []
    for unit_id, unit in new.items():
        previous = old.get(unit_id)
        if previous is None:
            changes.append(SourceChange("追加", unit_id, "", unit.source_text))
        elif (previous.source_text, previous.context) != (unit.source_text, unit.context):
            changes.append(SourceChange("変更", unit_id, previous.source_text, unit.source_text))
    for unit_id, unit in old.items():
        if unit_id not in new:
            changes.append(SourceChange("削除", unit_id, unit.source_text, ""))
    return SourceUpdate(target, observed, imported, changes)


def apply_update(service: WorkspaceService, update: SourceUpdate, path: Path | None) -> AppliedUpdate:
    root = Path(update.target.source_root)
    if source_watch.snapshot(settings_path(), root) != update.observed:
        raise ValueError("確認後に翻訳元が変更されました。差分を再確認してください。")
    candidate = deepcopy(service)
    project = update.imported.project
    candidate.imported = ImportedTranslation(
        replace(service.imported.project, sources=project.sources, units=project.units,
                source_root=project.source_root, loaded_files=project.loaded_files,
                loaded_folders=project.loaded_folders),
        update.imported.source_refs,
    )
    changed = {change.unit_id for change in update.changes if change.kind == "変更"}
    for workspace in candidate.workspaces.values():
        records: dict[str, TranslationRecord] = {}
        for unit in project.units:
            entry = workspace.records.get(unit.id, TranslationRecord())
            if unit.id in changed:
                entry.source_changed = True
            records[unit.id] = entry
        workspace.records = records
    if path is not None:
        save_project(path, candidate)
    error = ""
    try:
        source_watch.acknowledge(settings_path(), root, update.observed)
    except OSError as exc:
        # The project is already saved; retain it even if acknowledgment fails.
        error = str(exc)
    return AppliedUpdate(candidate, error)
