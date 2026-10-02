from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
NATIVE = ROOT / "build" / "native"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if NATIVE.exists() and str(NATIVE) not in sys.path:
    sys.path.insert(0, str(NATIVE))

from autolingua2.app import main


if __name__ == "__main__":
    raise SystemExit(main())
