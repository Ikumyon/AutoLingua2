"""Public, widget-free application operations shared by chat, MCP and plugins."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from autolingua2.ir.validation import array, record, text

Permission = Literal["read", "edit", "translate", "export"]
PERMISSIONS: tuple[Permission, ...] = ("read", "edit", "translate", "export")


@dataclass(frozen=True, slots=True)
class PluginInformation:
    """One manifest's admission result, supplied by the official entrance."""
    id: str | None
    name: str
    version: str | None
    description: str
    kind: str | None
    source: Literal["builtin", "external"]
    directory: str
    status: Literal["loaded", "failed"]
    capabilities: tuple[str, ...] = ()
    error: str = ""


class OperationContext(Protocol):
    """Plugins receive snapshots and the public dispatcher, never host internals."""
    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class OperationTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    permission: Permission = "read"

    def document(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "inputSchema": self.input_schema,
                "annotations": {"readOnlyHint": self.permission == "read",
                                "openWorldHint": False}}


@dataclass(frozen=True, slots=True)
class OperationContribution:
    tool: OperationTool
    execute: Callable[[OperationContext, dict[str, Any]], dict[str, Any]]


def validate_arguments(value: object, schema: dict[str, Any], path: str = "arguments") -> None:
    """Validate the deliberately small JSON Schema vocabulary used by operations."""
    kind = schema.get("type")
    if kind == "object":
        data = record(value)
        properties = record(schema.get("properties", {}))
        for key in array(schema.get("required", [])):
            if text(key) not in data:
                raise ValueError(f"{path}: {key} is required")
        if schema.get("additionalProperties") is False and set(data) - set(properties):
            raise ValueError(f"{path}: unknown arguments")
        for key, item in data.items():
            if key in properties:
                validate_arguments(item, record(properties[key]), f"{path}.{key}")
    elif kind == "array":
        items = array(value)
        if len(items) > schema.get("maxItems", 1000):
            raise ValueError(f"{path}: too many items")
        for item in items:
            validate_arguments(item, record(schema.get("items", {})), path)
    elif kind == "string":
        result = text(value)
        if len(result) > schema.get("maxLength", 200_000):
            raise ValueError(f"{path}: text is too long")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected boolean")
    elif kind == "integer":
        if type(value) is not int or value < schema.get("minimum", 0) or value > schema.get("maximum", 1_000_000):
            raise ValueError(f"{path}: invalid integer")
    elif kind is not None:
        raise ValueError(f"{path}: unsupported schema type {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid choice")


@dataclass(slots=True)
class ExternalMcpConnection:
    id: str
    name: str
    transport: Literal["stdio", "http"]
    address: str
    arguments: list[str] = field(default_factory=list)
    token: str = ""


@dataclass(slots=True)
class McpSettings:
    enabled: bool = False
    port: int = 0
    token: str = ""
    permissions: list[Permission] = field(default_factory=lambda: list(PERMISSIONS))
    connections: list[ExternalMcpConnection] = field(default_factory=list)


@dataclass(slots=True)
class OperationJob:
    id: str
    kind: str
    project_id: str
    status: str = "waiting"
    completed: int = 0
    total: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
