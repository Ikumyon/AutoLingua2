import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    # PyInstaller onedir 実行時 (exe と同じディレクトリ)
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    PACKAGE_DIR = PROJECT_ROOT / "_internal" / "autolingua2"
else:
    PACKAGE_DIR = Path(__file__).resolve().parents[1]
    PROJECT_ROOT = PACKAGE_DIR.parents[1]

UI_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "ui"
