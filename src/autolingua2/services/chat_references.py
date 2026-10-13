"""Immutable, per-message chat material; independent of the UI and providers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ChatAttachment:
    id: str
    name: str
    origin: str
    content: str

    def document(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "origin": self.origin, "content": self.content}


def read_chat_file(path: Path) -> ChatAttachment:
    if not path.is_file():
        raise ValueError(f"ファイルを参照できません：{path}")
    # The conversation already has a 200,000-character ceiling. Do not read
    # unbounded data, or silently truncate a document that cannot be sent.
    with path.open("rb") as stream:
        raw = stream.read(800_001)
    if len(raw) > 800_000:
        raise ValueError(f"参照ファイルが大きすぎます：{path.name}")
    encoding = "utf-8-sig"
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding = "utf-32"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    try:
        content = raw.decode(encoding)
    except UnicodeError as exc:
        raise ValueError(f"文字コードを読み取れません：{path.name}（UTF-8またはBOM付きUnicodeが必要です）") from exc
    if any(ord(character) < 32 and character not in "\t\r\n\f" for character in content):
        raise ValueError(f"テキストファイルではありません：{path.name}")
    if len(content) > 200_000:
        raise ValueError(f"参照ファイルが大きすぎます：{path.name}")
    return ChatAttachment(uuid4().hex, path.name, str(path.resolve()), content)
