from __future__ import annotations

import re

from PySide6.QtCore import QLocale

DEFAULT_LANGUAGE = "ja-JP"


def normalize_language(value: str) -> str:
    cleaned = value.strip().replace("_", "-")
    match = re.fullmatch(r"([A-Za-z]{2,3})(?:-([A-Za-z]{4}))?(?:-([A-Za-z0-9]{2,3}))?", cleaned)
    if not match:
        raise ValueError("言語コードは「2〜3文字」または「2〜3文字-2〜3文字」（例: ja, en, ja-JP）で入力してください。")
    lang, script, region = match.groups()
    parts = [lang.lower()]
    if script:
        parts.append(script.title())
    if region:
        parts.append(region.upper())
    return "-".join(parts)


normalize_language_code = normalize_language


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
    try:
        tag = normalize_language(tag)
    except ValueError:
        return None
    locale = QLocale(tag)
    return None if locale.language() == QLocale.Language.C else locale


def fallback_tags(tag: str) -> tuple[str, ...]:
    try:
        tag = normalize_language(tag)
    except ValueError:
        return (tag,)
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
            try:
                candidates.append(normalize_language("-".join(parts)))
            except ValueError:
                continue
    return tuple(dict.fromkeys(candidates))


def qt_language_options() -> tuple[tuple[str, str], ...]:
    options: dict[str, str] = {}
    for locale in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript,
                                         QLocale.Country.AnyCountry):
        if locale.language() == QLocale.Language.C:
            continue
        try:
            code = qt_language_code(locale)
        except ValueError:
            continue
        name = "English" if code == "en" else locale.nativeLanguageName()
        if not name:
            continue
        if code != "zh":
            options.setdefault(code, name)
        territory = QLocale.territoryToCode(locale.territory())
        if territory:
            tag = f"{code}-{territory}"
            try:
                norm_tag = normalize_language(tag)
                t_name = locale.nativeTerritoryName()
                if code == "zh" and territory in ("CN", "TW", "HK"):
                    options.setdefault(norm_tag, f"{name}（{t_name}）")
                elif code == "pt" and territory == "BR":
                    options.setdefault(norm_tag, f"{name}（{t_name}）")
            except ValueError:
                pass
    return tuple(sorted(options.items(), key=lambda item: (item[1].casefold(), item[0])))
