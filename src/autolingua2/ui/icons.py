from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.ui.i18n import system_language
from autolingua2.ui.theme import _resolve_locale_text


ICONS_DIR = PROJECT_ROOT / "theme" / "icons"
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
    def __init__(self, icons_dir: Path | None = None) -> None:
        self.icons_dir = icons_dir or ICONS_DIR
        self._current_iconset_id: str = DEFAULT_ICONSET_ID
        self._icon_cache: dict[str, QIcon] = {}

    def discover_iconsets(self, ui_language: str = "system") -> dict[str, IconSetInfo]:
        """icons ディレクトリ内の各アイコンセットを走査して IconSetInfo の辞書を返す。"""
        if not ui_language or ui_language.lower() == "system":
            ui_language = system_language()
        iconsets: dict[str, IconSetInfo] = {}
        if not self.icons_dir.exists():
            return iconsets

        for item in sorted(self.icons_dir.iterdir()):
            if not item.is_dir():
                continue

            meta_file = item / "iconset.json"
            if not meta_file.is_file():
                continue

            try:
                with open(meta_file, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue

            if not isinstance(meta, dict):
                continue

            iconset_id = str(meta.get("id") or item.name)
            name_key = meta.get("name_key", "")
            desc_key = meta.get("description_key", "")
            fmt = str(meta.get("format", "svg"))

            locales_dir = item / "locales"
            name = _resolve_locale_text(locales_dir, name_key, ui_language) if name_key else None
            if not name:
                name = iconset_id.capitalize()

            description = _resolve_locale_text(locales_dir, desc_key, ui_language) if desc_key else ""
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

        icon_dir = self.icons_dir / self._current_iconset_id
        # Search for svg, png, etc.
        extensions = [".svg", ".png"]
        icon_path: Path | None = None

        for ext in extensions:
            candidate = icon_dir / f"{icon_name}{ext}"
            if candidate.is_file():
                icon_path = candidate
                break

        # Fallback to default iconset if current iconset doesn't have it
        if icon_path is None and self._current_iconset_id != DEFAULT_ICONSET_ID:
            default_dir = self.icons_dir / DEFAULT_ICONSET_ID
            for ext in extensions:
                candidate = default_dir / f"{icon_name}{ext}"
                if candidate.is_file():
                    icon_path = candidate
                    break

        if icon_path and icon_path.is_file():
            icon = QIcon(str(icon_path))
        else:
            icon = QIcon()

        self._icon_cache[cache_key] = icon
        return icon
