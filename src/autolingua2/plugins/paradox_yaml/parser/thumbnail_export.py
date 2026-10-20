"""Plan a Paradox descriptor's picture update without touching unrelated fields."""
from pathlib import Path
import re


def update_picture(text: str, filename: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    pattern = re.compile(r'^([ \t]*picture[ \t]*=[ \t]*)(?:"[^"\r\n]*"|[^\s#\r\n]*)([^\r\n]*)(?=\r?$)', re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda match: f'{match[1]}"{filename}"{match[2]}', text)
    return text + ("" if not text or text.endswith(("\n", "\r")) else newline) + f'picture="{filename}"{newline}'


def descriptor_path(destination: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("更新する.modファイルを指定してください。")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = destination.parent / path
    path = path.resolve()
    if path.suffix.lower() != ".mod" or not path.is_file():
        raise ValueError("更新対象の.modファイルがありません。")
    if path.parent != destination.parent.resolve():
        raise ValueError("画像は.modファイルと同じフォルダへ出力してください。")
    return path
