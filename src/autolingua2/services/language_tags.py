from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import re

from PySide6.QtCore import QLocale

from autolingua2.infrastructure.filesystem import ASSETS_DIR
from autolingua2.ir.validation import array, record, required, text

DEFAULT_LANGUAGE = "ja-JP"


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    preferred: str
    prefixes: tuple[str, ...]
    suppress: str


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict[str, RegistryEntry]]:
    data = record(json.loads((ASSETS_DIR / "i18n/language-subtag-registry.json").read_text(encoding="utf-8")))
    entries: dict[str, dict[str, RegistryEntry]] = {}
    for value in array(required(data, "records")):
        item = record(value)
        kind = text(required(item, "Type"))
        identifier = text(item.get("Subtag", item.get("Tag", ""))).lower()
        entries.setdefault(kind, {})[identifier] = RegistryEntry(
            text(item.get("Preferred-Value", "")),
            tuple(text(prefix).lower() for prefix in array(item.get("Prefix", []))),
            text(item.get("Suppress-Script", "")),
        )
    return entries


def _entry(kind: str, value: str) -> RegistryEntry:
    entries = _registry().get(kind, {})
    found = entries.get(value.lower())
    if found is not None:
        return found
    for key, entry in entries.items():
        if ".." in key:
            first, last = key.split("..")
            if len(value) == len(first) and first <= value.lower() <= last:
                return entry
    raise ValueError(f"IANAに登録されていない{kind}コードです: {value}")


def normalize_language(value: str) -> str:
    """Validate BCP 47 without asking QLocale to approximate an unknown language."""
    raw = value.strip().replace("_", "-")
    if not raw or not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", raw):
        raise ValueError("有効なBCP 47言語タグを入力してください。")
    for kind in ("grandfathered", "redundant"):
        registered = _registry().get(kind, {}).get(raw.lower())
        if registered is not None:
            return normalize_language(registered.preferred) if registered.preferred else raw.lower()
    parts = raw.split("-")
    language = parts.pop(0).lower()
    entry = _entry("language", language)
    if entry.preferred:
        language = entry.preferred.lower()
        entry = _entry("language", language)
    output = [language]
    # Extlangs carry a registered prefix; their Preferred-Value is the primary tag.
    count = 0
    while parts and len(parts[0]) == 3 and parts[0].isalpha() and parts[0].lower() in _registry().get("extlang", {}):
        extlang = parts.pop(0).lower()
        ext = _entry("extlang", extlang)
        if count >= 3 or (ext.prefixes and "-".join(output).lower() not in ext.prefixes):
            raise ValueError("拡張言語コードの組み合わせが不正です。")
        output = [ext.preferred.lower()] if ext.preferred else [*output, extlang]
        entry = _entry("language", output[0])
        count += 1
    if parts and len(parts[0]) == 4 and parts[0].isalpha():
        script = parts.pop(0).title()
        registered = _entry("script", script)
        script = registered.preferred or script
        if script.lower() != entry.suppress.lower():
            output.append(script)
    if parts and (len(parts[0]) == 2 and parts[0].isalpha() or len(parts[0]) == 3 and parts[0].isdigit()):
        region = parts.pop(0).upper()
        registered = _entry("region", region)
        output.append(registered.preferred or region)
    variants: set[str] = set()
    while parts and (5 <= len(parts[0]) <= 8 or len(parts[0]) == 4 and parts[0][0].isdigit()):
        variant = parts.pop(0).lower()
        registered = _entry("variant", variant)
        if variant in variants:
            raise ValueError("言語タグの変種が重複しています。")
        variants.add(variant)
        output.append(registered.preferred.lower() or variant)
    extensions: dict[str, list[str]] = {}
    private: list[str] = []
    while parts:
        singleton = parts.pop(0).lower()
        if len(singleton) != 1 or singleton in extensions:
            raise ValueError("言語タグの拡張形式が不正です。")
        if singleton == "x":
            if not parts or any(not 1 <= len(part) <= 8 for part in parts):
                raise ValueError("私用タグの形式が不正です。")
            private = ["x", *(part.lower() for part in parts)]
            parts.clear()
            break
        values: list[str] = []
        while parts and 2 <= len(parts[0]) <= 8:
            values.append(parts.pop(0).lower())
        if not values:
            raise ValueError("拡張タグの値がありません。")
        extensions[singleton] = values
    for singleton in sorted(extensions):
        output.extend([singleton, *extensions[singleton]])
    return "-".join([*output, *private])


def is_default_language(language: str | None) -> bool:
    return language is None or normalize_language(language) in ("ja", "ja-JP")


def system_language() -> str:
    locale = QLocale.system()
    return DEFAULT_LANGUAGE if locale.language() == QLocale.Language.C else normalize_language(locale.bcp47Name())


def qt_language_code(locale: QLocale) -> str:
    for kind in (QLocale.LanguageCodeType.ISO639Part1, QLocale.LanguageCodeType.ISO639Part2T,
                 QLocale.LanguageCodeType.ISO639Part3):
        code = QLocale.languageToCode(locale.language(), kind)
        if code:
            return normalize_language(code)
    raise ValueError("Qtロケールに有効な言語コードがありません。")


def qt_locale(tag: str) -> QLocale | None:
    tag = normalize_language(tag)
    locale = QLocale(tag)
    if locale.language() == QLocale.Language.C:
        return None
    if qt_language_code(locale) != tag.split("-")[0]:
        return None
    return locale


def _script(tag: str) -> str:
    parts = tag.split("-")
    if len(parts) > 1 and len(parts[1]) == 4 and parts[1].isalpha():
        return parts[1].title()
    locale = qt_locale(tag)
    return QLocale.scriptToCode(locale.script()) if locale is not None else ""


def fallback_tags(tag: str) -> tuple[str, ...]:
    tag = normalize_language(tag)
    candidates = [tag]
    locale = qt_locale(tag)
    if locale is not None:
        for candidate in locale.uiLanguages():
            try:
                candidates.append(normalize_language(candidate))
            except ValueError:
                continue
    else:
        parts = tag.split("-")
        while len(parts) > 1:
            parts.pop()
            if len(parts[-1]) == 1:
                parts.pop()
            try:
                candidates.append(normalize_language("-".join(parts)))
            except ValueError:
                continue
    script = _script(tag)
    return tuple(dict.fromkeys(candidate for candidate in candidates
                              if not script or not _script(candidate) or _script(candidate) == script))


def qt_language_options() -> tuple[tuple[str, str], ...]:
    options: dict[str, str] = {}
    for locale in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript,
                                         QLocale.Country.AnyCountry):
        if locale.language() == QLocale.Language.C:
            continue
        language = qt_language_code(locale)
        name = locale.nativeLanguageName()
        if not name:
            continue
        if language != "zh":
            options.setdefault(language, name)
        region = QLocale.territoryToCode(locale.territory())
        if not region:
            continue
        tag = normalize_language(f"{language}-{region}")
        standard = QLocale(tag)
        if standard.script() != locale.script():
            tag = normalize_language(f"{language}-{QLocale.scriptToCode(locale.script())}-{region}")
        options.setdefault(tag, f"{name}（{locale.nativeTerritoryName()}）")
    return tuple(sorted(options.items(), key=lambda item: (item[1].casefold(), item[0])))
