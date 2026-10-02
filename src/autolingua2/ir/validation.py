"""Validation of untrusted JSON values at domain boundaries."""
from __future__ import annotations

from typing import TypeGuard


def _is_record(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def record(value: object) -> dict[str, object]:
    if not _is_record(value):
        raise ValueError("Expected an object with string keys")
    return value


def array(value: object) -> list[object]:
    if not _is_array(value):
        raise ValueError("Expected an array")
    return value


def text(value: object, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError("Expected a nonempty string" if nonempty else "Expected a string")
    return value


def boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Expected a boolean")
    return value


def string_field(data: dict[str, object], name: str, default: str = "") -> str:
    return text(data.get(name, default))


def required(data: dict[str, object], name: str) -> object:
    if name not in data:
        raise ValueError(f"Missing required field: {name}")
    return data[name]
