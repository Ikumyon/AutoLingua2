from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from autolingua2.ir.validation import record, required, text, string_field
from autolingua2.ui.i18n import system_language
from autolingua2.ui.resource_locales import resolve_locale_text


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


class ThemeManager:
    def __init__(self) -> None:
        self._packages: dict[str, tuple[Path, dict[str, object]]] = {}
        self._current_theme_id: str = DEFAULT_THEME_ID

    def _register(self, path: Path) -> None:
        meta = record(json.loads((path / "theme.json").read_text(encoding="utf-8")))
        package_id = text(required(meta, "id"), nonempty=True)
        if package_id in self._packages:
            raise ValueError(f"Duplicate theme ID: {package_id}")
        for key in ("name_key", "description_key", "type"):
            if key in meta:
                text(meta[key])
        self._packages[package_id] = (path, meta)

    def available_themes(self, ui_language: str = "system") -> dict[str, ThemeInfo]:
        """Return registered packages; never discover additional directories."""
        if not ui_language or ui_language.lower() == "system":
            ui_language = system_language()
        themes: dict[str, ThemeInfo] = {}
        for package_id, (item, meta) in self._packages.items():
            theme_id = package_id
            name_key = string_field(meta, "name_key")
            desc_key = string_field(meta, "description_key")
            theme_type = string_field(meta, "type", "system")

            locales_dir = item / "locales"
            name = resolve_locale_text(locales_dir, name_key, ui_language) if name_key else None
            if not name:
                name = theme_id.capitalize()

            description = resolve_locale_text(locales_dir, desc_key, ui_language) if desc_key else ""
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

        themes = self.available_themes()
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
