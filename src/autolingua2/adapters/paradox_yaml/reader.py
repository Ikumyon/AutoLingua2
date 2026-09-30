from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from autolingua2.infrastructure.encoding import read_text_lossless
from autolingua2.ir import Issue, TranslationProject, TranslationSource, TranslationUnit
from autolingua2.adapters.base import CreationContext, GameProfile, ImportedTranslation, SourceRef



LANGUAGE_HEADER_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*:\s*(?:#.*)?$")
ENTRY_RE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.-]+)\s*:(?P<version>\d+)?\s*(?P<value>.*)$"
)


from autolingua2.services.filter_rules import FilterRule


PARADOX_YAML_LANGUAGES: list[tuple[str, str]] = [
    ("l_english", "l_english (English)"),
    ("l_japanese", "l_japanese (Japanese)"),
    ("l_simp_chinese", "l_simp_chinese (Simplified Chinese)"),
    ("l_german", "l_german (German)"),
    ("l_french", "l_french (French)"),
    ("l_spanish", "l_spanish (Spanish)"),
    ("l_russian", "l_russian (Russian)"),
    ("l_polish", "l_polish (Polish)"),
    ("l_korean", "l_korean (Korean)"),
    ("l_braz_por", "l_braz_por (Portuguese)"),
]

SLOT_LANGUAGE = dict(zip((slot for slot, _ in PARADOX_YAML_LANGUAGES),
                         ("en", "ja", "zh-Hans", "de", "fr", "es", "ru", "pl", "ko", "pt-BR")))

EU4_CK2_LANGUAGES: list[tuple[str, str]] = [
    ("l_english", "l_english (English)"),
    ("l_french", "l_french (French)"),
    ("l_german", "l_german (German)"),
    ("l_spanish", "l_spanish (Spanish)"),
]

PARADOX_GAMES: list[GameProfile] = [
    GameProfile(id="eu4", name="Europa Universalis IV", available_slots=EU4_CK2_LANGUAGES, default_slot="l_english"),
    GameProfile(id="ck2", name="Crusader Kings II", available_slots=EU4_CK2_LANGUAGES, default_slot="l_english"),
    GameProfile(id="stellaris", name="Stellaris", available_slots=PARADOX_YAML_LANGUAGES, default_slot="l_japanese"),
    GameProfile(id="hoi4", name="Hearts of Iron IV", available_slots=PARADOX_YAML_LANGUAGES, default_slot="l_japanese"),
    GameProfile(id="ck3", name="Crusader Kings III", available_slots=PARADOX_YAML_LANGUAGES, default_slot="l_japanese"),
    GameProfile(id="vic3", name="Victoria 3", available_slots=PARADOX_YAML_LANGUAGES, default_slot="l_japanese"),
    GameProfile(id="generic", name="その他のゲーム / 汎用", available_slots=PARADOX_YAML_LANGUAGES, default_slot="l_english"),
]

PARADOX_YAML_BUILTIN_RULES: list[FilterRule] = [
    FilterRule(id="paradox_1", enabled=True, rule_type="デフォルト", pattern=r"@\w+\s?", example="", is_builtin=True),
    FilterRule(id="paradox_2", enabled=True, rule_type="デフォルト", pattern=r"@?\[[\^\[\]]+\]", example="", is_builtin=True),
    FilterRule(id="paradox_3", enabled=True, rule_type="デフォルト", pattern=r"£[\w\|]+?[£\s]", example="", is_builtin=True),
    FilterRule(id="paradox_4", enabled=True, rule_type="デフォルト", pattern=r"[@£]\$.+?\$", example="", is_builtin=True),
    FilterRule(id="paradox_5", enabled=True, rule_type="デフォルト", pattern=r"\$[\w.@-]+\$|*[^$]*\$", example="", is_builtin=True),
    FilterRule(id="paradox_6", enabled=True, rule_type="開始", pattern=r"§\w", example="", is_builtin=True),
    FilterRule(id="paradox_7", enabled=True, rule_type="終了", pattern=r"§!", example="", is_builtin=True),
    FilterRule(id="paradox_8", enabled=True, rule_type="デフォルト", pattern=r"¤", example="", is_builtin=True),
    FilterRule(id="paradox_9", enabled=True, rule_type="デフォルト", pattern=r"@[A-Z]+(\s|$)", example="", is_builtin=True),
]


class ParadoxYamlAdapter:
    id = "paradox_yaml"
    name = "Paradox YAML"
    suffixes = {".yml", ".yaml"}
    supported_languages = [(SLOT_LANGUAGE[slot], label.split("(", 1)[1].rstrip(")"))
                           for slot, label in PARADOX_YAML_LANGUAGES]
    supported_games = PARADOX_GAMES
    default_filter_rules = PARADOX_YAML_BUILTIN_RULES

    def can_load(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in self.suffixes

    def create_creation_panel(self, context: CreationContext) -> Any:
        from autolingua2.adapters.paradox_yaml.panel import ParadoxCreationPanel
        return ParadoxCreationPanel(context)

    def on_paths_dropped(self, paths: list[Path], context: CreationContext) -> list[Path]:
        from autolingua2.adapters.paradox_yaml.panel import handle_paths_dropped
        return handle_paths_dropped(paths, context)

    def on_game_selected(self, game_id: str, context: CreationContext) -> None:
        for game in self.supported_games:
            if game.id == game_id and game.default_slot:
                context.set_target_slot(game.default_slot)
                break

    def format_target_path_label(self, path: Path, current_source_lang: str) -> tuple[str, str, str]:
        from autolingua2.adapters.paradox_yaml.panel import format_target_label
        return format_target_label(path, current_source_lang)

    def filter_source_files(self, paths: list[Path], current_source_lang: str) -> list[Path]:
        files: dict[Path, None] = {}
        for path in paths:
            if not path.exists():
                raise ValueError(f"対象が見つかりません: {path}")
            if path.is_file() and not self.can_load(path):
                raise ValueError(f"YAMLファイルではありません: {path}")
            for child in sorted(path.rglob("*")) if path.is_dir() else [path]:
                if self.can_load(child):
                    files[child.resolve()] = None
        languages = {path: self.detect_source_language(path) for path in files}
        selected = current_source_lang
        if selected == "auto":
            detected = {language for language in languages.values() if language}
            if len(detected) != 1 or any(language is None for language in languages.values()):
                raise ValueError("翻訳元言語を一意に検出できません。言語を選択してください。")
            selected = detected.pop()
        return [path for path, language in languages.items() if language == selected]

    def dispose_creation_panel(self, panel: Any) -> None:
        pass

    def on_ui_language_changed(self, language_code: str, context: CreationContext) -> None:
        pass

    def qt_translation_files(self, language_code: str) -> list[Path]:
        folder = Path(__file__).parent / "translations"
        for code in dict.fromkeys((language_code, language_code.split("_")[0])):
            path = folder / f"{code}.qm"
            if path.is_file():
                return [path]
        return []



    def detect_source_language(self, path: Path) -> str | None:
        if path.is_dir():
            languages = {self.detect_source_language(f) for f in path.rglob("*") if self.can_load(f)}
            return next(iter(languages)) if len(languages) == 1 else None
        return SLOT_LANGUAGE.get(self._detect_file_language(path) or "")

    def _detect_file_language(self, path: Path) -> str | None:
        try:
            text = read_text_lossless(path)
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
        text = read_text_lossless(path)
        source_id = str(path.resolve())
        source = TranslationSource(id=source_id, name=path.name)
        project = TranslationProject(sources=[source])
        source_refs: dict[str, SourceRef] = {}
        language_header = ""
        pending_comment_lines: list[str] = []

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped:
                pending_comment_lines.clear()
                continue
            if stripped.startswith("#"):
                pending_comment_lines.append(raw_line)
                continue

            if not language_header:
                header = LANGUAGE_HEADER_RE.match(raw_line)
                if header:
                    language_header = header.group(1)
                    pending_comment_lines.clear()
                    continue

            match = ENTRY_RE.match(raw_line)
            if not match:
                source.issues.append(Issue(message=f"{line_number}: 読み取れない行です"))
                continue

            key = match.group("key")
            raw_value, inline_comment = split_inline_comment(match.group("value").strip())
            value = parse_quoted_value(raw_value)
            unit_id = f"{source_id}#{line_number}:{key}"
            leading_comment_lines = pending_comment_lines.copy()
            pending_comment_lines.clear()

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
                data={
                    "language_header": language_header,
                    "line_number": str(line_number),
                    "raw_line": raw_line,
                    "raw_value": raw_value,
                    "version": match.group("version") or "",
                    "leading_comments": "\n".join(leading_comment_lines),
                    "inline_comment": inline_comment,
                },
            )

        if not language_header:
            source.issues.append(Issue(message="言語ヘッダが見つかりません"))

        return ImportedTranslation(project=project, source_refs=source_refs)

    def output_name(self, path: Path, project: TranslationProject) -> str:
        slot = project.target_file_language
        if slot not in SLOT_LANGUAGE:
            raise ValueError("出力言語スロットを選択してください。")
        stem = re.sub(r"l_[A-Za-z_]+$", slot, path.stem)
        if stem == path.stem and not stem.endswith(slot):
            stem = f"{stem}_{slot}"
        return f"{stem}{path.suffix}"

    def save(self, path: Path, imported: ImportedTranslation, project: TranslationProject,
             existing: ImportedTranslation | None = None) -> None:
        from .writer import render_translation_file, save_translation_file
        if project.target_file_language not in SLOT_LANGUAGE:
            raise ValueError("出力言語スロットを選択してください。")
        save_translation_file(path, render_translation_file(imported, project, existing))


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
