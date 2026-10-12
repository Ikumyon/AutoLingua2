"""Translation conditions and game text protection, independent of UI and storage."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re

from autolingua2.ir.filter_rules import TagKind, TagRules


class LowModelRange(str, Enum):
    NARROW = "narrow"
    STANDARD = "standard"
    WIDE = "wide"

    @property
    def bounds(self) -> tuple[int, int, float]:
        return {
            LowModelRange.NARROW: (2, 6, .95),
            LowModelRange.STANDARD: (4, 12, .90),
            LowModelRange.WIDE: (6, 18, .85),
        }[self]


@dataclass(frozen=True, slots=True)
class ModelSelection:
    provider_id: str
    model_id: str


@dataclass(frozen=True, slots=True)
class TranslationTextRules:
    sentence_endings: str = ".。!?！？"
    sentence_exceptions: tuple[str, ...] = ()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def translation_conditions(languages: tuple[str, str], template: str,
                           tone: tuple[str, str, str] | None,
                           terms: tuple[tuple[str, str, str, str, bool, tuple[str, ...]], ...]) -> str:
    return json.dumps({
        "languages": sorted(language.replace("_", "-").lower() for language in languages),
        "template": template, "tone": tone,
        "terms": sorted((source.replace("_", "-").lower(), target.replace("_", "-").lower(),
                         original, translated, sensitive, tuple(sorted(variants)))
                        for source, target, original, translated, sensitive, variants in terms),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_TOKEN = re.compile(r"⟦T\d+⟧")


def _protect_literals(translated: str, table: dict[str, str]) -> str:
    tokens: dict[str, deque[str]] = {}
    for token, literal in table.items():
        if not literal:
            raise ValueError("装飾位置を安全に復元できません。")
        tokens.setdefault(literal, deque()).append(token)
    if not tokens:
        return translated
    patterns = [(r"(?<!\d)" + re.escape(value) + r"(?!\d)")
                if re.fullmatch(r"\d+(?:[.,]\d+)*", value) else re.escape(value)
                for value in sorted(tokens, key=lambda value: -len(value))]
    pattern = re.compile("|".join(patterns))
    if Counter(match[0] for match in pattern.finditer(translated)) != Counter(table.values()):
        raise ValueError("訳文のタグ・数字が原文と一致しません。")
    return pattern.sub(lambda match: tokens[match[0]].popleft(), translated)


@dataclass(frozen=True, slots=True)
class ProtectedGroup:
    text: str
    restorations: dict[str, dict[str, str]]
    control_tokens: frozenset[str]

    def validate(self, translated: str, *, source: str | None = None) -> None:
        original = self.text if source is None else source
        if Counter(_TOKEN.findall(translated)) != Counter(_TOKEN.findall(original)):
            raise ValueError("保護トークンの欠落・重複・未知の追加があります。")
        if ([token for token in _TOKEN.findall(translated) if token in self.control_tokens]
                != [token for token in _TOKEN.findall(original) if token in self.control_tokens]):
            raise ValueError("表示制御タグの順序が変わっています。")
        if "⟦" in _TOKEN.sub("", translated) or "⟧" in _TOKEN.sub("", translated):
            raise ValueError("不正な保護トークンがあります。")
        if any(char.isdecimal() for char in _TOKEN.sub("", translated)):
            raise ValueError("原文に対応しない数字が追加されています。")

    def restore(self, translated: str, unit_id: str) -> str:
        self.validate(translated)
        table = self.restorations[unit_id]
        return _TOKEN.sub(lambda match: table[match[0]], translated)

    def bare(self, translated: str, unit_id: str) -> str:
        table = self.restorations[unit_id]
        return _TOKEN.sub(lambda match: "" if match[0] in self.control_tokens else table[match[0]], translated)

    def protect_memory(self, translated: str, unit_id: str, source: str) -> str | None:
        tokens = _TOKEN.findall(source)
        if any(token in self.control_tokens for token in tokens):
            return None
        table = self.restorations[unit_id]
        try:
            translated = _protect_literals(translated, {token: table[token] for token in tokens})
            self.validate(translated, source=source)
        except ValueError:
            return None
        return translated


def protect_group(sources: dict[str, str], rules: TagRules) -> ProtectedGroup:
    if not sources:
        raise ValueError("翻訳する原文がありません。")
    exact = {unit_id: rules.analyze(source)[0] for unit_id, source in sources.items()}
    body = next(iter(exact.values()))
    if any(value != body for value in exact.values()):
        raise ValueError("完全一致しない原文の訳は共有できません。")
    if "⟦" in body or "⟧" in body:
        raise ValueError("原文に予約済みの保護トークン文字があります。")
    controls: dict[str, dict[int, list[str]]] = {}
    contents: dict[tuple[int, int], str] = {}
    for unit_id, source in sources.items():
        shift = 0
        positions: dict[int, list[str]] = {}
        for start, end, kind in rules.spans(source):
            if kind == TagKind.DISPLAY_CONTROL:
                positions.setdefault(start - shift, []).append(source[start:end])
                shift += end - start
            else:
                contents[(start - shift, end - shift)] = source[start:end]
        controls[unit_id] = positions
    for match in re.finditer(r"\d+(?:[.,]\d+)*", body):
        if not any(start <= match.start() < end for start, end in contents):
            contents[(match.start(), match.end())] = match[0]
    events: list[tuple[int, int, int, int, str]] = []
    for position in sorted({position for positions in controls.values() for position in positions}):
        count = max(len(positions.get(position, [])) for positions in controls.values())
        events.extend((position, 0, ordinal, position, "") for ordinal in range(count))
    events.extend((start, 1, 0, end, literal) for (start, end), literal in contents.items())
    events.sort()
    tables: dict[str, dict[str, str]] = {unit_id: {} for unit_id in sources}
    control_tokens: set[str] = set()
    result: list[str] = []
    position = 0
    for start, kind, ordinal, end, literal in events:
        if start < position:
            raise ValueError("保護範囲と装飾の位置が重複しています。")
        result.append(body[position:start])
        token = f"⟦T{len(tables[next(iter(sources))])}⟧"
        result.append(token)
        for unit_id, table in tables.items():
            tags = controls[unit_id].get(start, [])
            table[token] = (tags[ordinal] if ordinal < len(tags) else "") if kind == 0 else literal
        if kind == 0:
            control_tokens.add(token)
        position = end
    result.append(body[position:])
    return ProtectedGroup("".join(result), tables, frozenset(control_tokens))


def split_sentences(text: str, rules: TranslationTextRules) -> tuple[str, ...]:
    protected = [(match.start(), match.end()) for match in _TOKEN.finditer(text)]
    protected.extend((match.start(), match.end())
                     for pattern in rules.sentence_exceptions for match in re.finditer(pattern, text))
    parts: list[str] = []
    start = 0
    for position, char in enumerate(text):
        if char not in rules.sentence_endings or any(left <= position < right for left, right in protected):
            continue
        if char == "." and position > 0 and position + 1 < len(text) and text[position - 1].isdigit() and text[position + 1].isdigit():
            continue
        if position + 1 < len(text) and text[position + 1] in rules.sentence_endings:
            continue
        end = position + 1
        while end < len(text) and text[end].isspace():
            end += 1
        parts.append(text[start:end])
        start = end
    if start < len(text):
        parts.append(text[start:])
    return tuple(parts) or (text,)


def protect_edited_group(group: ProtectedGroup, unit_id: str, translated: str) -> str:
    """Share only when the edited text explicitly retains every required boundary."""
    table = group.restorations[unit_id]
    if any(not value and any(other[token] for other in group.restorations.values()) for token, value in table.items()):
        raise ValueError("この訳文にない装飾の位置を安全に復元できないため、同じ文へ適用できません。個別の訳文は保存されています。")
    translated = _protect_literals(translated, table)
    group.validate(translated)
    return translated
