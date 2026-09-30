from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.ui.i18n import system_language


THEMES_DIR = PROJECT_ROOT / "theme" / "themes"
DEFAULT_THEME_ID = "system"


@dataclass(slots=True)
class ThemeInfo:
    id: str
    name: str
    description: str
    type: str
    dir_path: Path
    qss_path: Path | None
    preview_path: Path | None
    qss_paths: list[Path] = field(default_factory=list)


def _resolve_locale_text(locales_dir: Path, key: str, language: str) -> str | None:
    if not locales_dir.exists() or not locales_dir.is_dir():
        return None

    # Candidate file names in order of preference
    candidates: list[str] = [f"{language}.json"]
    if "_" in language:
        candidates.append(f"{language.split('_')[0]}.json")
    if language != "en_US":
        candidates.extend(["en_US.json", "en.json"])

    for candidate in candidates:
        locale_file = locales_dir / candidate
        if locale_file.is_file():
            try:
                with open(locale_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and key in data:
                    return str(data[key])
            except Exception:
                continue

    # Fallback to any json file found
    for locale_file in locales_dir.glob("*.json"):
        try:
            with open(locale_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and key in data:
                return str(data[key])
        except Exception:
            continue

    return None


class ThemeManager:
    def __init__(self, themes_dir: Path | None = None) -> None:
        self.themes_dir = themes_dir or THEMES_DIR
        self._current_theme_id: str = DEFAULT_THEME_ID

    def discover_themes(self, ui_language: str = "system") -> dict[str, ThemeInfo]:
        """themes ディレクトリ内の各テーマを走査して ThemeInfo の辞書を返す。"""
        if not ui_language or ui_language.lower() == "system":
            ui_language = system_language()
        themes: dict[str, ThemeInfo] = {}
        if not self.themes_dir.exists():
            return themes

        for item in sorted(self.themes_dir.iterdir()):
            if not item.is_dir():
                continue

            meta_file = item / "theme.json"
            if not meta_file.is_file():
                continue

            try:
                with open(meta_file, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue

            if not isinstance(meta, dict):
                continue

            theme_id = str(meta.get("id") or item.name)
            name_key = meta.get("name_key", "")
            desc_key = meta.get("description_key", "")
            theme_type = str(meta.get("type", "system"))

            locales_dir = item / "locales"
            name = _resolve_locale_text(locales_dir, name_key, ui_language) if name_key else None
            if not name:
                name = theme_id.capitalize()

            description = _resolve_locale_text(locales_dir, desc_key, ui_language) if desc_key else ""
            if not description:
                description = ""

            qss_files = sorted(item.glob("*.qss"))
            qss_file = item / "style.qss"
            qss_path = qss_file if qss_file.is_file() else (qss_files[0] if qss_files else None)

            preview_file = item / "preview.png"
            preview_path = preview_file if preview_file.is_file() else None

            themes[theme_id] = ThemeInfo(
                id=theme_id,
                name=name,
                description=description,
                type=theme_type,
                dir_path=item,
                qss_path=qss_path,
                preview_path=preview_path,
                qss_paths=qss_files,
            )

        return themes

    def apply_theme(self, theme_id: str, app: QApplication | None = None) -> bool:
        """指定されたテーマをアプリケーションに適用する。"""
        if app is None:
            instance = QApplication.instance()
            if not isinstance(instance, QApplication):
                return False
            app = instance

        themes = self.discover_themes()
        theme = themes.get(theme_id)
        if not theme:
            # Fallback to system
            theme = themes.get("system")

        if not theme:
            app.setStyleSheet("")
            self._current_theme_id = "system"
            return True

        self._current_theme_id = theme.id
        combined_qss: list[str] = []
        for qss_p in theme.qss_paths:
            try:
                content = qss_p.read_text(encoding="utf-8").strip()
                if content:
                    combined_qss.append(content)
            except Exception:
                continue

        if combined_qss:
            app.setStyleSheet("\n\n".join(combined_qss))
            return True
        elif theme.qss_path and theme.qss_path.is_file():
            try:
                app.setStyleSheet(theme.qss_path.read_text(encoding="utf-8"))
                return True
            except Exception:
                app.setStyleSheet("")
                return False
        else:
            app.setStyleSheet("")
            return True

    @property
    def current_theme_id(self) -> str:
        return self._current_theme_id
