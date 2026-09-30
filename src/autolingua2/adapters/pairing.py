from __future__ import annotations

from dataclasses import dataclass

from autolingua2.ir import TranslationUnit, UnitState

from .base import ImportedTranslation


@dataclass(frozen=True, slots=True)
class PairingSummary:
    matched: int
    untranslated: int
    translated: int


def apply_existing_translation(
    source: ImportedTranslation,
    translation: ImportedTranslation,
) -> PairingSummary:
    """Pair one source file with one existing translation file by localization key."""
    if len(source.project.sources) != 1 or len(translation.project.sources) != 1:
        raise ValueError("原文と既存訳はそれぞれ1ファイルを指定してください")

    source_by_key = _units_by_key(source)
    translation_by_key = _units_by_key(translation)
    updates: list[tuple[TranslationUnit, str, UnitState]] = []
    matched = 0
    untranslated = 0
    translated = 0

    for key, unit in source_by_key.items():
        translated_unit = translation_by_key.get(key)
        target_text = translated_unit.source_text if translated_unit is not None else ""
        if translated_unit is not None:
            matched += 1
        if not target_text.strip() or target_text == unit.source_text:
            state = UnitState.UNTRANSLATED
            untranslated += 1
        else:
            state = UnitState.TRANSLATED
            translated += 1
        updates.append((unit, target_text, state))

    for unit, target_text, state in updates:
        unit.target_text = target_text
        unit.state = state

    return PairingSummary(matched=matched, untranslated=untranslated, translated=translated)


def _units_by_key(imported: ImportedTranslation) -> dict[str, TranslationUnit]:
    result: dict[str, TranslationUnit] = {}
    for unit in imported.project.units:
        ref = imported.source_refs.get(unit.id)
        if ref is None:
            raise ValueError(f"キーの参照情報がありません: {unit.label}")
        key = ref.external_id
        if key in result:
            raise ValueError(f"同じキーがファイル内に複数あります: {key}")
        result[key] = unit
    return result
