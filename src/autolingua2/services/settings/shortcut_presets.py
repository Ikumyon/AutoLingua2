"""YAML shortcut presets. File contents, rather than a second registry, are authoritative."""
from __future__ import annotations

from pathlib import Path
import re

import yaml
from PySide6.QtCore import QIODevice, QSaveFile

from autolingua2.infrastructure.filesystem import DATA_DIR
from autolingua2.infrastructure.platform import qt_file_path
from autolingua2.ir.shortcuts import ShortcutPreset
from autolingua2.ir.validation import array, record, required, text


class ShortcutPresetStore:
    def __init__(self) -> None:
        self.directory = DATA_DIR / "presets" / "shortcuts"
        self.paths: dict[str, Path] = {}
        self.errors: list[str] = []

    def path_for(self, preset_id: str) -> Path:
        if re.fullmatch(r"[a-zA-Z0-9_-]+", preset_id) is None:
            raise ValueError(f"Invalid shortcut preset ID: {preset_id}")
        return self.directory / f"{preset_id}.alshortcut"

    def load(self) -> dict[str, ShortcutPreset]:
        self.paths.clear()
        self.errors.clear()
        presets: dict[str, ShortcutPreset] = {}
        duplicates: set[str] = set()
        for path in sorted(self.directory.glob("*.alshortcut")):
            try:
                preset = self._parse(path)
                if preset.id in duplicates or preset.id in presets:
                    duplicates.add(preset.id)
                    previous = self.paths.pop(preset.id, None)
                    presets.pop(preset.id, None)
                    raise ValueError(f"Duplicate ID {preset.id}: {previous}, {path}")
                self.paths[preset.id] = path
                presets[preset.id] = preset
            except (ValueError, OSError, UnicodeError, yaml.YAMLError) as error:
                self.errors.append(f"{path.name}: {error}")
        return presets

    def _parse(self, path: Path) -> ShortcutPreset:
        data = record(yaml.safe_load(path.read_text(encoding="utf-8")))
        if data.get("type") != "shortcuts" or type(data.get("type_version")) is not int or data["type_version"] != 1:
            raise ValueError("Unsupported shortcut preset type/version")
        meta = record(required(data, "metadata"))
        preset_id = text(required(meta, "id"), nonempty=True)
        self.path_for(preset_id)
        author = record(meta.get("author", {"name": "User"}))
        bindings = record(required(data, "shortcuts"))
        return ShortcutPreset(
            id=preset_id, name=text(required(meta, "name"), nonempty=True),
            description=text(meta.get("description", "")), author=text(author.get("name", "User")),
            tags=[text(tag) for tag in array(meta.get("tags", []))],
            version=text(required(meta, "preset_version"), nonempty=True),
            shortcuts={key: [text(value, nonempty=True) for value in array(values)]
                       for key, values in bindings.items()},
        )

    def write(self, preset: ShortcutPreset) -> None:
        path = self.paths.get(preset.id, self.path_for(preset.id))
        payload = yaml.safe_dump({
            "type": "shortcuts", "type_version": 1,
            "metadata": {"id": preset.id, "preset_version": preset.version,
                         "name": preset.name, "description": preset.description,
                         "author": {"name": preset.author}, "tags": preset.tags},
            "shortcuts": preset.shortcuts,
        }, allow_unicode=True, sort_keys=False).encode("utf-8")
        self.write_bytes(path, payload)
        self.paths[preset.id] = path

    @staticmethod
    def write_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        output = QSaveFile(qt_file_path(path))
        output.setDirectWriteFallback(False)
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(f"{path}: {output.errorString()}")
        if output.write(payload) != len(payload):
            error = output.errorString()
            output.cancelWriting()
            raise OSError(f"{path}: {error}")
        if not output.commit():
            raise OSError(f"{path}: {output.errorString()}")
