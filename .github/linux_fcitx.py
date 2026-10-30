"""Linux distribution-only Fcitx plugin build and static bundle validation.

Called by the spec for both CI and local PyInstaller builds. No IM environment
variables are changed and neither the application nor the plugin is executed.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.request

from PySide6.QtCore import QLibraryInfo, QPluginLoader, qVersion


VERSION = "5.1.16"
COMMIT = "115750044f3d0db16ca5859808c7da830fd1ff52"
REPOSITORY = "https://github.com/fcitx/fcitx5-qt.git"
PLUGIN = "libfcitx5platforminputcontextplugin.so"
PLUGIN_DIR = Path("PySide6/Qt/plugins/platforminputcontexts")
QT_LIB = Path("PySide6/Qt/lib")
NOTICES = Path("licenses/fcitx")
# glibc and its loader belong to the target OS. All other linked dependencies
# (including libstdc++/libgcc) are collected recursively, rather than assumed.
HOST_LIBS = re.compile(r"^(lib(c|m|dl|pthread|rt|resolv|util)\.so\.|ld-linux)")


def run(*args: str) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as error:
        # 共有ライブラリ不足など、子プロセスが出した原因をCIログに残す。
        raise RuntimeError(
            f"コマンドが失敗しました（終了コード {error.returncode}）: {args}\n{error.output}"
        ) from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def dynamic(path: Path) -> tuple[list[str], list[str]]:
    info = run("readelf", "-d", str(path))
    needed = re.findall(r"\(NEEDED\).*?\[(.*?)\]", info)
    paths = re.findall(r"\((?:RPATH|RUNPATH)\).*?\[(.*?)\]", info)
    require(all("/" not in name for name in needed), f"Absolute dependency: {path}")
    return needed, paths


def metadata(path: Path) -> None:
    # metaData reads the Qt metadata section; do not call load()/instance().
    data = QPluginLoader(str(path)).metaData()
    major, minor, patch = map(int, qVersion().split("."))
    require(data.get("version") == (major << 16 | minor << 8 | patch),
            f"Fcitx plugin Qt version differs from runtime Qt {qVersion()}: {data}")
    require("fcitx" in data.get("MetaData", {}).get("Keys", []),
            f"Missing fcitx input method key: {path}")


def package_license(library: Path, destination: Path) -> None:
    # The supported Linux distribution builder is Ubuntu/Debian, as in CI.
    candidates = [library, library.resolve()]
    if str(library).startswith("/usr/lib/"):
        candidates.append(Path(str(library).removeprefix("/usr")))
    for candidate in candidates:
        result = subprocess.run(["dpkg-query", "-S", str(candidate)],
                                text=True, capture_output=True, check=False)
        if result.returncode == 0:
            package = result.stdout.split(": ", 1)[0]
            copyright_file = Path("/usr/share/doc") / package.split(":")[0] / "copyright"
            if copyright_file.is_file():
                shutil.copy2(copyright_file, destination / (package.replace(":", "_") + ".copyright"))
                for name in set(re.findall(r"/usr/share/common-licenses/([\w.+-]+)",
                                           copyright_file.read_text())):
                    # 文末のピリオドを除き、LGPL-2.1など名前の途中のドットは保持する。
                    name = name.rstrip(".")
                    common = Path("/usr/share/common-licenses") / name
                    require(common.is_file(), f"Missing referenced license: {common}")
                    target = destination / "common-licenses"
                    target.mkdir(exist_ok=True)
                    shutil.copy2(common, target / name)
                return
    raise RuntimeError(f"Cannot collect runtime dependency license: {library}")


def prepare() -> tuple[list[tuple[str, str]], list[tuple[str, str]], Path]:
    require(sys.platform == "linux", "Fcitx distribution build is Linux-only")
    require(platform.machine() == "x86_64", "Current Linux distribution target is x86_64")
    for tool in ("git", "cmake", "ninja", "readelf", "patchelf", "ldconfig", "dpkg-query"):
        require(shutil.which(tool) is not None, f"Missing build prerequisite: {tool}")
    root = Path("build/linux-fcitx").resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source"
    if not source.exists():
        run("git", "clone", "--branch", VERSION, "--single-branch", REPOSITORY, str(source))
    run("git", "-C", str(source), "fetch", "origin", f"refs/tags/{VERSION}")
    require(run("git", "-C", str(source), "rev-parse", "FETCH_HEAD^{commit}") == COMMIT,
            "Fcitx source tag no longer matches pinned commit")
    require(not run("git", "-C", str(source), "status", "--porcelain"),
            "Fcitx source checkout contains local changes")
    run("git", "-C", str(source), "checkout", "--detach", COMMIT)

    qt_version = qVersion()
    sdk_override = os.environ.get("AUTOLINGUA_QT_SDK")
    if sdk_override:
        sdk = Path(sdk_override).resolve()
    else:
        sdk = root / "sdk" / qt_version / "gcc_64"
        if not (sdk / "bin/qmake").is_file() or not any((sdk / "lib").glob("libicuuc.so*")):
            # qmakeなどのSDKツールにもICUが必要。旧処理で取得済みのSDKも補完する。
            # ビルド専用のSDKはdatasに含めない。
            run(sys.executable, "-m", "aqt", "install-qt", "linux", "desktop",
                qt_version, "linux_gcc_64", "-O", str(root / "sdk"),
                "--archives", "qtbase", "qtwayland", "icu")
    require(run(str(sdk / "bin/qmake"), "-query", "QT_VERSION") == qt_version,
            f"SDK Qt version must exactly match PySide6 runtime Qt {qt_version}")
    build = root / "cmake"
    # Remove the CMake cache when the SDK changes, without discarding source/SDK.
    cache = build / "CMakeCache.txt"
    if cache.exists():
        cache.unlink()
    run("cmake", "-S", str(source), "-B", str(build), "-G", "Ninja",
        f"-DCMAKE_PREFIX_PATH={sdk}", f"-DQt6_DIR={sdk}/lib/cmake/Qt6",
        "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_SKIP_RPATH=ON",
        f"-DCMAKE_CXX_FLAGS=-ffile-prefix-map={root}=. -ffile-prefix-map={sdk}=QtSDK",
        "-DENABLE_QT4=OFF", "-DENABLE_QT5=OFF", "-DENABLE_QT6=ON",
        "-DBUILD_ONLY_PLUGIN=ON", "-DENABLE_X11=ON",
        "-DENABLE_QT6_WAYLAND_WORKAROUND=ON")
    qt_dirs = re.findall(r"^Qt6\w*_DIR:PATH=(.+)$", cache.read_text(), re.MULTILINE)
    require(bool(qt_dirs) and all(Path(p).resolve().is_relative_to(sdk) for p in qt_dirs),
            "CMake selected Qt components outside the matching SDK")
    run("cmake", "--build", str(build), "--target", "fcitx5platforminputcontextplugin-qt6")
    plugin = build / "qt6/platforminputcontext" / PLUGIN
    require(plugin.is_file(), f"Missing generated plugin: {plugin}")
    run("patchelf", "--set-rpath", "$ORIGIN/../../lib:$ORIGIN/../../../..", str(plugin))
    metadata(plugin)

    licenses = root / "licenses"
    licenses.mkdir(exist_ok=True)
    for license_file in (source / "LICENSES").glob("*.txt"):
        shutil.copy2(license_file, licenses / license_file.name)
    # Include exact corresponding source, preserving per-file copyright notices.
    run("git", "-C", str(source), "archive", "--format=tar.gz",
        f"--output={licenses / 'fcitx5-qt-source.tar.gz'}", COMMIT)
    for name in ("LGPL-3.0-only", "GPL-3.0-only"):
        urllib.request.urlretrieve(
            f"https://raw.githubusercontent.com/qt/qtbase/v{qt_version}/LICENSES/{name}.txt",
            licenses / f"Qt-{name}.txt")

    wheel_lib = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.LibrariesPath))
    system: dict[str, Path] = {}
    for name, path in re.findall(r"^\s*(\S+) .*?=> (\S+)$", run("ldconfig", "-p"), re.MULTILINE):
        system.setdefault(name, Path(path))
    binaries = [(str(plugin), str(PLUGIN_DIR))]
    pending = [plugin]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        needed, _ = dynamic(current)
        for name in needed:
            if name in seen:
                continue
            seen.add(name)
            if HOST_LIBS.match(name):
                require(name in system, f"Missing OS runtime dependency: {name}")
                continue
            wheel_file = wheel_lib / name
            dependency = wheel_file if wheel_file.is_file() else system.get(name)
            require(dependency is not None and dependency.is_file(), f"Missing dependency: {name}")
            assert dependency is not None
            require(not dependency.resolve().is_relative_to(sdk), f"SDK runtime selected: {dependency}")
            if name.startswith("libQt6"):
                require(dependency == wheel_file, f"Qt dependency is outside PySide6: {dependency}")
            else:
                package_license(dependency, licenses)
            binaries.append((str(dependency), str(QT_LIB) if name.startswith("libQt6") else "."))
            pending.append(dependency)
    datas = [(str(file), str(NOTICES / file.relative_to(licenses).parent))
             for file in licenses.rglob("*") if file.is_file()]
    return binaries, datas, sdk


def verify(core: Path, sdk: Path) -> None:
    internal = core / "_internal"
    plugin = internal / PLUGIN_DIR / PLUGIN
    require(plugin.is_file(), "Fcitx plugin missing from distribution")
    metadata(plugin)
    runtime_core = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.LibrariesPath)) / "libQt6Core.so.6"
    bundled_core = internal / QT_LIB / "libQt6Core.so.6"
    require(bundled_core.is_file(), "Distribution QtCore is missing")
    with bundled_core.open("rb") as bundled, runtime_core.open("rb") as runtime:
        require(hashlib.file_digest(bundled, "sha256").digest()
                == hashlib.file_digest(runtime, "sha256").digest(),
                "Distribution QtCore differs from the PySide6 runtime used to build Fcitx")
    for name in ("BSD-3-Clause.txt", "LGPL-2.1-or-later.txt", "fcitx5-qt-source.tar.gz",
                 "Qt-LGPL-3.0-only.txt", "Qt-GPL-3.0-only.txt"):
        require((internal / NOTICES / name).is_file(), f"Missing license/source: {name}")
    for directory in ("include", "mkspecs", "lib/cmake"):
        require(not (internal / "PySide6/Qt" / directory).exists(), f"SDK files bundled: {directory}")
    for file in internal.rglob("*"):
        if file.is_file():
            with file.open("rb") as binary:
                if binary.read(4) == b"\x7fELF":
                    require(str(sdk).encode() not in binary.read(), f"Build SDK path remains: {file}")
    # Inspect ELF metadata only: never use ldd or load the plugin to verify it.
    pending = [plugin]
    visited: set[Path] = set()
    while pending:
        current = pending.pop().resolve()
        if current in visited:
            continue
        visited.add(current)
        require(str(sdk).encode() not in current.read_bytes(), f"Build SDK path remains: {current}")
        needed, paths = dynamic(current)
        require(all(not entry.startswith("/") for value in paths for entry in value.split(":")),
                f"Absolute ELF search path: {current}: {paths}")
        # Model the actual $ORIGIN search paths, with PyInstaller's _internal
        # LD_LIBRARY_PATH fallback. Do not accept dependencies from the host.
        search = [Path(entry.replace("${ORIGIN}", str(current.parent)).replace("$ORIGIN", str(current.parent)))
                  for value in paths for entry in value.split(":") if entry]
        search.append(internal)
        for name in needed:
            if HOST_LIBS.match(name):
                continue
            resolved = next((folder / name for folder in search if (folder / name).is_file()), None)
            require(resolved is not None, f"Unresolved packaged dependency {name}: {current}")
            assert resolved is not None
            require(resolved.resolve().is_relative_to(internal.resolve()), f"External dependency: {resolved}")
            pending.append(resolved)
