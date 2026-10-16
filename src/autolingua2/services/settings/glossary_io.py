"""Portable glossary documents, validation and export selection (no widgets)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

from autolingua2.ir.glossary import Glossary, GlossaryTerm, TermSide, PARTS_OF_SPEECH, glossary_chain, resolve_terms
from .glossary_format import GlossaryImportData


class ExportMode(StrEnum):
    OWN = "own"
    FLAT = "flat"
    ANCESTORS = "ancestors"
    ALL = "all"


class ImportMode(StrEnum):
    MERGE = "merge"
    NEW = "new"


@dataclass(frozen=True, slots=True)
class GlossaryDocument:
    glossaries: tuple[Glossary, ...]
    terms: tuple[GlossaryTerm, ...]


@dataclass(frozen=True, slots=True)
class ImportResult:
    created: int
    added: int
    updated: int
    glossary_id: str


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("JSONオブジェクトで指定してください。")
    return dict(value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("JSON配列で指定してください。")
    return list(value)


def _string(data: dict[str, object], key: str, *, empty: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{key}は{'空でない' if not empty else ''}文字列で指定してください。")
    return value if empty else value.strip()


def parse_document(value: object) -> GlossaryDocument:
    data = _object(value)
    if data.get("format") != "autolingua2-glossary":
        raise ValueError("AUTOlingua2用語集の形式ではありません。")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("対応していない用語集バージョンです。")
    glossaries: list[Glossary] = []
    terms: list[GlossaryTerm] = []
    ids: set[str] = set()
    for raw in _array(data.get("glossaries")):
        item = _object(raw)
        gid, name = _string(item, "id"), _string(item, "name")
        if gid in ids:
            raise ValueError("用語集IDが重複しています。")
        ids.add(gid)
        if "parent_id" not in item:
            raise ValueError("parent_idがありません。")
        parent = item["parent_id"]
        if parent is not None:
            parent = _string(item, "parent_id")
        languages = None
        if parent is None:
            pair = _array(item.get("languages"))
            if len(pair) != 2 or any(not isinstance(v, str) or not v.strip() for v in pair):
                raise ValueError("最上位の親に異なる2言語を指定してください。")
            first, second = pair
            if not isinstance(first, str) or not isinstance(second, str) or first.strip() == second.strip():
                raise ValueError("異なる2言語を指定してください。")
            languages = (first.strip(), second.strip())
        elif "languages" in item:
            raise ValueError("子用語集に言語の組は指定できません。")
        glossaries.append(Glossary(gid, name, "", "", parent, languages))
        keys: set[str] = set()
        a_texts: set[str] = set()
        b_texts: set[str] = set()
        for raw_term in _array(item.get("terms")):
            entry = _object(raw_term)
            term = GlossaryTerm("", gid, _string(entry, "part_of_speech"),
                _parse_side(entry.get("a")), _parse_side(entry.get("b")),
                _string(entry, "memo", empty=True), _string(entry, "key"))
            if term.part_of_speech not in PARTS_OF_SPEECH:
                raise ValueError("品詞が不正です。")
            if term.key in keys or term.a.text in a_texts or term.b.text in b_texts:
                raise ValueError("用語のキーまたは表現が重複しています。")
            keys.add(term.key)
            a_texts.add(term.a.text)
            b_texts.add(term.b.text)
            terms.append(term)
    if sum(g.parent_id is None for g in glossaries) != 1:
        raise ValueError("ルート用語集は1件で指定してください。")
    # Validate all references before ordering parents ahead of children.
    chains = {g.id: glossary_chain(glossaries, g.id) for g in glossaries}
    glossaries.sort(key=lambda g: (len(chains[g.id]), g.name, g.id))
    for glossary in glossaries:
        effective = resolve_terms(chains[glossary.id], terms)
        if len({t.a.text for t in effective}) != len(effective) or len({t.b.text for t in effective}) != len(effective):
            raise ValueError("継承後の用語の表現が重複しています。")
    return GlossaryDocument(tuple(glossaries), tuple(terms))


def _parse_side(value: object) -> TermSide:
    data = _object(value)
    variants: list[str] = []
    for variant in _array(data.get("variants")):
        if not isinstance(variant, str):
            raise ValueError("variantsは文字列の配列で指定してください。")
        if variant.strip() and variant.strip() not in variants:
            variants.append(variant.strip())
    sensitive = data.get("case_sensitive")
    if not isinstance(sensitive, bool):
        raise ValueError("case_sensitiveは真偽値で指定してください。")
    return TermSide(_string(data, "text"), tuple(variants), sensitive)


def document_data(document: GlossaryDocument) -> dict[str, object]:
    items: list[dict[str, object]] = []
    for glossary in document.glossaries:
        entries: list[dict[str, object]] = []
        for term in document.terms:
            if term.glossary_id == glossary.id:
                entry = asdict(term)
                del entry["id"], entry["glossary_id"]
                entry["a"]["variants"] = list(term.a.variants)
                entry["b"]["variants"] = list(term.b.variants)
                entries.append(entry)
        items.append({"id": glossary.id, "name": glossary.name,
                      "parent_id": glossary.parent_id, "terms": entries})
        if glossary.parent_id is None:
            items[-1]["languages"] = list(glossary.languages) if glossary.languages is not None else []
    return {"format": "autolingua2-glossary", "version": 1, "glossaries": items}


def read_document(path: Path) -> GlossaryDocument:
    return parse_document(read_json(path))


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSONの形式が不正です（{exc.lineno}行、{exc.colno}列）。") from exc


def write_document(path: Path, document: GlossaryDocument) -> None:
    write_json(path, document_data(document))


def write_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    target = QSaveFile(str(path))
    if not target.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(target.errorString())
    if target.write(payload) != len(payload):
        target.cancelWriting()
        raise OSError(target.errorString())
    if not target.commit():
        raise OSError(target.errorString())


def external_document(data: GlossaryImportData, name: str, languages: tuple[str, str],
                      source_language: str) -> GlossaryDocument:
    if source_language not in languages:
        raise ValueError("取り込む原文の言語が一致しません。")
    terms = tuple(replace(t, a=t.b, b=t.a) if source_language != languages[0] else t for t in data.terms)
    document = GlossaryDocument((Glossary("import", name, "", "", None, languages),),
                               tuple(replace(t, id="", glossary_id="import") for t in terms))
    return parse_document(document_data(document))


def build_export(glossaries: list[Glossary], terms: list[GlossaryTerm],
                 glossary_id: str, mode: ExportMode) -> GlossaryDocument:
    chain = glossary_chain(glossaries, glossary_id)
    selected = chain[-1]
    if mode in (ExportMode.OWN, ExportMode.FLAT):
        output = [replace(selected, parent_id=None, languages=chain[0].languages)]
        if mode == ExportMode.FLAT:
            terms = [replace(t, glossary_id=selected.id) for t in resolve_terms(chain, terms)]
    elif mode == ExportMode.ANCESTORS:
        output = chain
    else:
        output = [g for g in glossaries
                  if (g.adapter_id, g.game_id) == (selected.adapter_id, selected.game_id)]
    ids = {g.id for g in output}
    document = GlossaryDocument(tuple(output), tuple(t for t in terms if t.glossary_id in ids))
    return parse_document(document_data(document))
