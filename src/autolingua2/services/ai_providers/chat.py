"""Provider-independent chat contracts exposed through the plugin entrance."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatReply:
    text: str
    calls: list[ChatToolCall] = field(default_factory=list)
    # Keep the original provider message, including Gemini thought signatures,
    # only for continuation of this turn. Completed history stays portable.
    message: dict[str, Any] = field(default_factory=dict)


def object_value(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def string_value(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value
