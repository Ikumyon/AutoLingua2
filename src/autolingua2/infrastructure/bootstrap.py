"""Python's narrow adapter to the shared native bootstrap control plane."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autolingua2_native.bootstrap import CoreSession

_session: CoreSession | None = None
_development_root: Path | None = None


@dataclass(frozen=True)
class LaunchConfiguration:
    launcher: Path
    development_root: Path | None

    def command(self, arguments: list[str]) -> list[str]:
        if not self.launcher.is_file():
            raise FileNotFoundError(f"ランチャーがありません。配布物または開発ビルドを確認してください: {self.launcher}")
        command = [str(self.launcher)]
        if self.development_root is not None:
            command += ["--development-root", str(self.development_root)]
        return command + arguments


def configuration() -> LaunchConfiguration:
    from autolingua2_native import platform as native
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        launcher = exe.parent.parent / native.executable_name("AutoLingua Desktop") if exe.parent.name.lower() == "core" else exe.with_name(native.executable_name("AutoLingua Desktop"))
        return LaunchConfiguration(launcher, None)
    root = Path(__file__).resolve().parents[3]
    return LaunchConfiguration(root / "target" / "release" / native.executable_name("autolingua-launcher"), root)


def launcher_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith("AUTOLINGUA_"):
            del environment[key]
    if getattr(sys, "frozen", False):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def spawn_launcher(arguments: list[str], environment: dict[str, str]) -> None:
    from autolingua2_native import platform as native
    native.spawn_launcher(configuration().command(arguments), environment)


def enter() -> bool:
    """Return False after forwarding a public invocation; True for an authenticated core."""
    global _development_root, _session
    credential = os.environ.pop("AUTOLINGUA_BOOT_TOKEN", None)
    raw_development_root = os.environ.get("AUTOLINGUA_DEVELOPMENT_ROOT")
    _development_root = Path(raw_development_root).resolve() if raw_development_root else None
    # Children/plugins must not inherit bootstrap credentials or internal launch context.
    os.environ.pop("AUTOLINGUA_DEVELOPMENT_ROOT", None)
    os.environ.pop("AUTOLINGUA_LAUNCHER", None)
    if credential is None:
        spawn_launcher(sys.argv[1:], launcher_environment())
        return False
    from autolingua2_native import bootstrap as native
    root = configuration().development_root
    _session = native.CoreSession(credential, str(root) if root is not None else None)
    return True


def development_root() -> Path | None:
    return _development_root


def session() -> CoreSession:
    if _session is None:
        raise RuntimeError("起動管理セッションがありません。ランチャーから起動してください。")
    return _session


def close() -> None:
    global _session
    current = _session
    _session = None
    if current is not None:
        current.close()


def restart(debug: bool) -> None:
    current = session()
    ticket = current.prepare_restart()
    arguments = [arg for arg in sys.argv[1:] if arg != "--debug"]
    if debug:
        arguments.append("--debug")
    environment = launcher_environment()
    environment["AUTOLINGUA_RESTART_TICKET"] = ticket
    environment["AUTOLINGUA_RESTART_PID"] = str(os.getpid())
    try:
        spawn_launcher(arguments, environment)
        current.wait_restart()
    except Exception:
        current.cancel_restart()
        raise
