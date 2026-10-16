"""Immutable, per-message chat material; independent of the UI and providers."""
from __future__ import annotations

from dataclasses import dataclass
from base64 import b64encode
from pathlib import Path
from uuid import uuid4

from autolingua2.services.ai_providers.chat import ChatImage


@dataclass(frozen=True, slots=True)
class ChatAttachment:
    id: str
    name: str
    origin: str
    content: str
    image: ChatImage | None = None

    def document(self) -> dict[str, str]:
        document = {"id": self.id, "name": self.name, "origin": self.origin, "content": self.content}
        if self.image is not None:
            document["mime_type"] = self.image.mime_type
        return document


def read_chat_file(path: Path) -> ChatAttachment:
    if not path.is_file():
        raise ValueError(f"ファイルを参照できません：{path}")
    image_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".gif": "image/gif"}
    mime_type = image_types.get(path.suffix.lower())
    limit = 5_000_000 if mime_type is not None else 800_000
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"参照ファイルが大きすぎます：{path.name}")
    if mime_type is not None:
        valid = (mime_type == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n")
                 or mime_type == "image/jpeg" and raw.startswith(b"\xff\xd8\xff")
                 or mime_type == "image/gif" and raw[:6] in (b"GIF87a", b"GIF89a")
                 or mime_type == "image/webp" and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
        if not valid:
            raise ValueError(f"画像の形式が不正です：{path.name}")
        return ChatAttachment(uuid4().hex, path.name, str(path.resolve()), "",
                              ChatImage(mime_type, b64encode(raw).decode("ascii")))
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
