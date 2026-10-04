from __future__ import annotations
from pathlib import Path
from autolingua2_native import (
    detect_encoding as native_detect_encoding,
    read_text_auto as native_read_text_auto,
)


def read_text_auto(path: Path | str) -> tuple[str, str]:
    return native_read_text_auto(str(path))


def detect_encoding(data: bytes) -> str:
    return native_detect_encoding(data)
