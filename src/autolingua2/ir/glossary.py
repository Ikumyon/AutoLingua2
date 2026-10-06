"""Shared glossaries and their project-independent inheritance rules."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable


PARTS_OF_SPEECH = ("名詞", "動詞", "形容詞", "副詞", "代名詞", "その他")


@dataclass(frozen=True, slots=True)
class Glossary:
    id: str
    name: str
    adapter_id: str
    game_id: str
    parent_id: str | None


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    id: str
    glossary_id: str
    source_language: str
    target_language: str
    part_of_speech: str
    source: str
    translation: str
    variants: tuple[str, ...] = ()
    memo: str = ""
    case_sensitive: bool = False


def glossary_chain(glossaries: Iterable[Glossary], glossary_id: str) -> list[Glossary]:
    """Return ancestors first; reject missing parents and cycles."""
    by_id = {item.id: item for item in glossaries}
    chain: list[Glossary] = []
    seen: set[str] = set()
    current: str | None = glossary_id
    while current is not None:
        if current in seen:
            raise ValueError("用語集の親子関係が循環しています。")
        seen.add(current)
        item = by_id.get(current)
        if item is None:
            raise ValueError("参照先の用語集が見つかりません。")
        chain.append(item)
        current = item.parent_id
    chain.reverse()
    if any((item.adapter_id, item.game_id) != (chain[0].adapter_id, chain[0].game_id)
           for item in chain):
        raise ValueError("親用語集のゲームが一致しません。")
    return chain


def resolve_terms(chain: Iterable[Glossary], terms: Iterable[GlossaryTerm],
                  source_language: str, target_language: str) -> list[GlossaryTerm]:
    by_glossary: dict[str, list[GlossaryTerm]] = {}
    for term in terms:
        if (term.source_language, term.target_language) == (source_language, target_language):
            by_glossary.setdefault(term.glossary_id, []).append(term)
    resolved: dict[str, GlossaryTerm] = {}
    for glossary in chain:
        for term in by_glossary.get(glossary.id, []):
            resolved[term.source] = term
    return sorted(resolved.values(), key=lambda term: (term.source.casefold(), term.source))
