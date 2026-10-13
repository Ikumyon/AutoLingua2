from __future__ import annotations

from pathlib import Path
import json
import re
from collections.abc import Callable

from autolingua2.plugins.contracts import (
    Issue, TranslationProject, TranslationSource, TranslationUnit,
    GameProfile, GameSlot, ImportedTranslation, SourceRef, FilterRule, TagKind,
    KeyEntry, KeyFile, TranslationTextRules,
)



LANGUAGE_HEADER_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*:\s*(?:#.*)?$")
ENTRY_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.-]+)\s*:(?P<version>\d+)?\s*(?P<value>.*)$"
)




EU4_SLOTS: list[GameSlot] = [
    GameSlot("l_english", "English", "en-US"),
    GameSlot("l_french", "French", "fr-FR"),
    GameSlot("l_german", "German", "de-DE"),
    GameSlot("l_spanish", "Spanish", "es-ES"),
]

PARADOX_STANDARD_SLOTS: list[GameSlot] = [
    GameSlot("l_english", "English", "en-US"),
    GameSlot("l_japanese", "Japanese", "ja-JP"),
    GameSlot("l_simp_chinese", "Simplified Chinese", "zh-CN"),
    GameSlot("l_german", "German", "de-DE"),
    GameSlot("l_french", "French", "fr-FR"),
    GameSlot("l_spanish", "Spanish", "es-ES"),
    GameSlot("l_russian", "Russian", "ru-RU"),
    GameSlot("l_polish", "Polish", "pl-PL"),
    GameSlot("l_korean", "Korean", "ko-KR"),
    GameSlot("l_braz_por", "Portuguese", "pt-BR"),
]

SLOT_LANGUAGE: dict[str, str] = {slot.slot_id: slot.language_code for slot in PARADOX_STANDARD_SLOTS}


def detect_file_slot_from_name(path: Path) -> str | None:
    if path.suffix.lower() == ".json":
        path = path.with_suffix("")
    stem = path.stem.lower()
    for slot in SLOT_LANGUAGE:
        if stem.endswith(f"_{slot}") or stem == slot:
            return slot
    return None


def detect_file_language_from_name(path: Path) -> str | None:
    slot = detect_file_slot_from_name(path)
    return SLOT_LANGUAGE.get(slot) if slot else None

PARADOX_GAMES: list[GameProfile] = [
    GameProfile(id="eu4", name="Europa Universalis IV", slots=EU4_SLOTS, default_slot_id="l_english"),
    GameProfile(id="ck2", name="Crusader Kings II", slots=EU4_SLOTS, default_slot_id="l_english"),
    GameProfile(id="stellaris", name="Stellaris", slots=PARADOX_STANDARD_SLOTS, default_slot_id="l_japanese"),
    GameProfile(id="hoi4", name="Hearts of Iron IV", slots=PARADOX_STANDARD_SLOTS, default_slot_id="l_japanese"),
    GameProfile(id="ck3", name="Crusader Kings III", slots=PARADOX_STANDARD_SLOTS, default_slot_id="l_japanese"),
    GameProfile(id="vic3", name="Victoria 3", slots=PARADOX_STANDARD_SLOTS, default_slot_id="l_japanese"),
    GameProfile(id="generic", name="その他のゲーム / 汎用", slots=PARADOX_STANDARD_SLOTS, default_slot_id="l_english"),
]

PARADOX_YAML_DEFAULT_RULES: list[FilterRule] = [
    FilterRule("paradox_color", TagKind.DISPLAY_CONTROL, pattern=r"§[^\r\n]", example="§Y / §!"),
    FilterRule("paradox_newline", TagKind.DISPLAY_CONTROL, pattern=r"\\n", example=r"\n"),
    FilterRule("paradox_scope", TagKind.DISPLAY_CONTENT,
               pattern=r"@?\[[^\[\]\r\n]+\]", example="[Root.GetName]"),
    FilterRule("paradox_reference", TagKind.DISPLAY_CONTENT,
               pattern=r"[@£]?\$[^$\r\n]+\$", example="$NAME$ / @$ICON$"),
    FilterRule("paradox_icon", TagKind.DISPLAY_CONTROL,
               pattern=r"£[^£\r\n]*£|¤", example="£gold£ / ¤"),
    FilterRule("paradox_at_icon", TagKind.DISPLAY_CONTENT,
               pattern=r"@[\w]+!", example="@gold!"),
    FilterRule("paradox_variable", TagKind.DISPLAY_CONTENT,
               pattern=r"(?<!\w)@\w+", example="@variable"),
]


def is_paratranz_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(data, list) and all(isinstance(entry, dict)
        and {"key", "original", "translation"} <= entry.keys() for entry in data)


class ParadoxYamlAdapter:
    id = "paradox_yaml"
    name = "Paradox YAML"
    suffixes = {".yml", ".yaml", ".json"}
    supported_games = PARADOX_GAMES
    supported_languages: list[tuple[str, str]] = list(dict.fromkeys(
        (slot.language_code, slot.name) for slot in PARADOX_STANDARD_SLOTS
    ))
    default_filter_rules = PARADOX_YAML_DEFAULT_RULES
    translation_text_rules = TranslationTextRules(sentence_exceptions=(r"\b(?:Mr|Mrs|Dr|St|e\.g|i\.e)\.",))

    def __init__(self, read_text: Callable[[Path], str], detect_encoding: Callable[[bytes], str]) -> None:
        self._read_text = read_text
        self._detect_encoding = detect_encoding

    def can_load(self, path: Path) -> bool:
        if not path.is_file() or path.suffix.lower() not in self.suffixes:
            return False
        if path.suffix.lower() != ".json":
            return True
        return is_paratranz_json(path)

    def contains_translations(self, path: Path) -> bool:
        if path.is_dir():
            return any(self.contains_translations(child) for child in path.rglob("*.json"))
        return path.suffix.lower() == ".json" and self.can_load(path)

    def filter_source_files(self, paths: list[Path], source_slot: str) -> list[Path]:
        files: dict[Path, None] = {}
        for path in paths:
            if not path.exists():
                raise ValueError(f"対象が見つかりません: {path}")
            if path.is_file() and not self.can_load(path):
                raise ValueError(f"YAMLまたはParaTranz JSONファイルではありません: {path}")
            for child in sorted(path.rglob("*")) if path.is_dir() else [path]:
                if self.can_load(child):
                    files[child.resolve()] = None
        if not source_slot:
            return list(files)
        return [path for path in files if self.detect_source_slot(path) == source_slot]

    def detect_source_slot(self, path: Path) -> str | None:
        if path.is_dir():
            slots = {self.detect_source_slot(child) for child in path.rglob("*") if self.can_load(child)}
            return next(iter(slots)) if len(slots) == 1 else None
        if path.suffix.lower() == ".json":
            return detect_file_slot_from_name(path)
        return self._detect_file_language(path) or detect_file_slot_from_name(path)

    def detect_source_language(self, path: Path) -> str | None:
        if path.is_dir():
            languages = {self.detect_source_language(f) for f in path.rglob("*") if self.can_load(f)}
            return next(iter(languages)) if len(languages) == 1 else None
        # 高速化: ファイル名から言語を即座に判定（ディスク読み込み回避）
        from_name = detect_file_language_from_name(path)
        if from_name:
            return from_name
        if path.suffix.lower() == ".json":
            return None
        return SLOT_LANGUAGE.get(self._detect_file_language(path) or "")

    def _detect_file_language(self, path: Path) -> str | None:
        try:
            text = self._read_text(path)
            for line in text.splitlines()[:50]:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = LANGUAGE_HEADER_RE.match(line)
                if match:
                    return match.group(1)
        except Exception:
            return None
        return None

    def load(self, path: Path) -> ImportedTranslation:
        if path.suffix.lower() == ".json":
            return self._load_paratranz(path, path.read_text(encoding="utf-8-sig"))
        text = self._read_text(path)
        return self._load_text(path, text)

    def _load_paratranz(self, path: Path, text: str) -> ImportedTranslation:
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("ParaTranz JSONは配列で指定してください。")
        source_id = str(path)
        slot = detect_file_slot_from_name(path) or ""
        project = TranslationProject(sources=[TranslationSource(source_id, path.name)],
                                     source_language=SLOT_LANGUAGE.get(slot, ""), source_slot=slot)
        imported = ImportedTranslation(project)
        for index, entry in enumerate(data, 1):
            if not isinstance(entry, dict) or any(not isinstance(entry.get(field), str)
                                                 for field in ("key", "original", "translation")):
                raise ValueError(f"ParaTranz JSONの{index}件目: key・original・translationは文字列が必要です。")
            key = entry["key"].strip()
            match = re.fullmatch(r"([A-Za-z0-9_.-]+):\d+", key)
            key = match.group(1) if match else key
            if not key:
                raise ValueError(f"ParaTranz JSONの{index}件目: keyが空です。")
            unit_id = f"{source_id}#{index}:{key}"
            project.units.append(TranslationUnit(unit_id, key, entry["original"], context=path.name,
                                                issues=validate_value(entry["original"])))
            imported.source_refs[unit_id] = SourceRef(source_id, key, str(index),
                {"paratranz_entry": json.dumps(entry, ensure_ascii=False)})
            imported.embedded_translations[unit_id] = entry["translation"]
        return imported

    def inspect_key_file(self, path: Path) -> KeyFile:
        content = path.read_bytes()
        if path.suffix.lower() == ".json":
            imported = self._load_paratranz(path, content.decode("utf-8-sig"))
            entries = tuple(KeyEntry(unit.label, imported.project.source_language, unit.source_text,
                                     int(imported.source_refs[unit.id].location))
                            for unit in imported.project.units)
            return KeyFile(path.resolve(), content, "utf-8", b"\xef\xbb\xbf" if content.startswith(b"\xef\xbb\xbf")
                           else b"", entries)
        encoding = self._detect_encoding(content)
        bom = next((mark for mark in (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
                    if content.startswith(mark)), b"")
        text = content[len(bom):].decode(encoding)
        if bom + text.encode(encoding) != content:
            raise ValueError(f"文字コードを保持して修正できません: {path}")
        imported = self._load_text(path, text)
        language = imported.project.source_language
        if not language:
            raise ValueError(f"言語を検出できません: {path}")
        entries = tuple(KeyEntry(unit.label, language, unit.source_text,
                                 int(imported.source_refs[unit.id].location))
                        for unit in imported.project.units)
        return KeyFile(path.resolve(), content, encoding, bom, entries)

    def remove_key_lines(self, snapshot: KeyFile, lines: set[int]) -> bytes:
        if not lines <= {entry.line_number for entry in snapshot.entries}:
            raise ValueError("削除するキー行が見つかりません。")
        text = snapshot.content[len(snapshot.bom):].decode(snapshot.encoding)
        if snapshot.path.suffix.lower() == ".json":
            data = json.loads(text)
            remaining_entries = [entry for index, entry in enumerate(data, 1) if index not in lines]
            return snapshot.bom + (json.dumps(remaining_entries, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        remaining = "".join(line for number, line in enumerate(text.splitlines(keepends=True), 1)
                            if number not in lines)
        return snapshot.bom + remaining.encode(snapshot.encoding)

    def _load_text(self, path: Path, text: str) -> ImportedTranslation:
        source_id = str(path.resolve())
        source = TranslationSource(id=source_id, name=path.name)
        project = TranslationProject(sources=[source])
        source_refs: dict[str, SourceRef] = {}
        language_header = ""

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue

            if not language_header:
                header = LANGUAGE_HEADER_RE.match(raw_line)
                if header:
                    language_header = header.group(1)
                    continue

            match = ENTRY_RE.match(raw_line)
            if not match:
                source.issues.append(Issue(message=f"{line_number}: 読み取れない行です"))
                continue

            key = match.group("key")
            raw_value, _ = split_inline_comment(match.group("value").strip())
            value = parse_quoted_value(raw_value)
            unit_id = f"{source_id}#{line_number}:{key}"

            project.units.append(
                TranslationUnit(
                    id=unit_id,
                    label=key,
                    source_text=value,
                    context=path.name,
                    issues=validate_value(value),
                )
            )
            source_refs[unit_id] = SourceRef(
                source_id=source_id,
                external_id=key,
                location=str(line_number),
            )

        if not language_header:
            source.issues.append(Issue(message="言語ヘッダが見つかりません"))
        project.source_slot = language_header
        project.source_language = SLOT_LANGUAGE.get(language_header) or detect_file_language_from_name(path) or ""

        return ImportedTranslation(project=project, source_refs=source_refs)

def parse_quoted_value(raw_value: str) -> str:
    if len(raw_value) >= 2 and raw_value[0] == '"' and raw_value[-1] == '"':
        return _unescape_quoted_value(raw_value[1:-1])
    return raw_value


def split_inline_comment(value: str) -> tuple[str, str]:
    in_quote = False
    escaped = False

    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if char == "#" and not in_quote and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip(), value[index + 1 :].strip()

    return value, ""


def _unescape_quoted_value(value: str) -> str:
    result: list[str] = []
    escaped = False

    for char in value:
        if escaped:
            if char == "n":
                result.append("\\n")
            elif char in {'"', "\\"}:
                result.append(char)
            else:
                result.append("\\" + char)
            escaped = False
            continue

        if char == "\\":
            escaped = True
        else:
            result.append(char)

    if escaped:
        result.append("\\")

    return "".join(result)


def validate_value(value: str) -> list[Issue]:
    issues: list[Issue] = []
    if value.count('"') % 2:
        issues.append(Issue(message="引用符の数が不一致です"))
    if value.count("§!") > value.count("§"):
        issues.append(Issue(message="色コードが不自然です"))
    return issues
