from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator, QObject, Signal

from collections.abc import Mapping
from types import MappingProxyType

from autolingua2.ir.validation import record, required, text


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


class LocalizationManager:
    """Owns only application dictionaries; plugin dictionaries remain independent."""

    def __init__(self) -> None:
        self._languages: dict[str, LanguageInfo] = {}
        self._installed: list[QTranslator] = []
        self._app: QCoreApplication | None = None

    def _register(self, path: Path) -> None:
        meta = record(json.loads((path / "metadata.json").read_text(encoding="utf-8")))
        code = normalize_language(text(required(meta, "code"), nonempty=True))
        name = text(required(meta, "name"), nonempty=True)
        if code in self._languages:
            raise ValueError(f"Duplicate UI language: {code}")
        flag = text(meta.get("flag", ""))
        flag_path = path / flag if flag else None
        if flag_path is not None and not flag_path.is_file():
            flag_path = None
        self._languages[code] = LanguageInfo(code, name, flag_path, sorted(path.glob("*.qm")))

    @property
    def available_languages(self) -> Mapping[str, LanguageInfo]:
        return MappingProxyType(self._languages)

    def resolve_language(self, configured_language: str) -> str:
        if not configured_language or configured_language.lower() == "system":
            code = system_language()
            if code in self._languages:
                return code
            prefix = code.split("_")[0]
            for available in self._languages:
                if available.split("_")[0] == prefix:
                    return available
            return DEFAULT_LANGUAGE
        return normalize_language(configured_language)

    def apply_language(self, app: QCoreApplication, language: str) -> None:
        global _current_language
        self.close()
        self._app = app
        code = self.resolve_language(language)
        _current_language = code
        info = self._languages.get(code)
        if info is not None:
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
