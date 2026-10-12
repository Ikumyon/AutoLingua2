from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
import unicodedata
from .validation import array, boolean, record, required, string_field, text

class TagKind(str, Enum):
    """Display roles of untranslated tags; stored values remain stable."""

    DISPLAY_CONTENT = "text"
    DISPLAY_CONTROL = "non_text"


@dataclass(frozen=True, slots=True)
class FilterRule:
    id: str
    kind: TagKind
    enabled: bool = True
    pattern: str = ""
    example: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> FilterRule:
        data = record(value)
        return cls(
            id=text(required(data, "id"), nonempty=True),
            kind=TagKind(text(required(data, "kind"))),
            enabled=boolean(data.get("enabled", True)),
            pattern=string_field(data, "pattern"),
            example=string_field(data, "example"),
        )


@dataclass(slots=True)
class AdapterFilterConfig:
    rules: list[FilterRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"rules": [rule.to_dict() for rule in self.rules]}

    @classmethod
    def from_dict(cls, value: object) -> AdapterFilterConfig:
        data = record(value)
        return cls([FilterRule.from_dict(item) for item in array(required(data, "rules"))])


class TagRules:
    """A compiled snapshot shared by comparison and list exclusion."""

    def __init__(self, config: AdapterFilterConfig) -> None:
        self._patterns = tuple(
            (rule.kind, re.compile(rule.pattern))
            for rule in config.rules if rule.enabled and rule.pattern.strip()
        )

    def analyze(self, source: str) -> tuple[str, str, bool]:
        """Return exact text, similarity comparison text, and the existing hidden flag."""
        matches = self.spans(source)
        exact: list[str] = []
        ordinary: list[str] = []
        has_content = False
        position = 0

        def append_ordinary(value: str) -> None:
            nonlocal has_content
            exact.append(value)
            normalized = unicodedata.normalize("NFC", value)
            ordinary.append(normalized)
            has_content = has_content or any(
                not char.isspace() and unicodedata.category(char)[0] not in "NPS"
                for char in normalized
            )

        for start, end, kind in matches:
            append_ordinary(source[position:start])
            if kind == TagKind.DISPLAY_CONTENT:
                exact.append(source[start:end])
            position = end
        append_ordinary(source[position:])
        return "".join(exact), unicodedata.normalize("NFC", "".join(ordinary)), not has_content

    def spans(self, source: str) -> tuple[tuple[int, int, TagKind], ...]:
        """Return the same non-overlapping tag ranges used by classification."""
        matches = sorted(
            [(match.start(), match.end(), kind)
             for kind, pattern in self._patterns
             for match in pattern.finditer(source) if match.end() > match.start()],
            key=lambda item: (item[0], -item[1], item[2] != TagKind.DISPLAY_CONTENT),
        )
        accepted: list[tuple[int, int, TagKind]] = []
        position = 0
        for start, end, kind in matches:
            if start < position:
                continue
            accepted.append((start, end, kind))
            position = end
        return tuple(accepted)
