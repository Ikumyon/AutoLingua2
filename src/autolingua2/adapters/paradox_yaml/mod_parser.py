from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from autolingua2.infrastructure.encoding import read_text_lossless

KEY_VAL_RE = re.compile(r'^\s*([a-zA-Z0-9_]+)\s*=\s*(?:"([^"]*)"|([^\s#{}]+))')

GAME_KEYWORDS: dict[str, str] = {
    "europa universalis iv": "eu4",
    "eu4": "eu4",
    "stellaris": "stellaris",
    "hearts of iron iv": "hoi4",
    "hoi4": "hoi4",
    "crusader kings iii": "ck3",
    "ck3": "ck3",
    "crusader kings ii": "ck2",
    "ck2": "ck2",
    "victoria 3": "vic3",
    "vic3": "vic3",
}


@dataclass(slots=True)
class ModInfo:
    name: str = ""
    mod_dir: Path | None = None
    picture_path: Path | None = None
    target_path: Path | None = None
    game_id: str = ""
    version: str = ""
    supported_version: str = ""


def parse_mod_file(mod_path: Path) -> ModInfo:
    """Paradox の .mod / descriptor.mod を解析し、プロジェクト情報（名前、画像、対象パス、ゲーム）を返す。"""
    resolved_mod = mod_path.resolve()
    text = read_text_lossless(resolved_mod)

    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = KEY_VAL_RE.match(line)
        if match:
            key = match.group(1).lower()
            val = match.group(2) if match.group(2) is not None else match.group(3)
            data[key] = val

    name = data.get("name", "")
    picture_name = data.get("picture", "")
    path_val = data.get("path", "")
    version = data.get("version", "")
    supported_version = data.get("supported_version", "")

    # MODフォルダの特定
    mod_dir: Path | None = None
    if resolved_mod.name.lower() == "descriptor.mod":
        mod_dir = resolved_mod.parent
    elif path_val:
        candidate = Path(path_val)
        if candidate.is_absolute() and candidate.is_dir():
            mod_dir = candidate
        else:
            # 相対パスの場合: modファイルの親、または親の親基準
            for base in (resolved_mod.parent, resolved_mod.parent.parent):
                p = (base / candidate).resolve()
                if p.is_dir():
                    mod_dir = p
                    break
                # mod/xxx の xxx だけの場合
                p_name = (base / candidate.name).resolve()
                if p_name.is_dir():
                    mod_dir = p_name
                    break

    # それでも特定できない場合、同名フォルダや同階層をチェック
    if mod_dir is None:
        sibling = resolved_mod.parent / resolved_mod.stem
        if sibling.is_dir():
            mod_dir = sibling
        elif (resolved_mod.parent / "descriptor.mod").exists():
            mod_dir = resolved_mod.parent

    # 名前が未定義ならフォルダ名またはstem
    if not name:
        if mod_dir:
            name = mod_dir.name
        else:
            name = resolved_mod.stem

    # アイコン画像の特定
    picture_path: Path | None = None
    candidates_pic: list[Path] = []
    if picture_name:
        if mod_dir:
            candidates_pic.append(mod_dir / picture_name)
        candidates_pic.append(resolved_mod.parent / picture_name)

    # 典型的な画像ファイル名もフォールバックとして検索
    if mod_dir:
        for common in ("thumbnail.png", "thumbnail.jpg", "cover.png", "cover.jpg", "icon.png"):
            candidates_pic.append(mod_dir / common)

    for p in candidates_pic:
        if p.is_file():
            picture_path = p.resolve()
            break

    # 翻訳対象パス（localisation フォルダまたは MOD フォルダ）
    target_path: Path | None = None
    if mod_dir and mod_dir.is_dir():
        for child in mod_dir.iterdir():
            if child.is_dir() and child.name.lower() in {"localisation", "localization"}:
                target_path = child.resolve()
                break
        if target_path is None:
            target_path = mod_dir
    elif resolved_mod.is_file():
        target_path = resolved_mod.parent

    # ゲームの自動推定
    search_str = f"{resolved_mod} {mod_dir or ''}".lower()
    game_id = ""
    for kw, gid in GAME_KEYWORDS.items():
        if kw in search_str:
            game_id = gid
            break

    return ModInfo(
        name=name,
        mod_dir=mod_dir,
        picture_path=picture_path,
        target_path=target_path,
        game_id=game_id,
        version=version,
        supported_version=supported_version,
    )


FILENAME_LANG_RE = re.compile(r'_l_([a-zA-Z0-9_]+)\.ya?ml$', re.IGNORECASE)
HEADER_LANG_RE = re.compile(r'^\s*(l_[a-zA-Z0-9_]+)\s*:', re.MULTILINE)


def scan_folder_languages(folder: Path) -> dict[str, list[Path]]:
    """フォルダ内の .yml ファイルを再帰検索し、言語スロット別に分類したファイルリストを返す。"""
    result: dict[str, list[Path]] = {}
    if not folder.is_dir():
        return result

    for child in folder.rglob("*"):
        if not child.is_file():
            continue
        if child.suffix.lower() not in {".yml", ".yaml"}:
            continue

        lang_slot = ""
        match = FILENAME_LANG_RE.search(child.name)
        if match:
            lang_slot = f"l_{match.group(1).lower()}"
        else:
            try:
                text = child.read_text(encoding="utf-8-sig", errors="ignore")[:300]
                hm = HEADER_LANG_RE.search(text)
                if hm:
                    lang_slot = hm.group(1).lower()
            except Exception:
                pass

        if not lang_slot:
            lang_slot = "other"

        result.setdefault(lang_slot, []).append(child.resolve())

    # 主要言語が先頭に来るようにソート
    order_priority = {"l_english": 0, "l_japanese": 1, "l_simp_chinese": 2, "l_german": 3, "l_french": 4, "l_spanish": 5, "l_russian": 6}
    sorted_keys = sorted(result.keys(), key=lambda k: (order_priority.get(k, 99), k))
    return {k: result[k] for k in sorted_keys}
