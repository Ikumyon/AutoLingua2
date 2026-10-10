"""File-shaped workspace archives. Original paths are records, never IO inputs."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from io import BytesIO
import json
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from zipfile import ZIP_DEFLATED, ZipFile

from PySide6.QtCore import QIODevice, QSaveFile

from autolingua2.ir.imported import ImportedTranslation, SourceRef
from autolingua2.ir.project import TranslationProject, TranslationSource
from autolingua2.ir.state import UnitState
from autolingua2.ir.unit import TranslationUnit
from autolingua2.ir.validation import array, record, required, text
from autolingua2.ir.workspace import TranslationRecord, Workspace
from autolingua2.services.workspaces import Language, WorkspaceService, normalize_language_code
from autolingua2.adapters.base import FileAdapter
from autolingua2.services.source_classification import classify_sources


@dataclass
class ProjectArchive:
    imported: ImportedTranslation
    workspaces: dict[str, Workspace]
    languages: dict[str, Language]


def relative_path(value: str) -> str:
    if (not value or "\\" in value or ":" in value or "\x00" in value
            or PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError(f"不正な相対パスです: {value}")
    return value


def _absolute_path(value: str) -> PurePath:
    path = PureWindowsPath(value) if PureWindowsPath(value).drive else PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError(f"不正な読み込み元の絶対パスです: {value}")
    return path


def _relative_files(root_name: str, files: list[str], folders: list[str]) -> list[str]:
    root = _absolute_path(root_name)
    file_paths = [_absolute_path(value) for value in files]
    folder_paths = [_absolute_path(value) for value in folders]
    if len(set(file_paths)) != len(files) or len(set(folder_paths)) != len(folders):
        raise ValueError("読み込み元のファイルまたはフォルダが重複しています。")
    for path in [*file_paths, *folder_paths]:
        if type(path) is not type(root) or not path.is_relative_to(root):
            raise ValueError("読み込み元が記録されたルートの外にあります。")
    for path in file_paths:
        if path.parent not in folder_paths or path in folder_paths:
            raise ValueError("読み込み元のファイル構造が不正です。")
    return [relative_path(path.relative_to(root).as_posix()) for path in file_paths]


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def project_documents(service: WorkspaceService) -> dict[str, object]:
    project = service.imported.project
    paths = _relative_files(project.source_root, project.loaded_files, project.loaded_folders)
    if paths != [source.id for source in project.sources]:
        raise ValueError("読み込み元と原文ファイルの対応が一致しません。")
    documents: dict[str, object] = {
        "project.json": {
            "format_version": 1, "name": project.name, "plugin_id": project.adapter_id,
            "game_id": project.game_id, "source_slot": project.source_slot,
            "source_language": project.source_language,
            "source_root": project.source_root, "files": project.loaded_files,
            "folders": project.loaded_folders, "workspaces": list(service.workspaces),
        },
    }
    for name, workspace in service.workspaces.items():
        language = service.languages.get(workspace.language_code)
        if language is None:
            raise ValueError("ワークスペースの言語が登録されていません。")
        prefix = f"workspaces/{name}/"
        documents[prefix + "workspace.json"] = {
            "language_code": workspace.language_code, "language_name": language.name,
            "output_slot": workspace.output_slot,
        }
        for source in project.sources:
            entries: list[dict[str, object]] = []
            for unit in project.units:
                ref = service.imported.source_refs.get(unit.id)
                if ref is None:
                    raise ValueError("原文ファイルとの対応がありません。")
                if ref.source_id != source.id:
                    continue
                entry = workspace.records.get(unit.id)
                if entry is None:
                    raise ValueError("ワークスペースの翻訳行がありません。")
                entries.append({"key": ref.external_id, "original": unit.source_text,
                                "translation": entry.target_text, "state": entry.state.value,
                                "context": unit.context,
                                "source_changed": entry.source_changed})
            documents[prefix + f"files/{relative_path(source.id)}.json"] = entries
    return documents


def project_snapshot(service: WorkspaceService) -> bytes:
    return _json_bytes(project_documents(service))


def save_project(path: Path, service: WorkspaceService) -> None:
    documents = project_documents(service)
    _restore(documents)
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, document in documents.items():
            archive.writestr(name, _json_bytes(document))
    payload = buffer.getvalue()
    output = QSaveFile(str(path))
    output.setDirectWriteFallback(False)
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if output.write(payload) != len(payload):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())


def _restore(documents: dict[str, object]) -> ProjectArchive:
    metadata = record(required(documents, "project.json"))
    version = required(metadata, "format_version")
    if type(version) is not int or version != 1:
        raise ValueError("未対応のプロジェクト形式です。")
    files = [text(value, nonempty=True) for value in array(required(metadata, "files"))]
    folders = [text(value, nonempty=True) for value in array(required(metadata, "folders"))]
    root = text(required(metadata, "source_root"), nonempty=True)
    paths = _relative_files(root, files, folders)
    project = TranslationProject(
        name=text(required(metadata, "name")), adapter_id=text(required(metadata, "plugin_id"), nonempty=True),
        game_id=text(required(metadata, "game_id")), source_slot=text(required(metadata, "source_slot")),
        source_language=text(required(metadata, "source_language"), nonempty=True),
        source_root=root, loaded_files=files, loaded_folders=folders,
        sources=[TranslationSource(path, PurePosixPath(path).name) for path in paths],
    )
    names = [text(value, nonempty=True) for value in array(required(metadata, "workspaces"))]
    if not names or len(names) != len(set(names)):
        raise ValueError("ワークスペース一覧が不正です。")
    expected = {"project.json"}
    languages: dict[str, Language] = {}
    restored: dict[str, Workspace] = {}
    refs: dict[str, SourceRef] = {}
    originals: dict[str, dict[str, tuple[str, str]]] = {}
    for name in names:
        if normalize_language_code(name) != name:
            raise ValueError("ワークスペース名が不正です。")
        prefix = f"workspaces/{name}/"
        workspace_file = prefix + "workspace.json"
        expected.add(workspace_file)
        data = record(required(documents, workspace_file))
        code = text(required(data, "language_code"), nonempty=True)
        if normalize_language_code(code) != code or name != code:
            raise ValueError("ワークスペースの言語コードが一致しません。")
        language = Language(code, text(required(data, "language_name"), nonempty=True))
        if code in languages and languages[code] != language:
            raise ValueError("同じ言語の表示名が一致しません。")
        languages[code] = language
        slot = text(required(data, "output_slot"))
        workspace = Workspace(code, output_slot=slot)
        for path in paths:
            filename = prefix + f"files/{path}.json"
            expected.add(filename)
            entries = array(required(documents, filename))
            seen: dict[str, tuple[str, str]] = {}
            for item in entries:
                row = record(item)
                if not {"key", "original", "translation", "state"} <= set(row) or not set(row) <= {
                    "key", "original", "translation", "state", "context", "source_changed"
                }:
                    raise ValueError("翻訳行の項目が不正です。")
                key = text(required(row, "key"), nonempty=True)
                if key in seen:
                    raise ValueError(f"同じファイルにキーが重複しています: {path}: {key}")
                original = text(required(row, "original"))
                context = text(row.get("context", PurePosixPath(path).name))
                seen[key] = (original, context)
                unit_id = f"{path}#{key}"
                source_changed = row.get("source_changed", False)
                if type(source_changed) is not bool:
                    raise ValueError("原文更新状態が不正です。")
                workspace.records[unit_id] = TranslationRecord(
                    text(required(row, "translation")), UnitState(text(required(row, "state"))),
                    source_changed,
                )
                if name == names[0]:
                    project.units.append(TranslationUnit(
                        id=unit_id, label=key, source_text=original, context=context,
                    ))
                    refs[unit_id] = SourceRef(path, key)
            if name == names[0]:
                originals[path] = seen
            elif seen != originals[path]:
                raise ValueError(f"原文とワークスペースのキーまたは原文が一致しません: {path}")
        restored[name] = workspace
    if set(documents) != expected:
        raise ValueError("プロジェクト内のファイル構成が不正です。")
    return ProjectArchive(ImportedTranslation(project, refs), restored, languages)


def load_project(path: Path, adapters: Mapping[str, FileAdapter]) -> ProjectArchive:
    documents: dict[str, object] = {}
    with ZipFile(path, "r") as archive:
        for info in archive.infolist():
            relative_path(info.filename)
            if info.filename in documents or info.is_dir():
                raise ValueError("プロジェクト内のファイルが重複または不正です。")
            documents[info.filename] = json.loads(archive.read(info).decode("utf-8"), object_pairs_hook=_unique_object)
    restored = _restore(documents)
    adapter = adapters.get(restored.imported.project.adapter_id)
    if adapter is None:
        raise ValueError("プロジェクトの読み込み方式がありません。")
    classify_sources(restored.imported, adapter)
    return restored


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON項目が重複しています: {key}")
        result[key] = value
    return result
