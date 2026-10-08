from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class WatchTarget:
    project_path: str
    name: str
    source_root: str
    suffixes: list[str]
    icon_path: str = ""
    sound_path: str = ""
    adapter_id: str = ""
    source_language: str = ""


@dataclass(slots=True)
class WatchSettings:
    enabled: bool = False
    targets: list[WatchTarget] = field(default_factory=list)
