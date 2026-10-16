"""Shared glossaries and their project-independent inheritance rules."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Iterable


PARTS_OF_SPEECH = ("名詞", "動詞", "形容詞", "副詞")


@dataclass(frozen=True, slots=True)
class Glossary:
    id: str
    name: str
    adapter_id: str
    game_id: str
    parent_id: str | None
    languages: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class TermSide:
    text: str
    variants: tuple[str, ...] = ()
    case_sensitive: bool = False


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    id: str
    glossary_id: str
    part_of_speech: str
    a: TermSide
    b: TermSide
    memo: str = ""
    key: str = ""


@dataclass(frozen=True, slots=True)
class DirectedTerm:
    """Temporary projection for display/translation; never persisted."""
    term: GlossaryTerm
    source_language: str
    target_language: str
    source: str
    translation: str
    variants: tuple[str, ...]
    target_variants: tuple[str, ...]
    case_sensitive: bool
    target_case_sensitive: bool
    source_is_a: bool

    @property
    def id(self) -> str:
        return self.term.id

    @property
    def glossary_id(self) -> str:
        return self.term.glossary_id

    @property
    def part_of_speech(self) -> str:
        return self.term.part_of_speech

    @property
    def memo(self) -> str:
        return self.term.memo


def orient_term(term: GlossaryTerm, languages: tuple[str, str], source: str) -> DirectedTerm:
    if source not in languages:
        raise ValueError("用語集の言語が一致しません。")
    a, b = (term.a, term.b) if source == languages[0] else (term.b, term.a)
    target = languages[1] if source == languages[0] else languages[0]
    return DirectedTerm(term, source, target, a.text, b.text, a.variants, b.variants,
                        a.case_sensitive, b.case_sensitive, source == languages[0])


def edited_term(view: DirectedTerm, source: TermSide, target: TermSide,
                part_of_speech: str, memo: str) -> GlossaryTerm:
    """Map edited display values back to their original language slots."""
    a, b = (source, target) if view.source_is_a else (target, source)
    return replace(view.term, a=a, b=b, part_of_speech=part_of_speech, memo=memo)


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
    if any(item.languages is not None for item in chain[1:]):
        raise ValueError("言語の組は最上位の親用語集だけに設定してください。")
    return chain


def resolve_terms(chain: Iterable[Glossary], terms: Iterable[GlossaryTerm]) -> list[GlossaryTerm]:
    by_glossary: dict[str, list[GlossaryTerm]] = {}
    for term in terms:
        by_glossary.setdefault(term.glossary_id, []).append(term)
    resolved: dict[str, GlossaryTerm] = {}
    for glossary in chain:
        for term in by_glossary.get(glossary.id, []):
            resolved[term.key] = term
    return sorted(resolved.values(), key=lambda term: (term.a.text.casefold(), term.a.text))
