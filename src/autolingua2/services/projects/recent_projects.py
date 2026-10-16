"""Recent project history stored independently of application preferences."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

from autolingua2.infrastructure.filesystem import DATA_DIR
from autolingua2.infrastructure.platform import qt_file_path
from autolingua2.ir.validation import array, record, required, text


HISTORY_PATH = DATA_DIR / "recent_projects.json"
MAX_RECENT_PROJECTS = 20


@dataclass(frozen=True, slots=True)
class RecentProject:
    name: str
    path: Path


def load_recent_projects() -> list[RecentProject]:
    try:
        document = HISTORY_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    projects: list[RecentProject] = []
    seen: set[Path] = set()
    for value in array(json.loads(document)):
        entry = record(value)
        path = Path(text(required(entry, "path"), nonempty=True))
        name = text(required(entry, "name"), nonempty=True)
        if not path.is_absolute():
            raise ValueError("プロジェクト履歴のパスは絶対パスである必要があります。")
        if path not in seen:
            projects.append(RecentProject(name, path))
            seen.add(path)
    return projects[:MAX_RECENT_PROJECTS]


def remember_project(path: Path, name: str) -> None:
    path = path.resolve()
    projects = [RecentProject(name or path.stem, path)]
    projects.extend(project for project in load_recent_projects() if project.path != path)
    payload = json.dumps(
        [{"name": project.name, "path": str(project.path)} for project in projects[:MAX_RECENT_PROJECTS]],
        ensure_ascii=False, indent=2,
    ).encode("utf-8")
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = QSaveFile(qt_file_path(HISTORY_PATH))
    output.setDirectWriteFallback(False)
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if output.write(payload) != len(payload):
        error = output.errorString()
        output.cancelWriting()
        raise OSError(error)
    if not output.commit():
        raise OSError(output.errorString())
