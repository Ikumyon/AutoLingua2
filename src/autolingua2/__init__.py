import sys
from pathlib import Path

_version_root = Path(__file__).resolve().parents[1 if getattr(sys, "frozen", False) else 2]
__version__ = (_version_root / "VERSION").read_text(encoding="utf-8").strip()
