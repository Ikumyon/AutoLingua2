from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PySide6.QtGui import QIcon

from autolingua2.ir.validation import record, required, text, string_field
from autolingua2.ui.i18n import system_language
from autolingua2.ui.resource_locales import resolve_locale_text


DEFAULT_ICONSET_ID = "default"


@dataclass(slots=True)
class IconSetInfo:
    id: str
    name: str
    description: str
    format: str
    dir_path: Path
    preview_path: Path | None


class IconManager:
    def __init__(self) -> None:
        self._packages: dict[str, tuple[Path, dict[str, object]]] = {}
        self._current_iconset_id: str = DEFAULT_ICONSET_ID
        self._icon_cache: dict[str, QIcon] = {}

    def _register(self, path: Path) -> None:
        meta = record(json.loads((path / "iconset.json").read_text(encoding="utf-8")))
        package_id = text(required(meta, "id"), nonempty=True)
        if package_id in self._packages:
            raise ValueError(f"Duplicate iconset ID: {package_id}")
        for key in ("name_key", "description_key", "format"):
            if key in meta:
                text(meta[key])
        self._packages[package_id] = (path, meta)
        self._icon_cache.clear()

    def available_iconsets(self, ui_language: str = "system") -> dict[str, IconSetInfo]:
        """Return registered packages; never discover additional directories."""
        if not ui_language or ui_language.lower() == "system":
            ui_language = system_language()
        iconsets: dict[str, IconSetInfo] = {}
        for package_id, (item, meta) in self._packages.items():
            iconset_id = package_id
            name_key = string_field(meta, "name_key")
            desc_key = string_field(meta, "description_key")
            fmt = string_field(meta, "format", "svg")

            locales_dir = item / "locales"
            name = resolve_locale_text(locales_dir, name_key, ui_language) if name_key else None
            if not name:
                name = iconset_id.capitalize()

            description = resolve_locale_text(locales_dir, desc_key, ui_language) if desc_key else ""
            if not description:
                description = ""

            preview_file = item / "preview.png"
            preview_path = preview_file if preview_file.is_file() else None

            iconsets[iconset_id] = IconSetInfo(
                id=iconset_id,
                name=name,
                description=description,
                format=fmt,
                dir_path=item,
                preview_path=preview_path,
            )

        return iconsets

    def set_current_iconset(self, iconset_id: str) -> None:
        if self._current_iconset_id != iconset_id:
            self._current_iconset_id = iconset_id
            self._icon_cache.clear()

    @property
    def current_iconset_id(self) -> str:
        return self._current_iconset_id

    def get_icon(self, icon_name: str) -> QIcon:
        """指定されたアイコン名の QIcon を取得して返す（キャッシュ対応）。"""
        cache_key = f"{self._current_iconset_id}:{icon_name}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        icon_path: Path | None = None
        for package_id in dict.fromkeys((self._current_iconset_id, DEFAULT_ICONSET_ID)):
            package = self._packages.get(package_id)
            if package is None:
                continue
            directory, _ = package
            for extension in (".svg", ".png"):
                candidate = directory / f"{icon_name}{extension}"
                if candidate.is_file():
                    icon_path = candidate
                    break
            if icon_path is not None:
                break

        if icon_path and icon_path.is_file():
            icon = QIcon(str(icon_path))
        else:
            icon = QIcon()

        self._icon_cache[cache_key] = icon
        return icon
