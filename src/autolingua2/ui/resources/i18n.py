from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator, QObject, Signal

from collections.abc import Mapping
from types import MappingProxyType

from autolingua2.ir.validation import record, required, text
from autolingua2.ir.localization import LanguageInfo
from autolingua2.services.settings.language_tags import DEFAULT_LANGUAGE, fallback_tags, normalize_language, qt_locale, system_language


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


def tr(context: str, text: str) -> str:
    return QCoreApplication.translate(context, text)


def translation_source(_context: str, text: str) -> str:
    """Typed lupdate marker for labels translated later (Qt's NOOP returns object)."""
    return text


class LocalizationManager:
    """Owns application and Qt dictionaries; plugin dictionaries remain independent."""

    def __init__(self) -> None:
        self._languages: dict[str, LanguageInfo] = {}
        self._installed: list[QTranslator] = []
        self._app: QCoreApplication | None = None

    def _register(self, path: Path) -> None:
        meta = record(json.loads((path / "metadata.json").read_text(encoding="utf-8")))
        code = normalize_language(text(required(meta, "code"), nonempty=True))
        name = text(required(meta, "name"), nonempty=True)
        existing = self._languages.get(code)
        if existing is not None and existing.folder != path.resolve():
            raise ValueError(f"Duplicate UI language: {code}")
        flag = text(meta.get("flag", ""))
        flag_path = path / flag if flag else None
        if flag_path is not None and not flag_path.is_file():
            flag_path = None
        qm_paths = tuple(sorted(path.glob("*.qm"), key=lambda item: (item.name == "personal.qm", item.name)))
        self._languages[code] = LanguageInfo(code, name, path.resolve(), flag_path, qm_paths)

    @property
    def available_languages(self) -> Mapping[str, LanguageInfo]:
        return MappingProxyType(self._languages)

    def _unregister(self, folder: Path) -> None:
        for tag, info in tuple(self._languages.items()):
            if info.folder == folder.resolve():
                del self._languages[tag]

    def resolve_language(self, configured_language: str) -> str:
        if not configured_language or configured_language.lower() == "system":
            candidates = list(fallback_tags(system_language()))
            for preferred in QLocale.system().uiLanguages():
                try:
                    candidates.extend(fallback_tags(preferred))
                except ValueError:
                    continue
        else:
            candidates = list(fallback_tags(configured_language))
        for candidate in candidates:
            if candidate in self._languages or candidate in ("ja", "ja-JP"):
                return candidate
        return DEFAULT_LANGUAGE

    def apply_language(self, app: QCoreApplication, language: str) -> None:
        global _current_language
        self.close()
        self._app = app
        code = self.resolve_language(language)
        _current_language = code
        qt_translator = QTranslator(app)
        locale = qt_locale(code)
        if locale is not None and qt_translator.load(
            locale, "qtbase", "_",
            QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
        ):
            app.installTranslator(qt_translator)
            self._installed.append(qt_translator)
        else:
            qt_translator.deleteLater()
        candidates = fallback_tags(code)
        if code == "ja":
            candidates = (*candidates, "ja-JP")
        for candidate in reversed(candidates):
            info = self._languages.get(candidate)
            if info is None:
                continue
            for qm in info.qm_paths:
                translator = QTranslator(app)
                if translator.load(str(qm)):
                    app.installTranslator(translator)
                    self._installed.append(translator)
                else:
                    translator.deleteLater()
        language_events().changed.emit(code)

    def close(self) -> None:
        if self._app is not None:
            for translator in self._installed:
                self._app.removeTranslator(translator)
                translator.deleteLater()
        self._installed.clear()
        self._app = None
