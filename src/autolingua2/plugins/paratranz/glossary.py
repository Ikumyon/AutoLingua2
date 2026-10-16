"""ParaTranz terminology JSON; separate from its translation-file format."""
from dataclasses import replace

from autolingua2.plugins.contracts import (
    DirectedTerm, GlossaryTerm, TermSide, GlossaryImportData, GlossaryExportData,
)


# ParaTranz's Term.pos values (also used for the inverse export mapping).
PARTS = {"noun": "名詞", "verb": "動詞", "adj": "形容詞", "adv": "副詞"}
EXPORT_PARTS = {label: code for code, label in PARTS.items()}


def _text(entry: dict[str, object], field: str, *, optional: bool = False) -> str:
    value = entry.get(field, "" if optional else None)
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise ValueError(f"{field}は{'空でない' if not optional else ''}文字列で指定してください。")
    return value.strip()


class ParaTranzGlossaryFormat:
    id = "terms"
    name = "ParaTranz用語集"

    def decode(self, value: object) -> GlossaryImportData:
        if not isinstance(value, list):
            raise ValueError("ParaTranz用語集はJSON配列で指定してください。")
        groups: dict[tuple[str, str], GlossaryTerm] = {}
        for index, raw in enumerate(value, 1):
            try:
                if not isinstance(raw, dict) or any(not isinstance(k, str) for k in raw):
                    raise ValueError("用語はJSONオブジェクトで指定してください。")
                entry: dict[str, object] = dict(raw)
                source, target = _text(entry, "term"), _text(entry, "translation")
                pos, note = _text(entry, "pos"), _text(entry, "note", optional=True)
                part = PARTS.get(pos)
                if part is None:
                    raise ValueError(f"品詞が不正です：{pos}（noun・verb・adj・advを指定してください）")
                raw_variants = entry.get("variants", [])
                if not isinstance(raw_variants, list):
                    raise ValueError("variantsは文字列の配列で指定してください。")
                variants: list[str] = []
                for variant in raw_variants:
                    if not isinstance(variant, str):
                        raise ValueError("variantsは文字列の配列で指定してください。")
                    if variant.strip():
                        variants.append(variant.strip())
                key = (target, pos)
                existing = groups.get(key)
                if existing is None:
                    groups[key] = GlossaryTerm("", "import", part,
                        TermSide(source, tuple(dict.fromkeys(v for v in variants if v != source))),
                        TermSide(target), note, f"term-{len(groups) + 1}")
                else:
                    combined = tuple(dict.fromkeys(v for v in (*existing.a.variants, source, *variants)
                                                   if v != existing.a.text))
                    # Keep distinct notes as paragraphs, even on repeated imports.
                    notes = list(dict.fromkeys(p for p in (*existing.memo.split("\n\n"), *note.split("\n\n")) if p))
                    groups[key] = replace(existing, a=replace(existing.a, variants=combined), memo="\n\n".join(notes))
            except ValueError as exc:
                raise ValueError(f"用語{index}件目：{exc}") from exc
        terms = tuple(groups.values())
        seen: set[str] = set()
        for term in terms:
            expressions = {term.a.text, *term.a.variants}
            if seen & expressions:
                raise ValueError("同じ原文表現が異なる用語に対応しています。")
            seen.update(expressions)
        return GlossaryImportData(terms, len(value))

    def encode(self, terms: tuple[DirectedTerm, ...]) -> GlossaryExportData:
        entries: list[dict[str, object]] = []
        for term in terms:
            pos = EXPORT_PARTS.get(term.part_of_speech)
            if pos is None:
                raise ValueError(f"品詞が不正です：{term.part_of_speech}")
            entries.append({"term": term.source, "translation": term.translation, "variants": list(term.variants),
                            "pos": pos, "note": term.memo})
        return GlossaryExportData(entries, sum(len(t.target_variants) for t in terms),
                                  sum(int(t.case_sensitive) + int(t.target_case_sensitive) for t in terms))
