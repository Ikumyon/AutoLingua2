from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator, QObject, Signal

from autolingua2.infrastructure.filesystem import PROJECT_ROOT


TRANSLATIONS_DIR = PROJECT_ROOT / "translations"
DEFAULT_LANGUAGE = "ja_JP"

_current_language = DEFAULT_LANGUAGE


class LanguageEvents(QObject):
    changed = Signal(str)


_events: LanguageEvents | None = None


def language_events() -> LanguageEvents:
    global _events
    if _events is None:
        _events = LanguageEvents(QCoreApplication.instance())
    return _events


def current_ui_language() -> str:
    return _current_language


@dataclass(slots=True)
class LanguageInfo:
    code: str
    name: str
    flag_path: Path | None = None
    qm_paths: list[Path] = field(default_factory=list)


def tr(context: str, text: str) -> str:
    return QCoreApplication.translate(context, text)


def normalize_language(language: str | None) -> str:
    if not language:
        return DEFAULT_LANGUAGE
    lang = language.strip().replace("-", "_")
    parts = lang.split("_")
    if len(parts) == 1:
        part0 = parts[0].lower()
        if part0 == "ja":
            return "ja_JP"
        if part0 == "en":
            return "en_US"
        return part0
    return f"{parts[0].lower()}_{parts[1].upper()}"


def system_language() -> str:
    return normalize_language(QLocale.system().name())


def get_available_languages() -> dict[str, LanguageInfo]:
    """translations/ 内で metadata.json を持つ言語フォルダのみを読み込んで返す。"""
    languages: dict[str, LanguageInfo] = {}

    if not TRANSLATIONS_DIR.exists():
        return languages

    for lang_dir in sorted(TRANSLATIONS_DIR.iterdir()):
        if not lang_dir.is_dir():
            continue

        meta_file = lang_dir / "metadata.json"
        if not meta_file.is_file():
            continue

        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if not isinstance(meta, dict):
                continue
        except Exception:
            continue

        code_raw = meta.get("code")
        name_raw = meta.get("name")
        if not code_raw or not name_raw:
            continue

        code = normalize_language(str(code_raw))
        name = str(name_raw)

        # 国旗画像は metadata.json に "flag" が指定されている場合のみ
        flag_path: Path | None = None
        flag_file = meta.get("flag")
        if flag_file and isinstance(flag_file, str):
            custom_path = lang_dir / flag_file
            if custom_path.is_file():
                flag_path = custom_path

        qm_paths = sorted(lang_dir.glob("*.qm"))

        languages[code] = LanguageInfo(
            code=code,
            name=name,
            flag_path=flag_path,
            qm_paths=qm_paths,
        )

    return languages


def resolve_ui_language(configured_language: str | None = None) -> str:
    """設定値から実際に適用する言語コードを解決する。
    
    'system' の場合はOSの言語を検出し、対応パッケージがあればそれを採用。
    未対応の場合は日本語(ja_JP)にフォールバックする。
    """
    if not configured_language or configured_language.lower() == "system":
        sys_code = system_language()
        available = get_available_languages()
        if sys_code in available:
            return sys_code
        sys_prefix = sys_code.split("_")[0]
        for code in available:
            if code.split("_")[0] == sys_prefix:
                return code
        return DEFAULT_LANGUAGE

    return normalize_language(configured_language)


_installed_translators: list[QTranslator] = []


def install_ui_translator(app: QCoreApplication, language: str) -> None:
    global _current_language

    for trans in _installed_translators:
        app.removeTranslator(trans)
        trans.deleteLater()
    _installed_translators.clear()

    code = resolve_ui_language(language)
    _current_language = code

    # Only explicitly opted-in, successfully registered plugins provide Qt dictionaries.
    from autolingua2.adapters.registry import get_all_adapters
    for adapter in get_all_adapters():
        provider = getattr(adapter, "qt_translation_files", None)
        if provider is None:
            continue
        try:
            for candidate in dict.fromkeys(provider(code)):
                translator = QTranslator(app)
                if translator.load(str(candidate)):
                    app.installTranslator(translator)
                    _installed_translators.append(translator)
                else:
                    translator.deleteLater()
                    logging.getLogger(__name__).warning("Cannot load translation: %s", candidate)
        except Exception:
            logging.getLogger(__name__).exception("Translation provider failed: %s", adapter.id)
    # Qt searches in reverse installation order: host strings retain priority.
    available = get_available_languages()
    lang_info = available.get(code)
    if lang_info:
        for qm in lang_info.qm_paths:
            translator = QTranslator(app)
            if translator.load(str(qm)):
                app.installTranslator(translator)
                _installed_translators.append(translator)
            else:
                translator.deleteLater()
    language_events().changed.emit(code)
