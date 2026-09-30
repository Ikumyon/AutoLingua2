from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Iterable

from .protection import PROTECTED_RE, protect_text


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,]\d+)*(?![A-Za-z0-9_])")


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: int
    source: str
    target: str
    source_language: str
    target_language: str
    provenance: str
    context: str = ""


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    target: str
    entry_id: int
    method: str


def valid_protected_tokens(source: str, target: str) -> bool:
    return Counter(PROTECTED_RE.findall(source)) == Counter(PROTECTED_RE.findall(target))


def structure_signature(source: str) -> str:
    protected, tokens = protect_text(source)
    if tokens:
        return "tokens:" + protected
    return "numbers:" + NUMBER_RE.sub("__AL_NUMBER__", source) if NUMBER_RE.search(source) else ""


def select_match(
    source: str,
    entries: Iterable[MemoryEntry],
    source_language: str,
    target_language: str,
    context: str = "",
) -> MemoryMatch | None:
    eligible = [
        entry for entry in entries
        if entry.source_language == source_language
        and entry.target_language == target_language
        and entry.provenance != "imported_unverified"
        and entry.target.strip()
        and entry.target != entry.source
        and valid_protected_tokens(entry.source, entry.target)
    ]
    exact = [entry for entry in eligible if entry.source == source]
    if exact:
        preferred = [entry for entry in exact if entry.context == context] if context else []
        chosen = preferred or exact
        targets = {entry.target for entry in chosen}
        if len(targets) != 1:
            return None
        best = sorted(chosen, key=lambda entry: (entry.provenance != "human", -entry.id))[0]
        return MemoryMatch(best.target, best.id, "exact")

    signature = structure_signature(source)
    if not signature:
        return None
    structural: list[MemoryMatch] = []
    for entry in eligible:
        if structure_signature(entry.source) != signature or entry.source == source:
            continue
        target = _expand(entry.source, entry.target, source, target_language)
        if target is not None and target != source and valid_protected_tokens(source, target):
            structural.append(MemoryMatch(target, entry.id, "structural"))
    if len({match.target for match in structural}) != 1:
        return None
    return structural[0]


def _expand(old_source: str, old_target: str, new_source: str, target_language: str) -> str | None:
    old_masked, old_tokens = protect_text(old_source)
    new_masked, new_tokens = protect_text(new_source)
    if old_tokens and old_masked == new_masked and len(old_tokens) == len(new_tokens):
        replacements: list[tuple[str, str]] = []
        for old, new in zip(old_tokens, new_tokens):
            if old == new:
                continue
            if not ((old.startswith("$") and new.startswith("$")) or
                    (old.startswith("[") and new.startswith("["))):
                return None
            if old_target.count(old) != 1 or old_target.count(new) != 0:
                return None
            replacements.append((old, new))
        if not replacements:
            return None
        result = old_target
        for index, (old, _) in enumerate(replacements):
            result = result.replace(old, f"__AL_SWAP_{index}__", 1)
        for index, (_, new) in enumerate(replacements):
            result = result.replace(f"__AL_SWAP_{index}__", new, 1)
        return result

    if old_tokens or new_tokens or target_language != "ja":
        return None
    old_numbers = NUMBER_RE.findall(old_source)
    new_numbers = NUMBER_RE.findall(new_source)
    target_numbers = NUMBER_RE.findall(old_target)
    if not old_numbers or len(old_numbers) != len(set(old_numbers)):
        return None
    if target_numbers != old_numbers or len(new_numbers) != len(old_numbers):
        return None
    if NUMBER_RE.sub("__AL_NUMBER__", old_source) != NUMBER_RE.sub("__AL_NUMBER__", new_source):
        return None
    replacement_numbers = iter(new_numbers)
    return NUMBER_RE.sub(lambda _: next(replacement_numbers), old_target)
