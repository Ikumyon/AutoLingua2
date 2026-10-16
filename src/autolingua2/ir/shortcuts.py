"""Shortcut definitions and preset data, independent of UI objects."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ShortcutCommand:
    id: str
    name: str
    location: str
    scope: str
    defaults: tuple[str, ...] = ()


@dataclass(slots=True)
class ShortcutPreset:
    id: str
    name: str
    description: str = ""
    author: str = "User"
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    shortcuts: dict[str, list[str]] = field(default_factory=dict)


def scopes_overlap(first: str, second: str) -> bool:
    """Slash-separated scopes describe nested activation areas in one window."""
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")
