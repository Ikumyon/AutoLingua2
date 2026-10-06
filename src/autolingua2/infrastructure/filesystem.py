import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    # PyInstaller onedir 実行時 (core サブフォルダ配置時は親フォルダを PROJECT_ROOT とする)
    exe_dir = Path(sys.executable).resolve().parent
    PROJECT_ROOT = exe_dir.parent if exe_dir.name.lower() == "core" else exe_dir
    PACKAGE_DIR = exe_dir / "_internal" / "autolingua2"
else:
    PACKAGE_DIR = Path(__file__).resolve().parents[1]
    PROJECT_ROOT = PACKAGE_DIR.parents[1]

try:
    from autolingua2.infrastructure.bootstrap import development_root
except ImportError:
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
else:
    RESOURCE_ROOT = development_root() or Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))

UI_DIR = RESOURCE_ROOT / "ui"
ASSETS_DIR = RESOURCE_ROOT / "assets"
