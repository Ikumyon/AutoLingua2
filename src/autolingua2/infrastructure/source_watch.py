from __future__ import annotations

from pathlib import Path

from autolingua2_native import platform
from .filesystem import ASSETS_DIR, PROJECT_ROOT
from .bootstrap import configuration


def watcher_executable() -> Path:
    name = platform.executable_name("autolingua-source-watcher")
    packaged = PROJECT_ROOT / name
    if packaged.is_file():
        return packaged
    return PROJECT_ROOT / "target" / "release" / name


def configure(settings: Path, enabled: bool) -> None:
    from autolingua2_native import source_watch
    source_watch.configure(str(settings.resolve()), str(watcher_executable()), enabled,
                           configuration().command([]) if enabled else [], str(ASSETS_DIR / "images/app.ico"))


def notifications_available() -> bool:
    from autolingua2_native import source_watch
    return source_watch.notifications_available()


def target_settings(settings: Path) -> str:
    from autolingua2_native import source_watch
    return source_watch.target_settings(str(settings.resolve()))


def save_target_settings(settings: Path, data: str) -> None:
    from autolingua2_native import source_watch
    source_watch.save_target_settings(str(settings.resolve()), data)


def preview_sound(path: str) -> None:
    from autolingua2_native import source_watch
    source_watch.preview_sound(path)


def forget_target(settings: Path, project: str) -> None:
    from autolingua2_native import source_watch
    source_watch.forget_target(str(settings.resolve()), project)


def running(settings: Path) -> bool:
    from autolingua2_native import source_watch
    return source_watch.running(str(settings.resolve()))


def status(settings: Path) -> str:
    from autolingua2_native import source_watch
    return source_watch.status(str(settings.resolve()))


def snapshot(settings: Path, project: Path) -> str:
    from autolingua2_native import source_watch
    return source_watch.snapshot(str(settings.resolve()), str(project.resolve()))


def acknowledge(settings: Path, project: Path, observed: str) -> None:
    from autolingua2_native import source_watch
    source_watch.acknowledge(str(settings.resolve()), str(project.resolve()), observed)
